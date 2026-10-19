"""DI Commerce Egypt — single-restaurant pilot, FastAPI + SQLite.

Run: python -m uvicorn app:app --reload
Not a payment processor, POS integration, or hosted AI model.
"""
from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import re
import secrets
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timezone
from collections import deque
from time import monotonic
import logging
import mimetypes
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.parse import urlsplit

import qrcode

from assistant_engine import ai_chat, guided_chat, has_allergy
from auth_security import AdminAuth, PREVIEW_SECRET, SESSION_SECONDS, hash_password, parse_password_hash
from voice_gateway import transcribe_audio, synthesize_speech
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from itsdangerous import BadData, URLSafeTimedSerializer
from pydantic import BaseModel, Field
from starlette.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

BASE_DIR = Path(__file__).resolve().parent
mimetypes.add_type("image/webp", ".webp")
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))
COOKIE_NAME = "ai_commerce_admin"
ORDER_STATES = ("new", "accepted", "preparing", "ready", "completed", "cancelled")
CATEGORIES = ("بيتزا", "برجر", "مقبلات", "مشروبات", "حلويات", "أخرى")


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def amount_to_piasters(raw: str) -> int:
    try:
        num = Decimal(str(raw).strip())
        if not num.is_finite() or num < 0 or num > 100_000 or num.as_tuple().exponent < -2:
            raise ValueError("Price must be between 0 and 100000 with at most 2 decimals")
        return int(num * 100)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("السعر غير صحيح. أدخلي قيمة مثل 175 أو 175.50") from exc


def money(piasters: int) -> str:
    return f"{piasters / 100:,.2f}"


def connect(db_path: Path):
    conn = sqlite3.connect(db_path, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


@contextmanager
def dbconn(db_path: Path):
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def bootstrap(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with dbconn(db_path) as db:
        db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY, value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS menu_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL,
            price_piasters INTEGER NOT NULL CHECK(price_piasters >= 0),
            available INTEGER NOT NULL DEFAULT 1 CHECK(available IN (0,1)),
            emoji TEXT NOT NULL DEFAULT '🍽️',
            tags TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS addons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price_piasters INTEGER NOT NULL CHECK(price_piasters >= 0),
            available INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS item_addons (
            item_id INTEGER NOT NULL REFERENCES menu_items(id) ON DELETE CASCADE,
            addon_id INTEGER NOT NULL REFERENCES addons(id),
            PRIMARY KEY (item_id, addon_id)
        );
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference TEXT UNIQUE NOT NULL,
            idempotency_key TEXT UNIQUE NOT NULL,
            tracking_token TEXT NOT NULL,
            table_no INTEGER NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            total_piasters INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'new',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL REFERENCES orders(id),
            menu_item_id INTEGER NOT NULL REFERENCES menu_items(id),
            name_snapshot TEXT NOT NULL,
            unit_price_piasters INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            addons_snapshot TEXT NOT NULL,
            line_total_piasters INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status, created_at);
        """)
        db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES ('restaurant_name','بيت المذاق')")
        db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES ('tagline','طعم يفرّحك في كل لقمة')")
        db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES ('table_count','20')")
        count = db.execute("SELECT COUNT(*) FROM menu_items").fetchone()[0]
        if not count:
            samples = [
                ("بيتزا مارغريتا", "موتزاريلا، صلصة طماطم وريحان", "بيتزا", 18500, "🍕", "vegetarian,popular"),
                ("بيتزا دجاج رانش", "دجاج مشوي وصوص رانش وجبنة", "بيتزا", 26000, "🍕", "popular"),
                ("برجر لحم كلاسيك", "لحم بقري، جبن شيدر وخس طازج", "برجر", 22000, "🍔", "popular"),
                ("برجر دجاج كرسبي", "دجاج مقرمش وصوص خاص", "برجر", 20500, "🍔", ""),
                ("بطاطس مقرمشة", "بطاطس ذهبية مع رشة بهارات", "مقبلات", 8500, "🍟", "vegetarian"),
                ("سلطة خضراء", "خضروات طازجة مع صوص منفصل", "مقبلات", 9000, "🥗", "vegetarian,light"),
                ("ليمون بالنعناع", "عصير ليمون طازج بالنعناع", "مشروبات", 7500, "🍋", "vegetarian"),
                ("كولا", "مشروب غازي بارد", "مشروبات", 4500, "🥤", "vegetarian"),
                ("براونيز شوكولاتة", "براونيز دافئة بالشوكولاتة", "حلويات", 11000, "🍫", "vegetarian"),
            ]
            db.executemany("INSERT INTO menu_items (name,description,category,price_piasters,emoji,tags,created_at) VALUES (?,?,?,?,?,?,?)", [(*s, now_utc()) for s in samples])
            db.executemany("INSERT INTO addons (name,price_piasters) VALUES (?,?)", [
                ("جبنة إضافية", 3500), ("صوص رانش", 2000), ("صوص حار", 1500), ("إضافة بطاطس", 5500),
            ])
            db.executemany("INSERT INTO item_addons (item_id,addon_id) VALUES (?,?)", [
                (1,1),(1,3),(2,1),(2,2),(2,3),(3,1),(3,3),(3,4),(4,1),(4,2),(4,4),(5,2),(5,3)
            ])


def settings_from(db: sqlite3.Connection) -> dict[str, str]:
    return {r["key"]: r["value"] for r in db.execute("SELECT key,value FROM settings")}


def menu_from(db: sqlite3.Connection, *, include_unavailable: bool = False) -> list[dict[str, Any]]:
    query = "SELECT * FROM menu_items" + ("" if include_unavailable else " WHERE available=1") + " ORDER BY id"
    addons = db.execute("""SELECT ia.item_id,a.* FROM item_addons ia
                       JOIN addons a ON ia.addon_id=a.id WHERE a.available=1 ORDER BY a.id""").fetchall()
    by_item: dict[int, list] = {}
    for a in addons:
        by_item.setdefault(a["item_id"], []).append({"id": a["id"], "name": a["name"], "price_piasters": a["price_piasters"]})
    return [dict(row) | {"addons": by_item.get(row["id"], []), "price": money(row["price_piasters"])} for row in db.execute(query)]


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text.translate(str.maketrans("أإآةىؤئ", "اااهيوي"))


class ChatTurn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=500)


class ChatRequest(BaseModel):
    messages: list[ChatTurn] = Field(min_length=1, max_length=20)
    language: str = Field(default="ar", pattern=r"^(ar|en|fr)$")
    dialect: str = Field(default="egyptian", pattern=r"^(egyptian|lebanese|standard)$")


class OrderLine(BaseModel):
    item_id: int = Field(gt=0)
    quantity: int = Field(ge=1, le=20)
    addon_ids: list[int] = Field(default_factory=list, max_length=10)


class OrderRequest(BaseModel):
    table_no: int = Field(ge=1, le=500)
    note: str = Field(default="", max_length=250)
    idempotency_key: str = Field(min_length=16, max_length=100)
    expected_total_piasters: int = Field(ge=0)
    items: list[OrderLine] = Field(min_length=1, max_length=40)


class SpeechPayload(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    language: str = Field(default="ar", pattern=r"^(ar|en|fr)$")
    dialect: str = Field(default="egyptian", pattern=r"^(egyptian|lebanese|standard)$")


def create_app(db_path: Path | None = None, *, admin_password: str | None = None, secret_key: str | None = None) -> FastAPI:
    db_path = Path(db_path) if db_path else Path(os.environ.get("DATABASE_PATH", str(BASE_DIR / "data" / "commerce.db")))
    password_hash = os.environ.get("ADMIN_PASSWORD_HASH", "") if admin_password is None else ""
    admin_password = admin_password if admin_password is not None else os.environ.get("ADMIN_PASSWORD", "demo12345")
    secret_key = secret_key if secret_key is not None else os.environ.get("SECRET_KEY", "")
    # Railway may supply a public domain automatically after generating an HTTPS address.
    # PUBLIC_BASE_URL is the explicit override used for table QR codes.
    railway_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip().removeprefix("https://").strip("/")
    public_base = (os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
                   or (f"https://{railway_domain}" if railway_domain else "http://127.0.0.1:8000"))
    environment = os.environ.get("APP_ENV", "development").lower()
    if environment not in ("development", "production"):
        raise RuntimeError("APP_ENV must be development or production")
    production = environment == "production"
    if production and (secret_key == PREVIEW_SECRET or len(secret_key) < 32):
        raise RuntimeError("Set a random SECRET_KEY of at least 32 characters before production deployment")
    if not password_hash and (not admin_password or len(admin_password.encode()) > 1024 or
                             (production and (admin_password == "demo12345" or len(admin_password.strip()) < 12))):
        raise RuntimeError("Set ADMIN_PASSWORD_HASH or an ADMIN_PASSWORD of at least 12 characters in production")
    if not secret_key or secret_key == PREVIEW_SECRET:
        secret_key = secrets.token_urlsafe(48)  # Local preview keys must never be public constants.
    credential_material = "hash:" + password_hash if password_hash else "password:" + admin_password
    credential_tag = hmac.new(secret_key.encode(), credential_material.encode(), hashlib.sha256).hexdigest()
    password_hash = password_hash or hash_password(admin_password)
    parse_password_hash(password_hash)
    del admin_password, credential_material
    bootstrap(db_path)
    app = FastAPI(title="DI Commerce Egypt – Restaurant Pilot", docs_url=None if production else "/api/docs")
    app.state.db_path = db_path
    auth = AdminAuth(db_path, password_hash, credential_tag)
    app.state.serializer = URLSafeTimedSerializer(secret_key, salt="ace-session-v1")
    app.state.secret_key = secret_key
    app.state.public_base = public_base
    app.state.production = production
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    @app.middleware("http")
    async def request_headers(req: Request, call_next):
        response = await call_next(req)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store" if req.url.path.startswith(("/api/orders", "/admin")) else "private, max-age=30"
        if production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    def is_admin(req: Request) -> bool:
        cookie = req.cookies.get(COOKIE_NAME, "")
        if not cookie:
            return False
        try:
            data = app.state.serializer.loads(cookie, max_age=SESSION_SECONDS)
            if isinstance(data, dict) and data.get("role") == "admin" and auth.session_valid(data.get("sid")):
                req.state.admin_session_id = data["sid"]
                return True
            return False
        except BadData:
            return False

    def login_required(req: Request):
        if not is_admin(req):
            raise HTTPException(status_code=401, detail="يجب تسجيل الدخول")

    def csrf_for(req: Request) -> str:
        cookie = req.cookies.get(COOKIE_NAME, "")
        return hmac.new(secret_key.encode(), ("csrf:" + cookie).encode(), hashlib.sha256).hexdigest()

    def verify_csrf(req: Request, token: str):
        login_required(req)
        if not hmac.compare_digest(csrf_for(req).encode(), token.encode()):
            raise HTTPException(status_code=403, detail="انتهت صلاحية الطلب. حدّثي الصفحة.")

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        with dbconn(db_path) as db:
            settings = settings_from(db)
        return TEMPLATES.TemplateResponse(request, "customer.html", {"settings": settings})

    @app.get("/api/menu")
    def api_menu():
        with dbconn(db_path) as db:
            return {"settings": settings_from(db), "items": menu_from(db), "categories": list(CATEGORIES)}

    # Best-effort in-memory throttle for the pilot; a public deployment requires
    # centralised limits, provider spend caps, HTTPS and production monitoring.
    chat_requests: dict[str, deque[float]] = {}
    voice_requests: dict[tuple[str, str], deque[float]] = {}

    def voice_key() -> str:
        if os.environ.get("VOICE_API_ENABLED", "1").lower() in ("0", "false", "no"):
            return ""
        return os.environ.get("OPENAI_API_KEY", "").strip()

    def voice_throttle(req: Request, kind: str):
        ip = req.client.host if req.client else "unknown"
        stamp = monotonic()
        bucket = voice_requests.setdefault((ip, kind), deque())
        while bucket and stamp - bucket[0] >= 60:
            bucket.popleft()
        if len(bucket) >= (8 if kind == "stt" else 12):
            raise HTTPException(status_code=429, detail="عدد محاولات الصوت كبير. استنى دقيقة وحاول تاني.")
        bucket.append(stamp)

    @app.get("/api/chat/config")
    def chat_config():
        configured = bool(voice_key())
        return {"ai_enabled": bool(os.environ.get("OPENAI_API_KEY", "").strip()),
                "voice": "server" if configured else "browser-fallback",
                "voice_stt_enabled": configured, "voice_tts_enabled": configured,
                "max_record_seconds": 12}

    @app.post("/api/voice/transcribe")
    async def voice_transcribe(request: Request, language: str = "ar"):
        if language not in ("ar", "en", "fr"):
            raise HTTPException(status_code=422, detail="Unsupported speech language")
        key = voice_key()
        if not key:
            raise HTTPException(status_code=503, detail="خدمة تحويل الصوت إلى نص لم تُفعَّل بعد.")
        mime = (request.headers.get("content-type") or "").split(";", 1)[0].lower()
        allowed_types = {"audio/webm", "audio/mp4", "audio/mpeg", "audio/mp3", "audio/wav",
                         "audio/x-wav", "audio/ogg", "audio/aac", "audio/x-m4a", "audio/m4a"}
        if mime not in allowed_types:
            raise HTTPException(status_code=415, detail="صيغة التسجيل غير مدعومة. استخدم الكتابة أو متصفحًا أحدث.")
        voice_throttle(request, "stt")
        # Stream raw audio bytes and cap memory. Avoid multipart file spooling to disk.
        maximum = 2_500_000
        try:
            declared_length = int(request.headers.get("content-length", "0") or "0")
        except ValueError:
            raise HTTPException(status_code=400, detail="بيانات التسجيل غير صحيحة.")
        if declared_length > maximum:
            raise HTTPException(status_code=413, detail="التسجيل طويل أو فارغ. جرّب تسجيلًا أقصر من 12 ثانية.")
        raw_buffer = bytearray()
        async for part in request.stream():
            raw_buffer.extend(part)
            if len(raw_buffer) > maximum:
                raise HTTPException(status_code=413, detail="التسجيل طويل أو فارغ. جرّب تسجيلًا أقصر من 12 ثانية.")
        if not raw_buffer:
            raise HTTPException(status_code=413, detail="التسجيل طويل أو فارغ. جرّب تسجيلًا أقصر من 12 ثانية.")
        raw = bytes(raw_buffer)
        # Ignore any client-supplied filename, even if it includes path separators.
        suffix = {"audio/mp4": ".mp4", "audio/ogg": ".ogg", "audio/wav": ".wav",
                  "audio/x-wav": ".wav", "audio/mpeg": ".mp3", "audio/mp3": ".mp3",
                  "audio/aac": ".aac", "audio/m4a": ".m4a", "audio/x-m4a": ".m4a"}.get(mime, ".webm")
        try:
            transcript = await transcribe_audio(raw, "customer-voice" + suffix, mime, api_key=key,
                                                model=os.environ.get("VOICE_STT_MODEL", "gpt-4o-mini-transcribe"), language=language)
        except Exception:
            logging.getLogger(__name__).warning("STT provider request failed", exc_info=True)
            raise HTTPException(status_code=503, detail="تعذّر فهم الصوت حاليًا. جرّب تاني أو اكتب طلبك.")
        if not transcript:
            raise HTTPException(status_code=422, detail="مش سامعين كلام واضح. حاول التسجيل مرة تانية.")
        return {"text": transcript[:300]}

    @app.post("/api/voice/speak")
    async def voice_speak(request: Request, payload: SpeechPayload):
        key = voice_key()
        if not key:
            raise HTTPException(status_code=503, detail="الصوت الخارجي لم يُفعَّل بعد.")
        voice_throttle(request, "tts")
        try:
            audio_bytes = await synthesize_speech(payload.text, api_key=key,
                           model=os.environ.get("VOICE_TTS_MODEL", "gpt-4o-mini-tts"),
                           voice=os.environ.get("VOICE_TTS_VOICE", "coral"),
                           language=payload.language, dialect=payload.dialect)
        except Exception:
            logging.getLogger(__name__).warning("TTS provider request failed", exc_info=True)
            raise HTTPException(status_code=503, detail="الصوت غير متاح حاليًا. اقرأ الرد على الشاشة.")
        if not audio_bytes:
            raise HTTPException(status_code=503, detail="تعذر تشغيل الرد الصوتي.")
        return Response(content=audio_bytes, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})

    @app.post("/api/chat")
    async def chat(payload: ChatRequest, request: Request):
        messages = [m.model_dump() for m in payload.messages]
        if messages[-1]["role"] != "user":
            raise HTTPException(status_code=422, detail="لازم آخر رسالة تكون من الزبون")
        with dbconn(db_path) as db:
            items = menu_from(db)
        # Local food-safety redirection comes before any external provider call.
        if has_allergy(messages):
            return guided_chat(messages, items, language=payload.language, dialect=payload.dialect)
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        if key:
            ip = request.client.host if request.client else "unknown"
            stamp = monotonic()
            bucket = chat_requests.setdefault(ip, deque())
            while bucket and stamp - bucket[0] > 60:
                bucket.popleft()
            if len(bucket) >= 12:
                raise HTTPException(status_code=429, detail="طلبت كتير خلال دقيقة. استنى شوية وجرّب تاني.")
            bucket.append(stamp)
            try:
                return await ai_chat(messages, items, key=key, model=os.environ.get("AI_MODEL", "gpt-4.1-mini"),
                                     language=payload.language, dialect=payload.dialect)
            except Exception:
                logging.getLogger(__name__).warning("AI provider unavailable; using guided dialogue", exc_info=True)
        return guided_chat(messages, items, language=payload.language, dialect=payload.dialect)

    @app.get("/api/suggest")
    def suggest(q: str = ""):
        q = q[:300].strip()
        with dbconn(db_path) as db:
            items = menu_from(db)
        norm = normalize(q)
        if any(t in norm for t in ("حساسي", "مكسرات", "جلوتين", "لاكتوز", "allerg", "peanut")):
            return {"text": "للسلامة الغذائية، اسألي أحد موظفي المطعم عن المكونات والحساسية قبل الطلب. لا أستطيع تأكيد خلو أي صنف من مسببات الحساسية.", "item_ids": [], "needs_staff": True}
        filtered = items
        terms = [("بيتزا", ("بيتزا", "pizza")), ("برجر", ("برجر", "برغر", "burger")), ("مشروبات", ("مشروب", "عصير", "اشرب", "juice", "drink")), ("مقبلات", ("بطاطس", "سلطه", "خفيف", "side")), ("حلويات", ("حلو", "ديسرت", "dessert"))]
        for category, words in terms:
            if any(word in norm for word in words):
                filtered = [p for p in filtered if p["category"] == category]
                break
        if any(w in norm for w in ("نباتي", "vegetarian", "بدون لحم")):
            filtered = [p for p in filtered if "vegetarian" in p["tags"]]
        budget_match = re.search(r"(?:اقل من|تحت|بحدود|ب)\s*(\d{2,5})\s*(?:جنيه|ج)?", norm)
        if budget_match:
            budget = int(budget_match.group(1)) * 100
            filtered = [p for p in filtered if p["price_piasters"] <= budget]
        if not filtered:
            return {"text": "ما لقيتش صنف مطابق حاليًا. ممكن تختاري من المنيو أو تطلبي مساعدة الموظف.", "item_ids": [], "needs_staff": False}
        featured = sorted(filtered, key=lambda x: ("popular" not in x["tags"], x["price_piasters"]))[:3]
        return {"text": "أرشّح لك الاختيارات المتاحة دي من منيو المطعم. الأسعار النهائية تُحسب وقت تأكيد الطلب.", "item_ids": [p["id"] for p in featured], "needs_staff": False}

    def order_response(order: sqlite3.Row) -> dict[str, Any]:
        return {"id": order["id"], "reference": order["reference"], "tracking_token": order["tracking_token"], "table_no": order["table_no"], "total_piasters": order["total_piasters"], "status": order["status"], "created_at": order["created_at"]}

    @app.post("/api/orders", status_code=201)
    def create_order(payload: OrderRequest):
        with dbconn(db_path) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                config = settings_from(db)
                if payload.table_no > int(config.get("table_count", 20)):
                    raise HTTPException(status_code=422, detail="رقم الطاولة غير موجود")
                existing = db.execute("SELECT * FROM orders WHERE idempotency_key=?", (payload.idempotency_key,)).fetchone()
                if existing:
                    db.execute("COMMIT")
                    return order_response(existing)
                snapshots = []
                total = 0
                for line in payload.items:
                    item = db.execute("SELECT * FROM menu_items WHERE id=? AND available=1", (line.item_id,)).fetchone()
                    if not item:
                        raise HTTPException(status_code=409, detail="صنف غير متاح حاليًا. حدّثي المنيو وحاولي مجددًا.")
                    if len(set(line.addon_ids)) != len(line.addon_ids):
                        raise HTTPException(status_code=422, detail="إضافة مكررة")
                    available_addons = {a["id"]: a for a in db.execute("""SELECT a.* FROM item_addons ia JOIN addons a ON ia.addon_id=a.id
                           WHERE ia.item_id=? AND a.available=1""", (line.item_id,))}
                    if not set(line.addon_ids).issubset(available_addons):
                        raise HTTPException(status_code=409, detail="إضافة غير متاحة لهذا الصنف")
                    addons_snapshot = [{"name": available_addons[aid]["name"], "price_piasters": available_addons[aid]["price_piasters"]} for aid in line.addon_ids]
                    unit = item["price_piasters"] + sum(a["price_piasters"] for a in addons_snapshot)
                    line_total = unit * line.quantity
                    total += line_total
                    snapshots.append((item["id"], item["name"], item["price_piasters"], line.quantity, json.dumps(addons_snapshot, ensure_ascii=False), line_total))
                if total != payload.expected_total_piasters:
                    raise HTTPException(status_code=409, detail="السعر أو التوافر تغيّر. حدّثي المنيو وراجعي الإجمالي قبل تأكيد الطلب.")
                if total > 10_000_000_00:
                    raise HTTPException(status_code=422, detail="قيمة الطلب كبيرة جدًا")
                token = secrets.token_urlsafe(24)
                stamp = now_utc()
                reference = "ACE-" + secrets.token_hex(4).upper()
                row = db.execute("""INSERT INTO orders (reference,idempotency_key,tracking_token,table_no,note,total_piasters,status,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?)""", (reference, payload.idempotency_key, token, payload.table_no, payload.note.strip(), total, "new", stamp, stamp))
                order_id = row.lastrowid
                db.executemany("""INSERT INTO order_items (order_id,menu_item_id,name_snapshot,unit_price_piasters,quantity,addons_snapshot,line_total_piasters)
                    VALUES (?,?,?,?,?,?,?)""", [(order_id, *s) for s in snapshots])
                order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
                db.execute("COMMIT")
                return order_response(order)
            except Exception:
                db.execute("ROLLBACK")
                raise

    @app.get("/api/orders/{reference}")
    def track_order(reference: str, token: str = ""):
        with dbconn(db_path) as db:
            order = db.execute("SELECT * FROM orders WHERE reference=?", (reference,)).fetchone()
        if not order or not token or not hmac.compare_digest(order["tracking_token"].encode(), token.encode()):
            raise HTTPException(status_code=404, detail="لم يتم العثور على الطلب")
        return {k: v for k, v in order_response(order).items() if k != "tracking_token"}

    @app.get("/admin/login", response_class=HTMLResponse)
    def admin_login(request: Request):
        if is_admin(request):
            return RedirectResponse("/admin", status_code=303)
        return TEMPLATES.TemplateResponse(request, "login.html", {"error": False})

    @app.post("/admin/login")
    async def admin_login_post(request: Request):
        # Browsers include Origin on form POSTs; reject cross-origin login and opaque origins.
        origin = request.headers.get("origin")
        allowed_origins = {str(request.base_url).rstrip("/")}
        configured_url = urlsplit(public_base)
        if production and configured_url.scheme == "https" and configured_url.netloc:
            allowed_origins.add(f"https://{configured_url.netloc}")
        if request.headers.get("sec-fetch-site") == "cross-site" or (origin and origin not in allowed_origins):
            raise HTTPException(status_code=403, detail="طلب تسجيل الدخول من مصدر غير مسموح")
        retry = await run_in_threadpool(auth.reserve_login_attempt, request.client.host if request.client else "unknown")
        if retry:
            raise HTTPException(status_code=429, detail="محاولات كثيرة. انتظري خمس دقائق وحاولي مجددًا.", headers={"Retry-After": str(retry)})
        form = await request.form()
        supplied = str(form.get("password", ""))
        if not await run_in_threadpool(auth.password_matches, supplied):
            return TEMPLATES.TemplateResponse(request, "login.html", {"error": True}, status_code=401)
        sid = await run_in_threadpool(auth.create_session)
        if sid is None:
            raise HTTPException(status_code=401, detail="تم تغيير بيانات الدخول. حاولي مجددًا.")
        token = app.state.serializer.dumps({"role": "admin", "sid": sid})
        response = RedirectResponse("/admin", status_code=303)
        response.set_cookie(COOKIE_NAME, token, httponly=True, secure=production, samesite="lax", max_age=SESSION_SECONDS, path="/")
        return response

    @app.post("/admin/logout")
    async def logout(request: Request):
        form = await request.form()
        verify_csrf(request, str(form.get("csrf", "")))
        await run_in_threadpool(auth.revoke_session, request.state.admin_session_id)
        response = RedirectResponse("/admin/login", status_code=303)
        response.delete_cookie(COOKIE_NAME, path="/")
        return response

    @app.get("/admin", response_class=HTMLResponse)
    def admin(request: Request):
        if not is_admin(request):
            return RedirectResponse("/admin/login", status_code=303)
        with dbconn(db_path) as db:
            items = menu_from(db, include_unavailable=True)
            all_addons = [dict(a) for a in db.execute("SELECT * FROM addons ORDER BY id")]
            order_rows = db.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 50").fetchall()
            orders = []
            for row in order_rows:
                order = dict(row)
                order["lines"] = [dict(li) | {"addons": json.loads(li["addons_snapshot"])} for li in db.execute("SELECT * FROM order_items WHERE order_id=?", (row["id"],))]
                orders.append(order)
            settings = settings_from(db)
            stats = {"orders_today": db.execute("SELECT COUNT(*) FROM orders WHERE substr(created_at,1,10)=?", (now_utc()[:10],)).fetchone()[0],
                     "new_orders": db.execute("SELECT COUNT(*) FROM orders WHERE status='new'").fetchone()[0],
                     "total_piasters": db.execute("SELECT COALESCE(SUM(total_piasters),0) FROM orders WHERE status NOT IN ('cancelled')").fetchone()[0]}
        return TEMPLATES.TemplateResponse(request, "admin.html", {"items": items, "all_addons": all_addons,
            "orders": orders, "settings": settings, "stats": stats, "csrf": csrf_for(request),
            "categories": CATEGORIES, "statuses": ORDER_STATES, "money": money, "base_url": public_base})

    @app.get("/admin/pulse")
    def admin_pulse(request: Request):
        login_required(request)
        with dbconn(db_path) as db:
            last = db.execute("SELECT COALESCE(MAX(id),0) FROM orders").fetchone()[0]
            news = db.execute("SELECT COUNT(*) FROM orders WHERE status='new'").fetchone()[0]
        return {"last_order_id": last, "new_orders": news}

    @app.post("/admin/orders/{order_id}/status")
    async def change_status(order_id: int, request: Request):
        form = await request.form()
        verify_csrf(request, str(form.get("csrf", "")))
        status = str(form.get("status", ""))
        if status not in ORDER_STATES:
            raise HTTPException(status_code=422, detail="حالة غير مدعومة")
        with dbconn(db_path) as db:
            row = db.execute("UPDATE orders SET status=?,updated_at=? WHERE id=?", (status, now_utc(), order_id))
            if not row.rowcount:
                raise HTTPException(status_code=404, detail="طلب غير موجود")
        return RedirectResponse("/admin#orders", status_code=303)

    @app.post("/admin/menu")
    async def add_item(request: Request):
        form = await request.form()
        verify_csrf(request, str(form.get("csrf", "")))
        name = str(form.get("name", "")).strip()[:90]
        desc = str(form.get("description", "")).strip()[:250]
        category = str(form.get("category", ""))
        if not name or category not in CATEGORIES:
            raise HTTPException(status_code=422, detail="اسم الصنف أو القسم غير صحيح")
        try:
            price = amount_to_piasters(str(form.get("price", "")))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        addon_ids = [int(v) for v in form.getlist("addon_ids") if str(v).isdigit()]
        emoji = str(form.get("emoji", "🍽️"))[:8]
        with dbconn(db_path) as db:
            row = db.execute("INSERT INTO menu_items (name,description,category,price_piasters,available,emoji,tags,created_at) VALUES (?,?,?,?,?,?,?,?)", (name, desc, category, price, 1, emoji, "", now_utc()))
            for addon_id in set(addon_ids):
                db.execute("INSERT OR IGNORE INTO item_addons (item_id,addon_id) SELECT ?,id FROM addons WHERE id=?", (row.lastrowid, addon_id))
        return RedirectResponse("/admin#menu", status_code=303)

    @app.post("/admin/menu/{item_id}")
    async def edit_item(item_id: int, request: Request):
        form = await request.form()
        verify_csrf(request, str(form.get("csrf", "")))
        name = str(form.get("name", "")).strip()[:90]
        category = str(form.get("category", ""))
        desc = str(form.get("description", "")).strip()[:250]
        if not name or category not in CATEGORIES:
            raise HTTPException(status_code=422, detail="بيانات الصنف غير صحيحة")
        try:
            price = amount_to_piasters(str(form.get("price", "")))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        available = 1 if form.get("available") == "on" else 0
        emoji = str(form.get("emoji", "🍽️"))[:8]
        addon_ids = [int(v) for v in form.getlist("addon_ids") if str(v).isdigit()]
        with dbconn(db_path) as db:
            row = db.execute("UPDATE menu_items SET name=?, description=?,category=?,price_piasters=?, available=?,emoji=? WHERE id=?", (name,desc,category,price,available,emoji,item_id))
            if not row.rowcount:
                raise HTTPException(status_code=404, detail="صنف غير موجود")
            db.execute("DELETE FROM item_addons WHERE item_id=?", (item_id,))
            for addon_id in set(addon_ids):
                db.execute("INSERT OR IGNORE INTO item_addons (item_id,addon_id) SELECT ?,id FROM addons WHERE id=?", (item_id, addon_id))
        return RedirectResponse("/admin#menu", status_code=303)

    @app.post("/admin/settings")
    async def edit_settings(request: Request):
        form = await request.form()
        verify_csrf(request, str(form.get("csrf", "")))
        name = str(form.get("restaurant_name", "")).strip()[:100]
        tagline = str(form.get("tagline", "")).strip()[:180]
        try:
            table_count = int(form.get("table_count", ""))
        except (ValueError, TypeError):
            raise HTTPException(status_code=422, detail="عدد الطاولات غير صحيح")
        if not name or not (1 <= table_count <= 500):
            raise HTTPException(status_code=422, detail="الاسم أو عدد الطاولات غير صحيح")
        with dbconn(db_path) as db:
            for key, val in [("restaurant_name", name),("tagline", tagline),("table_count", str(table_count))]:
                db.execute("INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key,val))
        return RedirectResponse("/admin#settings", status_code=303)

    @app.get("/qr/{table_no}.png")
    def table_qr(table_no: int):
        with dbconn(db_path) as db:
            count = int(settings_from(db).get("table_count", 20))
        if not (1 <= table_no <= count):
            raise HTTPException(status_code=404, detail="رقم طاولة غير موجود")
        url = f"{public_base}/?table={table_no}"
        qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=3)
        qr.add_data(url)
        qr.make(fit=True)
        image = qr.make_image(fill_color="#112d3d", back_color="white")
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return Response(buf.getvalue(), media_type="image/png", headers={"Content-Disposition": f"inline; filename=table-{table_no}.png"})

    @app.get("/health")
    def health():
        return {"ok": True, "version": "1.0.0-restaurant-edition"}

    return app


app = create_app()
