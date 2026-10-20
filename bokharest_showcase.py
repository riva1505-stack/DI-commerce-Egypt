"""Independent, no-fee Bokharest sales showcase: grounded menu chat and table reservations.

All data is DEMO ONLY. Never contacts the restaurant, AI vendors, or WhatsApp.
No actual table inventory is claimed or displayed.
"""
from __future__ import annotations

import re
import secrets
import sqlite3
from collections import defaultdict, deque
from datetime import datetime, timedelta
from time import monotonic
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from assistant_engine import normalize
from bokharest_ordering import _catalog, _connect

CAIRO = ZoneInfo("Africa/Cairo")
SLOTS = [f"{h:02d}:{m:02d}" for h in range(12, 23) for m in (0, 30)]
CAPACITIES = {**{t: 2 for t in range(1, 5)},
              **{t: 4 for t in range(5, 9)},
              **{t: 6 for t in range(9, 13)}}


class BookingRequest(BaseModel):
    date: str = Field(min_length=10, max_length=10)
    time: str = Field(min_length=5, max_length=5)
    guests: int = Field(ge=1, le=6)
    table_no: int = Field(ge=1, le=12)
    guest_name: str = Field(default="ضيف تجريبي", max_length=70)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=300)
    history: list[str] = Field(default_factory=list, max_length=6)


def _date_slot(day: str, slot: str):
    try:
        parsed = datetime.strptime(day, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(422, "اختاري تاريخ صحيح.")
    today = datetime.now(CAIRO).date()
    if parsed < today or parsed > today + timedelta(days=60):
        raise HTTPException(422, "الحجز التجريبي متاح لحد 60 يوم من النهارده.")
    if slot not in SLOTS:
        raise HTTPException(422, "اختاري ميعاد من المواعيد الموجودة.")
    return parsed


def _seeded_demo_occupancy(day: str, slot: str) -> set[int]:
    """Clearly fictional example occupancy to make a realistic sales walkthrough."""
    if slot == "19:00":
        return {2, 6}
    if slot == "20:00":
        return {3, 7}
    return set()


def _availability(db_path, day: str, slot: str, guests: int) -> list[dict]:
    _date_slot(day, slot)
    if not 1 <= guests <= 6:
        raise HTTPException(422, "عدد الأشخاص لازم يكون من 1 إلى 6.")
    with _connect(db_path) as db:
        rows = db.execute(
            "SELECT table_no FROM bokharest_demo_reservations "
            "WHERE reservation_date=? AND reservation_time=? AND status='demo'",
            (day, slot),
        ).fetchall()
    occupied = {r["table_no"] for r in rows} | _seeded_demo_occupancy(day, slot)
    return [{"table_no": table, "capacity": capacity,
             "available": table not in occupied and capacity >= guests,
             "demo_occupied": table in occupied}
            for table, capacity in CAPACITIES.items()]


def _tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"[\w\u0621-\u064a]+", normalize(text))
            if len(w) >= 3 and w not in {"عندك", "عندكم", "عايز", "عايزة", "فيه", "في", "ممكن",
                                        "موجود", "موجودة", "إيه", "ايه", "اللي", "the", "and", "have"}]


def menu_reply(message: str, history: list[str] | None = None) -> dict:
    """Data-backed deterministic demo; deliberately does not claim to be a generative LLM."""
    restaurant, catalog = _catalog()
    items = list(catalog.values())
    q = normalize(message)
    if any(w in q for w in ("حساسي", "مكسرات", "جلوتين", "لاكتوز", "allerg", "peanut", "gluten")):
        return {"text": "سلامتك أهم. ماقدرش أؤكد مكونات أو خلو أي طبق من الحساسية؛ لازم تسألي موظف المطعم قبل الطلب.",
                "items": [], "mode": "catalogue-demo"}
    if any(w in q for w in ("احجز", "حجز", "ترابيز", "طاوله", "طاولة", "table", "reserv", "booking")):
        return {"text": "أكيد! عندنا تجربة حجز ترابيزة بتختاري فيها اليوم والساعة وعدد الأشخاص والترابيزة نفسها. دي محاكاة للعرض، مش حجز مؤكد في المطعم. افتحي «احجزي ترابيزة تجريبيًا» من الصفحة.",
                "items": [], "link": "/bokharest/reserve", "mode": "catalogue-demo"}
    if any(w in q for w in ("المنيو", "القائمه", "القائمة", "اقسام", "menu", "بتقدموا", "عندكم ايه", "عندكو ايه")):
        groups = {}
        for item in items:
            key = normalize(item.get("name_ar", ""))
        # Catalog groups are sourced from the same menu JSON as checkout.
        from bokharest_ordering import MENU_PATH
        import json
        sections = json.loads(MENU_PATH.read_text(encoding="utf-8"))["categories"]
        names = "، ".join(c["name_ar"] for c in sections)
        return {"text": f"منورانا! منيو بوخاريست التجريبي فيه {len(items)} صنف موزعين على: {names}. تحبي أقولك أصناف الدجاج مثلًا، ولا المشروبات، ولا حاجة حلوة؟ الأسعار الموجودة للعرض وتحتاج تأكيد المطعم.",
                "items": [], "mode": "catalogue-demo"}
    terms = _tokens(message)
    # A short follow-up such as "بكام؟" may refer to the preceding question.
    if (not terms or all(t in ("بكام", "السعر", "كام", "price") for t in terms)) and history:
        terms = _tokens(history[-1])
    synonyms = {
        "دجاج": ("دجاج", "فراخ", "فراخ", "تشيكن", "chicken", "poulet"),
        "ساندويتشات": ("ساندويتش", "ساندوتش", "سندوتش", "sandwich", "شاورما"),
        "مشروبات": ("عصير", "عصائر", "drink", "juice", "smoothie", "سموذي", "كوكتيل", "مشروب"),
        "برجر": ("برجر", "برغر", "burger"),
    }
    expanded = set(terms)
    for canonical, values in synonyms.items():
        if any(v in q for v in values):
            expanded.add(canonical)
    if any(w in q for w in ("بكام", "السعر", "كام", "price")) and not expanded and history:
        expanded.update(_tokens(history[-1]))
    def score(item):
        searchable = normalize(" ".join(str(item.get(k, "")) for k in
                 ("name_ar", "name_en", "description_ar", "description_en")))
        # Category labels are important for broad questions about chicken.
        category = normalize(item.get("_category", ""))
        return sum(4 for w in expanded if w in searchable) + sum(3 for w in expanded if w in category)
    if expanded:
        # Add actual category names, without hardcoding items or prices.
        from bokharest_ordering import MENU_PATH
        import json
        sections = json.loads(MENU_PATH.read_text(encoding="utf-8"))["categories"]
        enriched = [{**item, "_category": section["name_ar"] + " " + section["name_en"]}
                    for section in sections for item in section["items"]]
        ranked = sorted(enriched, key=score, reverse=True)
        hits = [x for x in ranked if score(x) > 0][:4]
    else:
        hits = []
    if hits:
        names = "، ".join(f'{x["name_ar"]} ({x["price_piasters"] / 100:.2f} ج.م)' for x in hits)
        topic = "الدجاج" if any(w in q for w in ("دجاج", "فراخ", "تشيكن", "chicken")) else "سؤالك"
        return {"text": f"أيوه، لقيت أصناف مرتبطة بـ{topic} في المنيو: {names}. دي الأسعار المعروضة في النسخة التجريبية ومحتاجة تأكيد من المطعم. تحبي تفاصيل صنف معين؟",
                "items": [{"id": x["id"], "name": x["name_ar"], "price_piasters": x["price_piasters"]} for x in hits],
                "mode": "catalogue-demo"}
    return {"text": "مش لاقي صنف مطابق لسؤالك في المنيو المسجل، ومش هخترع حاجة مش موجودة. ممكن تسأليني عن الدجاج، الساندويتشات، العصائر، أو تقولي «إيه المنيو؟».",
            "items": [], "mode": "catalogue-demo"}


def install_bokharest_showcase(app, db_path, is_admin, verify_csrf, csrf_for, templates):
    with _connect(db_path) as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS bokharest_demo_reservations(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference TEXT NOT NULL UNIQUE,
            reservation_date TEXT NOT NULL,
            reservation_time TEXT NOT NULL,
            table_no INTEGER NOT NULL CHECK(table_no BETWEEN 1 AND 12),
            guests INTEGER NOT NULL CHECK(guests BETWEEN 1 AND 6),
            guest_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'demo',
            created_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS bokharest_demo_active_booking
          ON bokharest_demo_reservations(reservation_date, reservation_time, table_no)
          WHERE status='demo';
        """)
    attempts = defaultdict(deque)

    def throttle(req: Request, limit: int):
        ip = req.client.host if req.client else "unknown"
        stamp = monotonic()
        bucket = attempts[ip]
        while bucket and bucket[0] < stamp - 3600:
            bucket.popleft()
        if len(bucket) >= limit:
            raise HTTPException(429, "محاولات كتير في وقت قصير، جربي بعد شوية.")
        bucket.append(stamp)

    @app.get("/bokharest/reserve", response_class=HTMLResponse)
    def showcase_page(request: Request):
        return templates.TemplateResponse(request, "bokharest_reservations.html", {})

    @app.get("/api/bokharest/demo-tables")
    def demo_tables(date: str, time: str, guests: int = 2):
        return {"demo_only": True, "tables": _availability(db_path, date, time, guests),
                "date": date, "time": time, "guests": guests}

    @app.post("/api/bokharest/demo-reservations", status_code=201)
    def create_booking(payload: BookingRequest, request: Request):
        throttle(request, 10)
        day = payload.date
        slot = payload.time
        _date_slot(day, slot)
        if CAPACITIES[payload.table_no] < payload.guests:
            raise HTTPException(422, "الترابيزة دي أصغر من عدد الأشخاص.")
        if payload.table_no in _seeded_demo_occupancy(day, slot):
            raise HTTPException(409, "الترابيزة دي محجوزة في المحاكاة، اختاري غيرها.")
        name = payload.guest_name.strip() or "ضيف تجريبي"
        with _connect(db_path) as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                result = db.execute(
                    "SELECT 1 FROM bokharest_demo_reservations "
                    "WHERE reservation_date=? AND reservation_time=? AND table_no=? AND status='demo'",
                    (day, slot, payload.table_no),
                ).fetchone()
                if result:
                    raise HTTPException(409, "حد سبقك في حجز الترابيزة التجريبية دي.")
                reference = "BKH-RES-DEMO-" + secrets.token_hex(4).upper()
                db.execute(
                    "INSERT INTO bokharest_demo_reservations "
                    "(reference,reservation_date,reservation_time,table_no,guests,guest_name,status,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (reference, day, slot, payload.table_no, payload.guests, name, "demo",
                     datetime.now(CAIRO).isoformat(timespec="seconds")),
                )
                db.commit()
            except Exception:
                db.rollback()
                raise
        return {"demo_only": True, "reference": reference, "table_no": payload.table_no,
                "date": day, "time": slot, "guests": payload.guests,
                "message": "اتسجل حجز تجريبي للعرض فقط، مش حجز حقيقي في المطعم."}

    @app.post("/api/bokharest/demo-chat")
    def demo_chat(payload: ChatRequest, request: Request):
        throttle(request, 60)
        return menu_reply(payload.message.strip(), payload.history[-6:])

    @app.get("/admin/bokharest-reservations", response_class=HTMLResponse)
    def reservation_admin(request: Request):
        if not is_admin(request):
            return RedirectResponse("/admin/login", status_code=303)
        with _connect(db_path) as db:
            bookings = [dict(r) for r in db.execute(
                "SELECT * FROM bokharest_demo_reservations ORDER BY id DESC LIMIT 100")]
        return templates.TemplateResponse(request, "bokharest_reservations_admin.html",
                                          {"bookings": bookings, "csrf": csrf_for(request)})

    @app.post("/admin/bokharest-reservations/{booking_id}/cancel")
    async def cancel_booking(booking_id: int, request: Request):
        form = await request.form()
        verify_csrf(request, str(form.get("csrf", "")))
        with _connect(db_path) as db:
            updated = db.execute("UPDATE bokharest_demo_reservations SET status='cancelled' WHERE id=?",
                                 (booking_id,))
            if updated.rowcount == 0:
                raise HTTPException(404, "الحجز التجريبي غير موجود")
        return RedirectResponse("/admin/bokharest-reservations", status_code=303)
