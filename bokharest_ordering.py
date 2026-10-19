"""Isolated, server-priced Café Bokharest dine-in ordering pilot.

Safe by default: accepting actual orders requires explicit restaurant approval,
an approved menu and BOKHAREST_ORDERS_ENABLED=1. Nothing enters demo orders.
"""
from __future__ import annotations

import hmac
import json
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

MENU_PATH = Path(__file__).resolve().parent / "static" / "data" / "bokharest_menu.json"
STATES = ("new", "accepted", "preparing", "ready", "completed", "cancelled")


class BokharestLine(BaseModel):
    item_id: int = Field(gt=0)
    quantity: int = Field(ge=1, le=20)


class BokharestCart(BaseModel):
    items: list[BokharestLine] = Field(min_length=1, max_length=40)


class BokharestOrder(BokharestCart):
    table_no: int = Field(ge=1, le=500)
    note: str = Field(default="", max_length=250)
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9_-]{16,100}$")
    expected_total_piasters: int = Field(ge=1)


def _connect(db_path: Path):
    db = sqlite3.connect(db_path, timeout=10, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=10000")
    return db


def _catalog():
    data = json.loads(MENU_PATH.read_text(encoding="utf-8"))
    items = {}
    for category in data["categories"]:
        for item in category["items"]:
            if item["id"] in items:
                raise RuntimeError("Duplicate Bokharest item id")
            items[item["id"]] = item
    return data["restaurant"], items


def _enabled(restaurant):
    # The three separate controls prevent public orders being sent to a
    # restaurant based only on third-party menu photos.
    return (restaurant.get("checkout_enabled") is True
            and restaurant.get("status") == "approved-live"
            and os.getenv("BOKHAREST_ORDERS_ENABLED", "").lower() in ("1", "true")
            and os.getenv("BOKHAREST_RESTAURANT_APPROVED", "").lower() in ("1", "true"))


def _quote(lines: list[BokharestLine]):
    restaurant, catalog = _catalog()
    if len({line.item_id for line in lines}) != len(lines):
        raise HTTPException(422, "لا تكرري الصنف مرتين؛ عدّلي الكمية.")
    if sum(x.quantity for x in lines) > 80:
        raise HTTPException(422, "حد أقصى 80 قطعة في الطلب.")
    subtotal = 0
    details = []
    for line in lines:
        item = catalog.get(line.item_id)
        if not item:
            raise HTTPException(409, "صنف غير موجود في منيو بوخاريست.")
        price = item["price_piasters"]
        subtotal += price * line.quantity
        details.append({"item_id": line.item_id, "name_ar": item["name_ar"],
                        "name_en": item["name_en"], "unit_price_piasters": price,
                        "quantity": line.quantity, "line_total_piasters": price * line.quantity})
    if subtotal > 10_000_000:
        raise HTTPException(422, "قيمة الطلب أكبر من الحد المسموح.")
    service_rate = restaurant.get("service_charge_percent", 0)
    vat_rate = restaurant.get("vat_percent", 0)
    if not all(type(x) is int and 0 <= x <= 30 for x in (service_rate, vat_rate)):
        raise RuntimeError("Unapproved charges configuration")
    # Estimates only until the restaurant confirms its receipt calculation.
    service = (subtotal * service_rate + 50) // 100
    vat = ((subtotal + service) * vat_rate + 50) // 100
    return {"restaurant": "bokharest", "items": details,
            "subtotal_piasters": subtotal, "service_piasters": service,
            "vat_piasters": vat, "total_piasters": subtotal + service + vat,
            "estimated": not _enabled(restaurant), "checkout_enabled": _enabled(restaurant)}


def _bootstrap(db_path: Path):
    db = _connect(db_path)
    try:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS bokharest_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference TEXT UNIQUE NOT NULL,
            idempotency_key TEXT UNIQUE NOT NULL,
            tracking_token TEXT NOT NULL,
            table_no INTEGER NOT NULL CHECK(table_no BETWEEN 1 AND 500),
            note TEXT NOT NULL DEFAULT '',
            subtotal_piasters INTEGER NOT NULL,
            service_piasters INTEGER NOT NULL,
            vat_piasters INTEGER NOT NULL,
            total_piasters INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'new',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS bokharest_order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL REFERENCES bokharest_orders(id),
            item_id INTEGER NOT NULL,
            name_snapshot TEXT NOT NULL,
            unit_price_piasters INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            line_total_piasters INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_bokharest_orders_status
          ON bokharest_orders(status, created_at);
        """)
    finally:
        db.close()


def install_bokharest_ordering(app, db_path, is_admin, verify_csrf, csrf_for, templates):
    """Install restaurant-scoped routes without touching the sample restaurant."""
    _bootstrap(db_path)

    @app.get("/api/bokharest/ordering-config")
    def bokharest_config():
        restaurant, _ = _catalog()
        return {"checkout_enabled": _enabled(restaurant), "restaurant": "bokharest",
                "service_charge_percent": restaurant["service_charge_percent"],
                "vat_percent": restaurant["vat_percent"], "mode": "dine-in"}

    @app.post("/api/bokharest/quote")
    def bokharest_quote(cart: BokharestCart):
        return _quote(cart.items)

    @app.post("/api/bokharest/orders", status_code=201)
    def bokharest_place(order: BokharestOrder):
        restaurant, _ = _catalog()
        if not _enabled(restaurant):
            raise HTTPException(403, "بوخاريست لم يعتمد استقبال الطلبات بعد؛ السلة تجريبية.")
        quote = _quote(order.items)
        if quote["total_piasters"] != order.expected_total_piasters:
            raise HTTPException(409, "الإجمالي تغير؛ راجعي الطلب قبل الإرسال.")
        db = _connect(db_path)
        try:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM bokharest_orders WHERE idempotency_key=?",
                                  (order.idempotency_key,)).fetchone()
            if existing:
                if existing["total_piasters"] != quote["total_piasters"] or existing["table_no"] != order.table_no:
                    raise HTTPException(409, "مفتاح الطلب مستخدم لطلب مختلف.")
                db.commit()
                return {"reference": existing["reference"], "tracking_token": existing["tracking_token"],
                        "status": existing["status"], "total_piasters": existing["total_piasters"]}
            stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
            ref = "BKH-" + secrets.token_hex(5).upper()
            token = secrets.token_urlsafe(24)
            cur = db.execute("""INSERT INTO bokharest_orders
                (reference,idempotency_key,tracking_token,table_no,note,subtotal_piasters,
                 service_piasters,vat_piasters,total_piasters,status,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (ref, order.idempotency_key, token, order.table_no, order.note.strip(),
                 quote["subtotal_piasters"], quote["service_piasters"], quote["vat_piasters"],
                 quote["total_piasters"], "new", stamp, stamp))
            db.executemany("""INSERT INTO bokharest_order_items
                (order_id,item_id,name_snapshot,unit_price_piasters,quantity,line_total_piasters)
                VALUES (?,?,?,?,?,?)""",
                [(cur.lastrowid, i["item_id"], i["name_ar"], i["unit_price_piasters"],
                  i["quantity"], i["line_total_piasters"]) for i in quote["items"]])
            db.commit()
            return {"reference": ref, "tracking_token": token,
                    "status": "new", "total_piasters": quote["total_piasters"]}
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @app.get("/api/bokharest/orders/{reference}")
    def bokharest_track(reference: str, token: str = ""):
        if not token or len(token) > 100:
            raise HTTPException(404, "الطلب غير موجود")
        db = _connect(db_path)
        try:
            row = db.execute("SELECT * FROM bokharest_orders WHERE reference=?", (reference,)).fetchone()
        finally:
            db.close()
        if not row or not hmac.compare_digest(row["tracking_token"], token):
            raise HTTPException(404, "الطلب غير موجود")
        return {"reference": row["reference"], "status": row["status"],
                "total_piasters": row["total_piasters"], "created_at": row["created_at"]}

    @app.get("/admin/bokharest-orders", response_class=HTMLResponse)
    def bokharest_admin(request: Request):
        if not is_admin(request):
            return RedirectResponse("/admin/login", status_code=303)
        db = _connect(db_path)
        try:
            rows = [dict(row) for row in db.execute(
                "SELECT * FROM bokharest_orders ORDER BY id DESC LIMIT 100")]
            for row in rows:
                row["items"] = [dict(item) for item in db.execute(
                    "SELECT * FROM bokharest_order_items WHERE order_id=?", (row["id"],))]
        finally:
            db.close()
        return templates.TemplateResponse(request, "bokharest_admin.html",
                                          {"orders": rows, "statuses": STATES,
                                           "checkout_enabled": _enabled(_catalog()[0]),
                                           "csrf": csrf_for(request)})

    @app.post("/admin/bokharest-orders/{order_id}/status")
    async def bokharest_status(order_id: int, request: Request):
        form = await request.form()
        verify_csrf(request, str(form.get("csrf", "")))
        state = str(form.get("status", ""))
        if state not in STATES:
            raise HTTPException(422, "حالة غير معروفة")
        db = _connect(db_path)
        try:
            cur = db.execute("UPDATE bokharest_orders SET status=?,updated_at=? WHERE id=?",
                             (state, datetime.now(timezone.utc).isoformat(timespec="seconds"), order_id))
            if cur.rowcount == 0:
                raise HTTPException(404, "الطلب غير موجود")
        finally:
            db.close()
        return RedirectResponse("/admin/bokharest-orders", status_code=303)
