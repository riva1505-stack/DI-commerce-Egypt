"""Tenant-isolated restaurant pilots with durable, resized dish photos.

This module intentionally does not share the legacy single-restaurant order or admin
tables. All restaurant reads and writes require an explicit tenant id derived from a
validated URL slug or an authenticated tenant session.
Photos live in the persistent SQLite database on Railway's /app/data volume.
"""
from __future__ import annotations

import hashlib
import hmac
import io
import json
import re
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from itsdangerous import BadData, URLSafeTimedSerializer
from pydantic import BaseModel, Field
from starlette.datastructures import UploadFile

from auth_security import hash_password, parse_password_hash
from assistant_engine import guided_chat

SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,45}[a-z0-9])?$")
LIMIT_UPLOAD_BYTES = 5 * 1024 * 1024
LIMIT_PHOTO_BYTES = 2 * 1024 * 1024
TENANT_PHOTO_QUOTA = 90 * 1024 * 1024
SESSION_SECONDS = 8 * 60 * 60


def _connect(path: Path):
    db = sqlite3.connect(path, timeout=10, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=10000")
    return db


def initialize(path: Path):
    with _connect(path) as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS tenant_restaurants (
          id INTEGER PRIMARY KEY, slug TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
          password_hash TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tenant_menu (
          id INTEGER PRIMARY KEY, tenant_id INTEGER NOT NULL
            REFERENCES tenant_restaurants(id) ON DELETE CASCADE,
          name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
          category TEXT NOT NULL DEFAULT 'أخرى', emoji TEXT NOT NULL DEFAULT '🍽️',
          price_piasters INTEGER NOT NULL CHECK(price_piasters >= 0),
          available INTEGER NOT NULL DEFAULT 1 CHECK(available IN (0,1))
        );
        CREATE INDEX IF NOT EXISTS idx_tenant_menu ON tenant_menu(tenant_id, available);
        CREATE TABLE IF NOT EXISTS tenant_photos (
          tenant_id INTEGER NOT NULL REFERENCES tenant_restaurants(id),
          item_id INTEGER PRIMARY KEY REFERENCES tenant_menu(id) ON DELETE CASCADE,
          data BLOB NOT NULL, version TEXT NOT NULL,
          CHECK(length(data)<=2097152)
        );
        CREATE TABLE IF NOT EXISTS tenant_demo_orders (
          id INTEGER PRIMARY KEY,
          tenant_id INTEGER NOT NULL REFERENCES tenant_restaurants(id),
          table_no INTEGER NOT NULL, note TEXT NOT NULL DEFAULT '',
          total_piasters INTEGER NOT NULL, lines_json TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'demo', created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_tenant_orders ON tenant_demo_orders(tenant_id,id);
        CREATE TABLE IF NOT EXISTS tenant_demo_request_limits (
          tenant_id INTEGER NOT NULL REFERENCES tenant_restaurants(id),
          bucket TEXT NOT NULL, window_start INTEGER NOT NULL, count INTEGER NOT NULL,
          PRIMARY KEY (tenant_id, bucket)
        );

        """)


def _tenant(db, slug: str):
    if not SLUG.fullmatch(slug):
        raise HTTPException(404, "مطعم غير موجود")
    row = db.execute("SELECT * FROM tenant_restaurants WHERE slug=?", (slug,)).fetchone()
    if not row:
        raise HTTPException(404, "مطعم غير موجود")
    return row


def _slug(value: str):
    value = value.lower().strip()
    if not SLUG.fullmatch(value):
        raise HTTPException(422, "الرابط لازم يكون حروف إنجليزية صغيرة أو أرقام أو شرطات.")
    return value


def _money(raw: str):
    from decimal import Decimal, InvalidOperation
    try:
        n = Decimal(str(raw))
        if not n.is_finite() or n < 0 or n > 100000 or n.as_tuple().exponent < -2:
            raise ValueError()
        return int(n * 100)
    except (ValueError, TypeError, InvalidOperation) as exc:
        raise HTTPException(422, "السعر غير صحيح") from exc


def _password_matches(raw: str, encoded: str) -> bool:
    if not raw or len(raw.encode()) > 1024:
        return False
    iterations, salt, expected = parse_password_hash(encoded)
    actual = hashlib.pbkdf2_hmac("sha256", raw.encode(), salt, iterations)
    return hmac.compare_digest(actual, expected)


def _menu(db, tenant_id: int, include_unavailable: bool = False):
    rows = db.execute(
        "SELECT m.*,p.version AS photo_version FROM tenant_menu m "
        "LEFT JOIN tenant_photos p ON p.item_id=m.id AND p.tenant_id=m.tenant_id "
        "WHERE m.tenant_id=?" + ("" if include_unavailable else " AND m.available=1") +
        " ORDER BY m.id", (tenant_id,)
    ).fetchall()
    return [dict(r) | {"has_photo": bool(r["photo_version"])} for r in rows]


def _encode_photo(data: bytes) -> bytes:
    if not data or len(data) > LIMIT_UPLOAD_BYTES:
        raise HTTPException(413, "الصورة لازم تكون أقل من 5 ميجابايت.")
    try:
        with Image.open(io.BytesIO(data)) as opened:
            if opened.format not in ("JPEG", "PNG", "WEBP"):
                raise HTTPException(415, "الصور المسموحة: JPG أو PNG أو WebP فقط.")
            opened.verify()
        with Image.open(io.BytesIO(data)) as opened:
            fixed = ImageOps.exif_transpose(opened)
            if fixed.width > 12000 or fixed.height > 12000 or fixed.width * fixed.height > 30_000_000:
                raise HTTPException(413, "أبعاد الصورة كبيرة جدًا.")
            fixed.thumbnail((1100, 1100))
            rgb = fixed.convert("RGB")
            out = io.BytesIO()
            rgb.save(out, "WEBP", quality=77, method=4)
            result = out.getvalue()
            if len(result) > LIMIT_PHOTO_BYTES:
                raise HTTPException(413, "تعذّر ضغط الصورة للحجم المسموح.")
            return result
    except HTTPException:
        raise
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise HTTPException(422, "ملف الصورة غير صالح.") from exc


def _limit_demo_requests(db, tenant_id: int, request: Request):
    """Global, shared-SQLite limits; do not retain raw client IPs."""
    now = int(time.time())
    ip = request.client.host if request.client else "unknown"
    bucket = hashlib.sha256(ip.encode("utf-8")).hexdigest()[:32]
    for label, limit in ((bucket, 10), ("all", 45)):
        row = db.execute(
            "SELECT window_start,count FROM tenant_demo_request_limits "
            "WHERE tenant_id=? AND bucket=?", (tenant_id, label)
        ).fetchone()
        if row and now - row["window_start"] < 60:
            if row["count"] >= limit:
                raise HTTPException(429, "طلبات تجريبية كثيرة. حاولي بعد دقيقة.",
                                    headers={"Retry-After": "60"})
            db.execute(
                "UPDATE tenant_demo_request_limits SET count=count+1 "
                "WHERE tenant_id=? AND bucket=?", (tenant_id, label)
            )
        else:
            db.execute(
                "INSERT INTO tenant_demo_request_limits(tenant_id,bucket,window_start,count) "
                "VALUES(?,?,?,1) ON CONFLICT(tenant_id,bucket) "
                "DO UPDATE SET window_start=excluded.window_start,count=1",
                (tenant_id, label, now)
            )
    # Bounded bookkeeping: expired counts do not grow across days.
    db.execute("DELETE FROM tenant_demo_request_limits WHERE window_start<?",
               (now - 120,))


def _stamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MenuChat(BaseModel):
    message: str = Field(min_length=1, max_length=300)


class DemoOrder(BaseModel):
    table_no: int = Field(ge=1, le=500)
    note: str = Field(default="", max_length=180)
    items: list[dict] = Field(min_length=1, max_length=20)


def install_tenant_platform(app, db_path: Path, is_platform_admin, platform_csrf,
                            platform_csrf_for, secret_key: str, production: bool,
                            templates, login_throttle):
    initialize(db_path)

    def _cookie(slug):
        return "di_restaurant_" + slug.replace("-", "_")

    def _serializer(slug):
        return URLSafeTimedSerializer(secret_key, salt="di-tenant-v1-" + slug)

    def _check(request: Request, tenant):
        token = request.cookies.get(_cookie(tenant["slug"]), "")
        try:
            data = _serializer(tenant["slug"]).loads(token, max_age=SESSION_SECONDS)
            if (data.get("tenant") == tenant["id"] and
                    hmac.compare_digest(str(data.get("pwd", "")),
                                        hashlib.sha256(tenant["password_hash"].encode()).hexdigest())):
                return token
        except (BadData, AttributeError, TypeError):
            pass
        raise HTTPException(401, "سجّلي الدخول للوحة إدارة المطعم.")

    def _csrf(request: Request, tenant, supplied):
        token = _check(request, tenant)
        valid = hmac.new(secret_key.encode(),
                         ("tenant-csrf:" + tenant["slug"] + ":" + token).encode(),
                         hashlib.sha256).hexdigest()
        if not hmac.compare_digest(valid, str(supplied)):
            raise HTTPException(403, "رمز حماية النموذج غير صحيح.")

    def _form_csrf(request, tenant):
        token = _check(request, tenant)
        return hmac.new(secret_key.encode(),
                        ("tenant-csrf:" + tenant["slug"] + ":" + token).encode(),
                        hashlib.sha256).hexdigest()

    @app.get("/restaurants", response_class=HTMLResponse)
    def restaurant_directory(request: Request):
        with _connect(db_path) as db:
            tenants = db.execute("SELECT slug,name FROM tenant_restaurants ORDER BY id").fetchall()
        return templates.TemplateResponse(request, "tenant_directory.html",
                                          {"tenants": tenants})

    @app.get("/admin/restaurants", response_class=HTMLResponse)
    def platform_restaurants(request: Request):
        if not is_platform_admin(request):
            return RedirectResponse("/admin/login", status_code=303)
        with _connect(db_path) as db:
            tenants = db.execute("SELECT id,slug,name FROM tenant_restaurants ORDER BY id").fetchall()
        return templates.TemplateResponse(request, "tenant_platform_admin.html",
                                          {"tenants": tenants, "csrf": platform_csrf_for(request)})

    @app.post("/admin/restaurants")
    async def add_restaurant(request: Request):
        form = await request.form()
        platform_csrf(request, str(form.get("csrf", "")))
        slug = _slug(str(form.get("slug", "")))
        name = str(form.get("name", "")).strip()[:100]
        password = str(form.get("password", ""))
        if not name or len(password) < 12 or len(password.encode()) > 1024:
            raise HTTPException(422, "اسم المطعم وكلمة مرور قوية من 12 حرف على الأقل مطلوبين.")
        password_digest = hash_password(password)
        with _connect(db_path) as db:
            try:
                db.execute("INSERT INTO tenant_restaurants(slug,name,password_hash,created_at) "
                           "VALUES(?,?,?,?)", (slug, name, password_digest, _stamp()))
            except sqlite3.IntegrityError as exc:
                raise HTTPException(409, "رابط المطعم ده مستخدم بالفعل.") from exc
        return RedirectResponse("/admin/restaurants", status_code=303)

    @app.post("/admin/restaurants/{slug}/reset-password")
    async def reset_restaurant_password(slug: str, request: Request):
        form = await request.form()
        platform_csrf(request, str(form.get("csrf", "")))
        password = str(form.get("password", ""))
        if len(password) < 12 or len(password.encode()) > 1024:
            raise HTTPException(422, "كلمة المرور لا تقل عن 12 حرف.")
        digest = hash_password(password)
        with _connect(db_path) as db:
            tenant = _tenant(db, slug)
            db.execute("UPDATE tenant_restaurants SET password_hash=? WHERE id=?",
                       (digest, tenant["id"]))
        return RedirectResponse("/admin/restaurants", status_code=303)

    @app.get("/r/{slug}", response_class=HTMLResponse)
    def restaurant_page(slug: str, request: Request):
        with _connect(db_path) as db:
            tenant = _tenant(db, slug)
        return templates.TemplateResponse(request, "tenant_customer.html",
                                          {"tenant": tenant})

    @app.get("/r/{slug}/api/menu")
    def restaurant_menu(slug: str):
        with _connect(db_path) as db:
            tenant = _tenant(db, slug)
            return {"restaurant": {"name": tenant["name"], "slug": slug},
                    "items": _menu(db, tenant["id"]), "demo_only": True}

    @app.post("/r/{slug}/api/chat")
    def restaurant_chat(slug: str, payload: MenuChat):
        with _connect(db_path) as db:
            tenant = _tenant(db, slug)
            items = _menu(db, tenant["id"])
        catalog = [dict(p) | {"addons": [], "tags": ""} for p in items]
        answer = guided_chat([{"role": "user", "content": payload.message}], catalog)
        return answer | {"mode": "catalogue-demo", "demo_only": True}

    @app.get("/r/{slug}/images/{item_id}.webp")
    def restaurant_dish_photo(slug: str, item_id: int):
        with _connect(db_path) as db:
            tenant = _tenant(db, slug)
            row = db.execute("SELECT p.data FROM tenant_photos p JOIN tenant_menu m "
                "ON m.id=p.item_id AND m.tenant_id=p.tenant_id "
                "WHERE p.item_id=? AND p.tenant_id=? AND m.available=1",
                (item_id, tenant["id"])).fetchone()
        if not row:
            raise HTTPException(404, "الصورة مش موجودة.")
        return Response(row["data"], media_type="image/webp",
                        headers={"Cache-Control": "private, max-age=30"})

    @app.get("/r/{slug}/admin/login", response_class=HTMLResponse)
    def restaurant_login_page(slug: str, request: Request):
        with _connect(db_path) as db:
            tenant = _tenant(db, slug)
        return templates.TemplateResponse(request, "tenant_login.html",
                                          {"tenant": tenant, "error": False})

    @app.post("/r/{slug}/admin/login")
    async def restaurant_login(slug: str, request: Request):
        with _connect(db_path) as db:
            tenant = _tenant(db, slug)
        retry = login_throttle("tenant-" + slug + ":" + (request.client.host if request.client else "unknown"))
        if retry:
            raise HTTPException(429, "محاولات دخول كثيرة، حاولي بعد دقائق.")
        form = await request.form()
        if not _password_matches(str(form.get("password", "")), tenant["password_hash"]):
            return templates.TemplateResponse(request, "tenant_login.html",
                                              {"tenant": tenant, "error": True}, status_code=401)
        token = _serializer(slug).dumps(
            {"tenant": tenant["id"], "pwd": hashlib.sha256(tenant["password_hash"].encode()).hexdigest()})
        response = RedirectResponse(f"/r/{slug}/admin", status_code=303)
        response.set_cookie(_cookie(slug), token, httponly=True,
                            secure=production, samesite="lax", max_age=SESSION_SECONDS,
                            path=f"/r/{slug}")
        return response

    @app.post("/r/{slug}/admin/logout")
    async def restaurant_logout(slug: str, request: Request):
        with _connect(db_path) as db:
            tenant = _tenant(db, slug)
        form = await request.form()
        _csrf(request, tenant, form.get("csrf", ""))
        response = RedirectResponse(f"/r/{slug}/admin/login", status_code=303)
        response.delete_cookie(_cookie(slug), path=f"/r/{slug}")
        return response

    @app.get("/r/{slug}/admin", response_class=HTMLResponse)
    def restaurant_admin(slug: str, request: Request):
        with _connect(db_path) as db:
            tenant = _tenant(db, slug)
            try:
                csrf = _form_csrf(request, tenant)
            except HTTPException:
                return RedirectResponse(f"/r/{slug}/admin/login", status_code=303)
            items = _menu(db, tenant["id"], include_unavailable=True)
            orders = db.execute("SELECT * FROM tenant_demo_orders WHERE tenant_id=? ORDER BY id DESC LIMIT 30",
                                (tenant["id"],)).fetchall()
        return templates.TemplateResponse(request, "tenant_admin.html",
            {"tenant": tenant, "items": items, "orders": orders, "csrf": csrf})

    @app.post("/r/{slug}/admin/menu")
    async def restaurant_create_dish(slug: str, request: Request):
        form = await request.form()
        with _connect(db_path) as db:
            tenant = _tenant(db, slug)
            _csrf(request, tenant, form.get("csrf", ""))
            name = str(form.get("name", "")).strip()[:90]
            cat = str(form.get("category", "")).strip()[:50]
            if not name or not cat:
                raise HTTPException(422, "اسم الطبق والقسم مطلوبان.")
            price = _money(str(form.get("price", "")))
            db.execute("INSERT INTO tenant_menu(tenant_id,name,description,category,emoji,price_piasters) "
                       "VALUES(?,?,?,?,?,?)", (tenant["id"], name,
                       str(form.get("description", "")).strip()[:250], cat,
                       str(form.get("emoji", "🍽️")).strip()[:8] or "🍽️", price))
        return RedirectResponse(f"/r/{slug}/admin#menu", status_code=303)

    @app.post("/r/{slug}/admin/menu/{item_id}")
    async def restaurant_edit_dish(slug: str, item_id: int, request: Request):
        form = await request.form()
        with _connect(db_path) as db:
            tenant = _tenant(db, slug)
            _csrf(request, tenant, form.get("csrf", ""))
            name = str(form.get("name", "")).strip()[:90]
            category = str(form.get("category", "")).strip()[:50]
            if not name or not category:
                raise HTTPException(422, "اسم الطبق والقسم مطلوبان.")
            updated = db.execute(
                "UPDATE tenant_menu SET name=?,description=?,category=?,emoji=?,price_piasters=?,available=? "
                "WHERE id=? AND tenant_id=?",
                (name, str(form.get("description", "")).strip()[:250], category,
                 str(form.get("emoji", "🍽️")).strip()[:8] or "🍽️",
                 _money(str(form.get("price", ""))),
                 1 if form.get("available") == "on" else 0,
                 item_id, tenant["id"]))
            if updated.rowcount != 1:
                raise HTTPException(404, "الطبق مش موجود في المطعم ده.")
        return RedirectResponse(f"/r/{slug}/admin#menu", status_code=303)

    @app.post("/r/{slug}/admin/menu/{item_id}/photo")
    async def restaurant_upload_photo(slug: str, item_id: int, request: Request):
        form = await request.form()
        with _connect(db_path) as db:
            tenant = _tenant(db, slug)
            _csrf(request, tenant, form.get("csrf", ""))
            item = db.execute("SELECT id FROM tenant_menu WHERE id=? AND tenant_id=?",
                              (item_id, tenant["id"])).fetchone()
            if item is None:
                raise HTTPException(404, "الطبق مش موجود في مطعمك.")
            upload = form.get("photo")
            if not isinstance(upload, UploadFile):
                raise HTTPException(422, "اختاري صورة JPG أو PNG أو WebP.")
            photo = _encode_photo(await upload.read(LIMIT_UPLOAD_BYTES + 1))
            db.execute("BEGIN IMMEDIATE")
            used = db.execute("SELECT COALESCE(SUM(length(data)),0) FROM tenant_photos WHERE tenant_id=? "
                              "AND item_id!=?", (tenant["id"], item_id)).fetchone()[0]
            if used + len(photo) > TENANT_PHOTO_QUOTA:
                raise HTTPException(413, "المساحة المخصصة لصور المطعم ممتلئة.")
            db.execute("INSERT INTO tenant_photos(tenant_id,item_id,data,version) VALUES(?,?,?,?) "
                       "ON CONFLICT(item_id) DO UPDATE SET data=excluded.data,version=excluded.version "
                       "WHERE tenant_photos.tenant_id=excluded.tenant_id",
                       (tenant["id"], item_id, photo, secrets.token_hex(8)))
            db.commit()
        return RedirectResponse(f"/r/{slug}/admin#menu", status_code=303)

    @app.post("/r/{slug}/admin/menu/{item_id}/photo/delete")
    async def restaurant_delete_photo(slug: str, item_id: int, request: Request):
        form = await request.form()
        with _connect(db_path) as db:
            tenant = _tenant(db, slug)
            _csrf(request, tenant, form.get("csrf", ""))
            existing = db.execute("SELECT 1 FROM tenant_menu WHERE id=? AND tenant_id=?",
                                  (item_id, tenant["id"])).fetchone()
            if not existing:
                raise HTTPException(404, "الطبق مش موجود في مطعمك.")
            db.execute("DELETE FROM tenant_photos WHERE item_id=? AND tenant_id=?",
                       (item_id, tenant["id"]))
        return RedirectResponse(f"/r/{slug}/admin#menu", status_code=303)

    @app.post("/r/{slug}/api/orders")
    def restaurant_demo_order(slug: str, payload: DemoOrder, request: Request):
        with _connect(db_path) as db:
            tenant = _tenant(db, slug)
            ids = [x.get("id") for x in payload.items]
            if (len(ids) != len(set(str(v) for v in ids)) or
                any(type(x.get("id")) is not int or type(x.get("quantity")) is not int
                    or not 1 <= x["quantity"] <= 20 for x in payload.items)):
                raise HTTPException(422, "تفاصيل الطلب غير صحيحة.")
            db.execute("BEGIN IMMEDIATE")
            _limit_demo_requests(db, tenant["id"], request)
            lines = []
            total = 0
            for line in payload.items:
                item = db.execute("SELECT name,price_piasters FROM tenant_menu "
                                  "WHERE tenant_id=? AND id=? AND available=1",
                                  (tenant["id"], line["id"])).fetchone()
                if item is None:
                    raise HTTPException(409, "الصنف غير متاح في المطعم ده.")
                total += item["price_piasters"] * line["quantity"]
                lines.append({"id": line["id"], "name": item["name"],
                              "quantity": line["quantity"], "price_piasters": item["price_piasters"]})
            created = db.execute("INSERT INTO tenant_demo_orders("
                                 "tenant_id,table_no,note,total_piasters,lines_json,created_at) "
                                 "VALUES(?,?,?,?,?,?)",
                                 (tenant["id"], payload.table_no, payload.note,
                                  total, json.dumps(lines, ensure_ascii=False), _stamp()))
            db.execute("DELETE FROM tenant_demo_orders WHERE tenant_id=? AND id NOT IN "
                       "(SELECT id FROM tenant_demo_orders WHERE tenant_id=? ORDER BY id DESC LIMIT 500)",
                       (tenant["id"], tenant["id"]))
            db.commit()
            return {"demo_only": True, "id": created.lastrowid, "total_piasters": total,
                    "message": "طلب تجريبي فقط؛ لم يُرسل للمطعم."}
