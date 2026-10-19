"""Isolated Café Bokharest demo ordering. No orders are sent to the restaurant.

Optional WhatsApp Cloud API template notifications require private environment
credentials and a Meta-approved, three-variable template. Default is OFF.
"""
from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import sqlite3
import time
import urllib.request
from collections import defaultdict, deque
from datetime import datetime, timezone
from threading import Lock
from urllib.parse import quote

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from bokharest_ordering import BokharestCart, BokharestOrder, _connect, _quote


def _setup(db_path):
    db = _connect(db_path)
    try:
        db.executescript("""
          CREATE TABLE IF NOT EXISTS bokharest_demo_orders(
            id INTEGER PRIMARY KEY,
            reference TEXT NOT NULL UNIQUE,
            idempotency_key TEXT NOT NULL UNIQUE,
            tracking_token TEXT NOT NULL,
            table_no INTEGER NOT NULL CHECK(table_no BETWEEN 1 AND 500),
            note TEXT NOT NULL DEFAULT '',
            subtotal_piasters INTEGER NOT NULL,
            service_piasters INTEGER NOT NULL,
            vat_piasters INTEGER NOT NULL,
            total_piasters INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'demo',
            alert_status TEXT NOT NULL DEFAULT 'not_configured',
            created_at TEXT NOT NULL
          );
          CREATE TABLE IF NOT EXISTS bokharest_demo_lines(
            id INTEGER PRIMARY KEY,
            order_id INTEGER NOT NULL REFERENCES bokharest_demo_orders(id),
            item_id INTEGER NOT NULL,
            name_ar TEXT NOT NULL,
            unit_price_piasters INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            line_total_piasters INTEGER NOT NULL
          );
          CREATE INDEX IF NOT EXISTS idx_bokharest_demo_created ON bokharest_demo_orders(created_at);
        """)
    finally:
        db.close()


def _recipient():
    value = os.getenv("BOKHAREST_ALERT_PHONE", "").strip().lstrip("+")
    return value if re.fullmatch(r"[1-9][0-9]{9,14}", value) else ""


def _wa_ready():
    return bool(_recipient() and os.getenv("BOKHAREST_WA_TOKEN")
                and os.getenv("BOKHAREST_WA_PHONE_ID")
                and os.getenv("BOKHAREST_WA_TEMPLATE"))


def _send_whatsapp(order, lines):
    """Returns accepted_by_provider, failed, or not_configured.

    The Meta-approved template must have three body placeholders:
    table number, item list and demo estimated total.
    """
    if not _wa_ready():
        return "not_configured"
    template_name = os.getenv("BOKHAREST_WA_TEMPLATE", "")
    phone_id = os.getenv("BOKHAREST_WA_PHONE_ID", "")
    api_version = os.getenv("BOKHAREST_WA_API_VERSION", "v23.0")
    if not re.fullmatch(r"[A-Za-z0-9_]+", template_name) or not re.fullmatch(r"[0-9]+", phone_id) or not re.fullmatch(r"v[0-9]+\.[0-9]+", api_version):
        return "failed"
    items = "؛ ".join(str(x["quantity"]) + " × " + x["name_ar"] for x in lines)[:900]
    total = f'{order["total_piasters"] / 100:.2f} EGP (DEMO)'
    payload = {
        "messaging_product": "whatsapp", "to": _recipient(), "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": os.getenv("BOKHAREST_WA_TEMPLATE_LANG", "ar")},
            "components": [{"type": "body", "parameters": [
                {"type": "text", "text": str(order["table_no"])},
                {"type": "text", "text": items},
                {"type": "text", "text": total}
            ]}]
        }
    }
    request = urllib.request.Request(
        "https://graph.facebook.com/" + api_version + "/" + phone_id + "/messages",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": "Bearer " + os.environ["BOKHAREST_WA_TOKEN"],
                 "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=6) as response:
            body = json.loads(response.read(64000).decode("utf-8"))
        return "accepted_by_provider" if body.get("messages") else "failed"
    except Exception:
        return "failed"


def install_bokharest_demo(app, db_path, is_admin, verify_csrf, csrf_for, templates):
    _setup(db_path)
    attempts = defaultdict(deque)
    lock = Lock()

    @app.post("/api/bokharest/quote")
    def quote_cart(payload: BokharestCart):
        """Price a test cart using the separate, server-side Bokharest menu."""
        return _quote(payload.items)

    @app.post("/api/bokharest/quote")
    def calculate_demo_quote(cart: BokharestCart):
        return _quote(cart.items)

    @app.post("/api/bokharest/demo-orders", status_code=201)
    def place_demo_order(payload: BokharestOrder, request: Request):
        quote_data = _quote(payload.items)
        if quote_data["total_piasters"] != payload.expected_total_piasters:
            raise HTTPException(409, "الإجمالي اتغير؛ راجعي الطلب مرة تانية.")
        # Demo sends no real restaurant requests. Limit abuse and WhatsApp spam.
        key = request.client.host if request.client else "unknown"
        stamp = time.monotonic()
        with lock:
            for name, limit in (("global", 80), (key, 5)):
                queue = attempts[name]
                while queue and queue[0] < stamp - 3600:
                    queue.popleft()
                if len(queue) >= limit:
                    raise HTTPException(429, "محاولات كتير؛ جربي بعد شوية.")
            attempts["global"].append(stamp)
            attempts[key].append(stamp)

        db = _connect(db_path)
        try:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM bokharest_demo_orders WHERE idempotency_key=?",
                                  (payload.idempotency_key,)).fetchone()
            if existing:
                if existing["table_no"] != payload.table_no or existing["total_piasters"] != quote_data["total_piasters"]:
                    raise HTTPException(409, "رقم العملية مستخدم لطلب مختلف.")
                db.commit()
                return {"reference": existing["reference"], "status": "demo",
                        "alert_status": existing["alert_status"],
                        "total_piasters": existing["total_piasters"]}
            ref = "BKH-TEST-" + secrets.token_hex(5).upper()
            token = secrets.token_urlsafe(24)
            created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            cur = db.execute("""INSERT INTO bokharest_demo_orders
                (reference,idempotency_key,tracking_token,table_no,note,subtotal_piasters,
                 service_piasters,vat_piasters,total_piasters,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (ref, payload.idempotency_key, token, payload.table_no, payload.note.strip(),
                 quote_data["subtotal_piasters"], quote_data["service_piasters"],
                 quote_data["vat_piasters"], quote_data["total_piasters"], created_at))
            demo_id = cur.lastrowid
            db.executemany("""INSERT INTO bokharest_demo_lines
                (order_id,item_id,name_ar,unit_price_piasters,quantity,line_total_piasters)
                VALUES (?,?,?,?,?,?)""",
                [(demo_id, item["item_id"], item["name_ar"], item["unit_price_piasters"],
                  item["quantity"], item["line_total_piasters"]) for item in quote_data["items"]])
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

        alert = _send_whatsapp({"table_no": payload.table_no,
                                 "total_piasters": quote_data["total_piasters"]}, quote_data["items"])
        with _connect(db_path) as db:
            db.execute("UPDATE bokharest_demo_orders SET alert_status=? WHERE id=?", (alert, demo_id))
        return {"reference": ref, "status": "demo", "alert_status": alert,
                "total_piasters": quote_data["total_piasters"]}

    @app.get("/admin/bokharest-demo", response_class=HTMLResponse)
    def admin_demo(request: Request):
        if not is_admin(request):
            return RedirectResponse("/admin/login", status_code=303)
        with _connect(db_path) as db:
            orders = [dict(row) for row in db.execute(
                "SELECT * FROM bokharest_demo_orders ORDER BY id DESC LIMIT 100")]
            for order in orders:
                order["lines"] = [dict(row) for row in db.execute(
                    "SELECT * FROM bokharest_demo_lines WHERE order_id=?", (order["id"],))]
        return templates.TemplateResponse(request, "bokharest_demo_admin.html", {
            "orders": orders, "csrf": csrf_for(request), "whatsapp_ready": _wa_ready()
        })

    @app.post("/admin/bokharest-demo/{order_id}/status")
    async def admin_update_demo(order_id: int, request: Request):
        form = await request.form()
        verify_csrf(request, str(form.get("csrf", "")))
        status = str(form.get("status", ""))
        if status not in ("demo", "reviewed", "archived"):
            raise HTTPException(422, "حالة غير صحيحة")
        with _connect(db_path) as db:
            cur = db.execute("UPDATE bokharest_demo_orders SET status=? WHERE id=?", (status, order_id))
            if not cur.rowcount:
                raise HTTPException(404, "الطلب غير موجود")
        return RedirectResponse("/admin/bokharest-demo", status_code=303)
