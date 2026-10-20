"""Bokharest catalogue chat (optional Gemini trial) and demo reservations.

All data is DEMO ONLY; never confirms actual restaurant orders or bookings.
When a Gemini API key is configured, user message, previous turns, and menu
snippets are sent to Google; without a key no external AI is contacted.
"""
from __future__ import annotations

import os
import logging
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
from bokharest_free_ai import gemini_menu_reply
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



def _small_talk_reply(message: str) -> str | None:
    """Handle short, everyday customer exchanges before searching the catalogue.

    Only consume *standalone* social phrases. A greeting followed by a dish
    question must still reach the menu lookup, not be mistaken for small talk.
    """
    groups = (
        ("morning", ("صباح الخير", "صباح النور", "صباح الورد", "صباح الفل", "صباحو",
                     "يسعد صباحك", "good morning")),
        ("evening", ("مساء الخير", "مسا الخير", "مساء النور", "مسا النور",
                     "مساء الورد", "مسا الورد", "يسعد مساك", "good evening")),
        ("wellbeing", ("كيفك", "كيف الحال", "كيف حالك", "شو اخبارك", "شو اخباركم",
                       "عامل ايه", "عاملة ايه", "ازيك", "ازيكم", "اخبارك ايه",
                       "how are you")),
        ("hello", ("اهلا وسهلا", "أهلاً وسهلاً", "اهلا", "أهلاً", "مرحبا",
                   "السلام عليكم", "هلا والله", "هلا", "هاي", "hello", "hi", "bonjour")),
        ("thanks", ("شكراً", "شكرا", "ميرسي", "يسلمو", "تسلم", "thanks", "thank you")),
        ("bye", ("مع السلامة", "مع السلامه", "باي", "goodbye", "bye")),
        ("order", ("بدي اطلب", "عايز اطلب", "عايزة اطلب", "عاوز اطلب",
                   "حابب اطلب", "حابة اطلب", "شو اطلب", "بدي اكل")),
    )
    remaining = " ".join(re.findall(r"[\w\u0621-\u064a]+", normalize(message)))
    found: set[str] = set()
    for intent, phrases in groups:
        for phrase in sorted(phrases, key=len, reverse=True):
            normalized_phrase = normalize(phrase)
            pattern = r"(?<!\w)" + re.escape(normalized_phrase) + r"(?!\w)"
            if re.search(pattern, remaining):
                found.add(intent)
                remaining = re.sub(pattern, " ", remaining)
    # Polite fillers accompanying greetings shouldn't trigger a dish search.
    remaining = re.sub(r"\b(?:يا|بوخارست|بوخاريست|ياجماعه|ياجماعة)\b", " ", remaining)
    if not found or remaining.strip():
        return None
    if "morning" in found:
        return "صباح النور والورد! ☀️ أهلاً وسهلاً في بوخارست. تفضل، شو بتحب تطلب اليوم؟ فيني أساعدك تختار من المنيو."
    if "evening" in found:
        return "مساء النور والفل! 🌙 نورت بوخارست. تفضل، شو حابب تطلب؟ بتحب تشوف المنيو أو تسأل عن صنف؟"
    if "wellbeing" in found:
        return "الحمد لله، تمام! ❤️ إنت كيفك؟ أهلاً وسهلاً في بوخارست. شو بتحب تطلب؟"
    if "hello" in found:
        return "أهلين وسهلين! نورت بوخارست 🌷 تفضل، شو حابب تطلب؟ أو بتحب أساعدك تختار من المنيو؟"
    if "thanks" in found:
        return "العفو، على راسي! إذا بدك أي شي من منيو بوخارست، أنا هون أساعدك."
    if "bye" in found:
        return "مع السلامة! نورت بوخارست، ومنستناك ترجع بالسلامة."
    return "تفضل، شو بتحب تطلب من بوخارست؟ فيني أساعدك تشوف الأصناف والأسعار الموجودة في المنيو التجريبي."


def _menu_items_with_categories() -> list[dict]:
    """Use the live demo JSON, not hard-coded dish names or prices."""
    from bokharest_ordering import MENU_PATH
    import json
    sections = json.loads(MENU_PATH.read_text(encoding="utf-8"))["categories"]
    return [{**item, "_category_ar": section["name_ar"], "_category_en": section["name_en"]}
            for section in sections for item in section["items"]]


def _dish_reference(item: dict) -> dict:
    return {"id": item["id"], "name": item["name_ar"],
            "price_piasters": item["price_piasters"]}


def _price_text(item: dict) -> str:
    return f'{item["price_piasters"] / 100:.2f} جنيه'


def _query_mentions(text: str, phrases: tuple[str, ...]) -> bool:
    q = normalize(text)
    return any(normalize(phrase) in q for phrase in phrases)


def _chicken_question(text: str) -> bool:
    return _query_mentions(text, ("دجاج", "فراخ", "فرخة", "فراخ", "تشيكن", "chicken", "poulet"))


def _topic_matches(text: str, items: list[dict]) -> list[dict]:
    """Prefer the real category for broad questions; don't match unrelated filler."""
    q = normalize(text)
    if _chicken_question(text):
        # A customer asking for chicken mains expects the chicken section first.
        return [i for i in items if normalize(i["_category_ar"]) == normalize("دجاج")]
    topics = (
        (("ساندويتش", "ساندوتش", "سندوتش", "sandwich", "شاورما"), ("ساندويتشات",)),
        (("عصير", "عصائر", "juice"), ("عصائر طازجة",)),
        (("مشروبات", "مشروب", "drink"), ("مشروبات مميزة", "مشروبات ساخنة")),
        (("سلطة", "سلطات", "salad"), ("سلطات",)),
        (("سموذي", "smoothie"), ("سموذي",)),
    )
    for words, categories in topics:
        if _query_mentions(q, words):
            return [i for i in items if i["_category_ar"] in categories]
    return []


def _named_items(text: str, items: list[dict]) -> list[dict]:
    q = normalize(text)
    return [i for i in items if
            normalize(i["name_ar"]) in q or
            (len(i["name_en"]) >= 5 and normalize(i["name_en"]) in q)]


def _context_items(history: list[str], items: list[dict]) -> list[dict]:
    """Resolve 'which one?', 'price?' and 'on your taste' against recent turns.

    The browser sends the last six customer/assistant utterances, but legacy
    clients sending customer turns only are supported too.
    """
    for utterance in reversed(history[-6:]):
        named = _named_items(utterance, items)
        if named:
            return named[:4]
        topic = _topic_matches(utterance, items)
        if topic:
            return topic[:4]
    return []


def _choose_dish(candidates: list[dict], *, prefer_light: bool = False) -> dict:
    """Opinionated, explainable demo choice; never invent ratings or nutrition."""
    def preference(item: dict) -> tuple[int, int]:
        description = normalize(item.get("description_ar", "") + " " + item.get("description_en", ""))
        category = normalize(item.get("_category_ar", ""))
        grilled = "مشوي" in description or "grilled" in description
        salad = "سلطات" in category
        # Grilled dishes have an explainable cooking-method preference.
        return (int(grilled) * 5 + int(salad) * (4 if prefer_light else 1),
                -item["price_piasters"])
    return max(candidates, key=preference)


def menu_reply(message: str, history: list[str] | None = None) -> dict:
    """Conversational, menu-grounded demo; not a general-purpose generative AI."""
    history = (history or [])[-6:]
    q = normalize(message)
    _, catalog = _catalog()
    items = _menu_items_with_categories()

    # Food safety takes precedence over any recommendation or dialogue context.
    if _query_mentions(q, ("حساسي", "مكسرات", "جلوتين", "غلوتين", "لاكتوز",
                           "allerg", "peanut", "gluten", "سيلياك")):
        return {"text": "سلامتك أهم. ماقدرش أؤكد مكونات أو خلو أي طبق من الحساسية؛ لازم تسألي موظف المطعم قبل الطلب.",
                "items": [], "mode": "catalogue-demo"}
    if _query_mentions(q, ("احجز", "حجز", "ترابيز", "طاوله", "طاولة",
                           "table", "reserv", "booking")):
        return {"text": "أكيد! عندنا تجربة حجز ترابيزة بتختاري فيها اليوم والساعة وعدد الأشخاص والترابيزة نفسها. دي محاكاة للعرض، مش حجز مؤكد في المطعم. افتحي «احجزي ترابيزة تجريبيًا» من الصفحة.",
                "items": [], "link": "/bokharest/reserve", "mode": "catalogue-demo"}

    social = _small_talk_reply(message)
    if social is not None:
        return {"text": social, "items": [], "mode": "catalogue-demo"}

    explicit = _named_items(message, items)
    topical = _topic_matches(message, items)
    context = _context_items(history, items)
    scope = explicit or topical or context

    preference = _query_mentions(q, ("افضل", "احسن", "ارشح", "ترشح", "تنصح",
                                      "اختار", "اختاري", "على ذوقك", "علي ذوقك",
                                      "ع ذوقك", "على زوقك", "علي زوقك", "زوقك",
                                      "ذوقك", "recommend", "best", "suggest",
                                      "انسب", "الذ", "اطيب", "ايه رايك", "شو بتنصح"))
    healthier = _query_mentions(q, ("صحي", "اخف", "خفيف", "دايت", "مشوي", "healthy", "lighter", "light"))
    cheap = _query_mentions(q, ("ارخص", "اوفر", "اقتصادي", "cheapest", "budget"))
    compare = _query_mentions(q, ("الفرق", "قارن", "مقارنه", "compare", "الاختلاف"))
    price = _query_mentions(q, ("بكام", "السعر", "اسعار", "كام جنيه", "price", "cost", "ثمن"))
    # "احكيلي عنه أكتر" is a continuation of our own recommendation, not
    # a new food search. Cover Egyptian/Levantine colloquialisms and English.
    details = _query_mentions(q, (
        "مكونات", "مكوناته", "مكوناتها", "تفاصيل", "تفصيل",
        "فيه ايه", "جواه", "معاه", "احكي", "احكيلي", "احكيلنا",
        "قولي عنه", "قوليلي عنه", "قول لي عنه", "عرفني عنه",
        "عرفيني عنه", "اشرح", "اشرحلي", "شرح", "تكلم عنه", "اتكلم عنه",
        "عنه اكتر", "عنها اكتر", "عنهم اكتر", "عايز اعرف عنه",
        "عايزة اعرف عنه", "more about", "tell me more", "explain",
        "details", "ingredients",
    ))

    # Recommendations are subjective suggestions based on actual descriptions,
    # not claims about bestselling dishes, health outcomes or stock availability.
    if preference or healthier or cheap:
        options = scope or [i for i in items if normalize(i["_category_ar"]) == normalize("دجاج")]
        if not options:
            return {"text": "تحبي أرشّحلك دجاج، سلطة، ولا ساندويتش؟ قوليلّي بتحبي إيه وأنا أختار من المنيو.",
                    "items": [], "mode": "catalogue-demo"}
        chosen = min(options, key=lambda i: i["price_piasters"]) if cheap else _choose_dish(options, prefer_light=healthier)
        description = chosen.get("description_ar", "").strip()
        if cheap:
            reason = "ده الأقل سعرًا بين الاختيارات اللي بنتكلم عنها."
        elif healthier:
            reason = ("المنيو بيذكر إنه مشوي، وده ممكن يناسب اللي يفضّل المشوي."
                      if _query_mentions(description, ("مشوي",)) else
                      "ده اختياري حسب الوصف المتاح، مش تقييم صحي مؤكد.")
        else:
            reason = ("عجبني إنه مشوي وطريقة تقديمه واضحة في المنيو."
                      if _query_mentions(description, ("مشوي",)) else
                      "اختياري مبني على مكونات الطبق المكتوبة في المنيو.")
        caution = (" ما عندناش سعرات أو تفاصيل تغذية مؤكدة، فماقدرش أقول إنه صحي أكتر طبيًا."
                   if healthier else "")
        return {"text": f"لو على ذوقي، أرشّحلك {chosen['name_ar']} بسعر {_price_text(chosen)}. "
                        f"{reason} {description if description else ''}{caution} "
                        "تحبي أحكيلك عنه أكتر ولا نختار حاجة تانية؟",
                "items": [_dish_reference(chosen)], "mode": "catalogue-demo"}

    if compare and len(scope) >= 2:
        compared = scope[:3]
        descriptions = "، ".join(f"{i['name_ar']}: {i.get('description_ar') or 'الوصف غير متوفر'}، {_price_text(i)}"
                                 for i in compared)
        return {"text": f"خليني أقارنلك بين الاختيارات من المنيو: {descriptions}. "
                        "الاختيار بيرجع لذوقك، تحبي أختارلك واحد منهم؟",
                "items": [_dish_reference(i) for i in compared], "mode": "catalogue-demo"}

    # A vague follow-up should not be treated as a nonexistent menu product.
    if price and (explicit or context) and not topical:
        found = (explicit or context)[:4]
        summary = "، ".join(f"{i['name_ar']} {_price_text(i)}" for i in found)
        return {"text": f"أكيد، الأسعار المسجّلة هي: {summary}. دي أسعار المنيو التجريبي وبتحتاج تأكيد من المطعم. تحبي أساعدك تختاري؟",
                "items": [_dish_reference(i) for i in found], "mode": "catalogue-demo"}
    if details:
        found = explicit or context
        if not found:
            return {"text": "من عيوني! تحبي أحكيلك عن أنهي صنف؟ قوليلّي اسمه أو اسألي عن الدجاج مثلًا، وأنا أشرحلك من المنيو.",
                    "items": [], "mode": "catalogue-demo"}
        # A singular follow-up ("احكيلي عنه") after a named recommendation
        # focuses on that one dish; plural requests can show two.
        plural = _query_mentions(q, ("عنهم", "عليهم", "كلهم", "دول", "كل الاصناف", "both", "them"))
        chosen = found[:2] if plural else found[:1]
        parts = []
        for item in chosen:
            description = item.get("description_ar", "").strip()
            details_text = (f"حسب المنيو، {item['name_ar']} عبارة عن {description}."
                            if description else
                            f"حسب المنيو، اسم الصنف {item['name_ar']}، لكن وصفه التفصيلي مش مذكور.")
            parts.append(f"{details_text} سعره المعروض {_price_text(item)}.")
        return {"text": "أكيد! " + " ".join(parts) +
                        " ده وصف المنيو التجريبي، والمكونات الكاملة ومسببات الحساسية محتاجة تأكيد من المطعم. "
                        "تحبي ترشيح تاني أو مقارنة مع صنف مختلف؟",
                "items": [_dish_reference(i) for i in chosen], "mode": "catalogue-demo"}

    if _query_mentions(q, ("المنيو", "القائمه", "القائمة", "اقسام", "menu", "بتقدموا", "عندكم ايه", "عندكو ايه")) and not topical and not explicit:
        names = "، ".join(dict.fromkeys(i["_category_ar"] for i in items))
        return {"text": f"منورانا! منيو بوخاريست التجريبي فيه {len(catalog)} صنف موزعين على: {names}. "
                        "تحبي أقولك أصناف الدجاج مثلًا، ولا المشروبات، ولا حاجة حلوة؟ الأسعار الموجودة للعرض وتحتاج تأكيد المطعم.",
                "items": [], "mode": "catalogue-demo"}

    if explicit or topical:
        matches = (explicit or topical)[:4]
    else:
        terms = _tokens(message)
        filler = {normalize(x) for x in ("النهاردة", "النهارده", "عندكو", "عندكم", "عندك", "سؤال",
                                         "ممكن", "أفضلهم", "احسنهم", "ايه", "كده")}
        terms = [t for t in terms if t not in filler]
        def score(item: dict) -> int:
            searchable = normalize(" ".join(str(item.get(k, "")) for k in
                                    ("name_ar", "name_en", "description_ar", "description_en",
                                     "_category_ar", "_category_en")))
            return sum(3 for t in terms if t in searchable)
        matches = sorted([i for i in items if terms and score(i) > 0],
                         key=score, reverse=True)[:4]

    if matches:
        names = "، ".join(f'{i["name_ar"]} ({_price_text(i)})' for i in matches)
        topic = "الدجاج" if _chicken_question(message) else "طلبك"
        return {"text": f"أيوه! عندنا أصناف مرتبطة بـ{topic}: {names}. دي الأسعار المعروضة في النسخة التجريبية ومحتاجة تأكيد من المطعم. "
                        "تحبي أرشّحلك الأفضل على ذوقي ولا أشرح الفرق بينهم؟",
                "items": [_dish_reference(i) for i in matches], "mode": "catalogue-demo"}

    if context and _query_mentions(q, ("دول", "منهم", "انواعهم", "واحد", "تاني", "غيره", "other")):
        return {"text": "أكيد، نقدر نكمل على الاختيارات اللي قلتلك عليها. "
                        "تحبي ترشيح على ذوقي، مقارنة بينهم، ولا ندوّر على صنف مختلف؟",
                "items": [_dish_reference(i) for i in context[:4]], "mode": "catalogue-demo"}

    return {"text": "مش قادر أحدد تقصدي أي طبق بالضبط. تحبي أساعدك تختاري دجاج، "
                    "ساندويتش، سلطة أو مشروب؟ وأنا أرشّحلك حاجة من المنيو.",
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
    gemini_calls = deque()
    ai_logger = logging.getLogger(__name__)

    def gemini_trial_available() -> bool:
        return bool(os.environ.get("GEMINI_API_KEY", "").strip())

    def allow_demo_ai() -> bool:
        """Conservative best-effort cap; provider-side free tier governs usage."""
        now = monotonic()
        while gemini_calls and gemini_calls[0] < now - 3600:
            gemini_calls.popleft()
        if len(gemini_calls) >= 40:
            return False
        gemini_calls.append(now)
        return True

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

    @app.get("/api/bokharest/chat-config")
    def demo_chat_config():
        """Public status; never exposes provider credentials."""
        enabled = gemini_trial_available()
        return {"ai_enabled": enabled,
                "mode": "gemini-ai-demo" if enabled else "catalogue-demo",
                "provider": "gemini" if enabled else None,
                "voice_ai_enabled": False}

    @app.post("/api/bokharest/demo-chat")
    async def demo_chat(payload: ChatRequest, request: Request):
        throttle(request, 60)
        message = payload.message.strip()
        history = payload.history[-6:]
        # Food safety and reservation claims always use the local response.
        unsafe = _query_mentions(message, (
            "حساسي", "مكسرات", "جلوتين", "غلوتين", "لاكتوز",
            "حامل", "حمل", "سكري", "دايت علاجي", "مريض",
            "allerg", "gluten", "peanut", "celiac", "diabetic",
            "احجز", "حجز", "ترابيز", "طاوله", "طاولة", "booking", "reserv",
        ))
        if not unsafe and gemini_trial_available() and allow_demo_ai():
            try:
                return await gemini_menu_reply(
                    message, history, _menu_items_with_categories(),
                    api_key=os.environ["GEMINI_API_KEY"].strip(),
                    model=os.environ.get("BOKHAREST_GEMINI_MODEL", "gemini-2.5-flash"),
                )
            except Exception:
                ai_logger.warning("Bokharest free-tier AI call failed; using local menu fallback",
                                  exc_info=True)
        answer = menu_reply(message, history)
        if gemini_trial_available():
            answer["ai_fallback"] = True
        return answer

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
