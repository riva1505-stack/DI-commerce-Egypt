"""Free catalogue-backed conversation and fake-table reservations must stay isolated."""
from datetime import datetime, timedelta
from pathlib import Path
import re
import sqlite3
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from app import create_app


def tomorrow():
    return (datetime.now(ZoneInfo("Africa/Cairo")).date()
            + timedelta(days=1)).isoformat()


def new_client(tmp_path: Path):
    app = create_app(tmp_path / "showcase.sqlite",
                     admin_password="test-showcase-password",
                     secret_key="z" * 52)
    return TestClient(app)


def test_free_chat_grounded_in_bokharest_catalogue(tmp_path):
    with new_client(tmp_path) as client:
        r = client.post("/api/bokharest/demo-chat",
                        json={"message": "عندكم دجاج؟", "history": []})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["mode"] == "catalogue-demo"
        assert data["items"], data
        assert "دجاج" in data["text"]
        assert "براونيز" not in data["text"]

        menu = client.post("/api/bokharest/demo-chat",
                           json={"message": "إيه المنيو النهاردة؟"}).json()
        assert "منيو" in menu["text"]
        assert "دجاج" in menu["text"]
        assert menu["mode"] == "catalogue-demo"

        booking = client.post("/api/bokharest/demo-chat",
                              json={"message": "عايز أحجز ترابيزة"}).json()
        assert booking["link"] == "/bokharest/reserve"
        assert "مش حجز مؤكد" in booking["text"]

        allergy = client.post("/api/bokharest/demo-chat",
                              json={"message": "عندي حساسية مكسرات"}).json()
        assert not allergy["items"]

        assert client.get("/bokharest/reserve").status_code == 200
        page = client.get("/bokharest").text
        assert 'href="/bokharest/reserve"' in page


def test_bookings_are_demo_only_and_do_not_reach_real_orders(tmp_path):
    with new_client(tmp_path) as client:
        date = tomorrow()
        params = {"date": date, "time": "19:00", "guests": 2}
        available = client.get("/api/bokharest/demo-tables", params=params)
        assert available.status_code == 200, available.text
        tables = available.json()["tables"]
        assert available.json()["demo_only"] is True
        assert len(tables) == 12
        assert next(t for t in tables if t["table_no"] == 2)["demo_occupied"]
        assert next(t for t in tables if t["table_no"] == 1)["available"]

        payload = {"date": date, "time": "19:00", "guests": 2,
                   "table_no": 1, "guest_name": "Test Guest"}
        created = client.post("/api/bokharest/demo-reservations", json=payload)
        assert created.status_code == 201, created.text
        reference = created.json()["reference"]
        assert reference.startswith("BKH-RES-DEMO-")
        assert created.json()["demo_only"]

        assert client.post("/api/bokharest/demo-reservations", json=payload).status_code == 409
        tables = client.get("/api/bokharest/demo-tables", params=params).json()["tables"]
        assert not next(t for t in tables if t["table_no"] == 1)["available"]

        assert client.get("/admin/bokharest-reservations", follow_redirects=False).status_code == 303
        login = client.post("/admin/login", data={"password": "test-showcase-password"},
                            follow_redirects=False)
        assert login.status_code == 303
        admin = client.get("/admin/bokharest-reservations")
        assert admin.status_code == 200 and reference in admin.text
        csrf = re.search(r'name="csrf" value="([^"]+)"', admin.text).group(1)
        cancel = client.post("/admin/bokharest-reservations/1/cancel",
                             data={"csrf": csrf}, follow_redirects=False)
        assert cancel.status_code == 303
        tables = client.get("/api/bokharest/demo-tables", params=params).json()["tables"]
        assert next(t for t in tables if t["table_no"] == 1)["available"]

    with sqlite3.connect(tmp_path / "showcase.sqlite") as db:
        assert db.execute("SELECT COUNT(*) FROM bokharest_demo_reservations").fetchone()[0] == 1
        # The production-scoped Bokharest ordering module is not installed in this pilot.
        if db.execute("SELECT name FROM sqlite_master WHERE name='bokharest_orders'").fetchone():
            assert db.execute("SELECT COUNT(*) FROM bokharest_orders").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0


def test_booking_validation(tmp_path):
    with new_client(tmp_path) as client:
        date = tomorrow()
        payload = {"date": date, "time": "19:00", "guests": 4, "table_no": 1}
        assert client.post("/api/bokharest/demo-reservations", json=payload).status_code == 422
        payload["table_no"] = 6  # seeded, clearly fictional occupancy
        assert client.post("/api/bokharest/demo-reservations", json=payload).status_code == 409
        payload["table_no"] = 5
        payload["date"] = "2020-01-01"
        assert client.post("/api/bokharest/demo-reservations", json=payload).status_code == 422


def test_bokharest_social_replies_are_natural_and_do_not_fabricate_menu(tmp_path):
    """Everyday Arabic/English chat should not be reported as a missing dish."""
    greetings = {
        "صباح الخير": ("صباح النور", "شو بتحب تطلب"),
        "صباح النور": ("صباح النور", "شو بتحب تطلب"),
        "مسا الخير": ("مساء النور", "شو حابب تطلب"),
        "مساء الخير": ("مساء النور", "شو حابب تطلب"),
        "كيفك": ("إنت كيفك", "شو بتحب تطلب"),
        "صباح الخير كيفك": ("صباح النور", "شو بتحب تطلب"),
        "أهلاً": ("أهلين", "شو حابب تطلب"),
        "السلام عليكم": ("أهلين", "شو حابب تطلب"),
        "بدي اطلب": ("تفضل", "شو بتحب تطلب"),
        "شكراً": ("العفو", "بوخارست"),
        "مع السلامة": ("مع السلامة", "بوخارست"),
        "good morning": ("صباح النور", "بوخارست"),
    }
    with new_client(tmp_path) as client:
        for phrase, expected_parts in greetings.items():
            r = client.post("/api/bokharest/demo-chat", json={"message": phrase})
            assert r.status_code == 200, (phrase, r.text)
            data = r.json()
            assert data["mode"] == "catalogue-demo"
            assert data["items"] == []
            assert "مش لاقي صنف" not in data["text"]
            assert all(p in data["text"] for p in expected_parts), (phrase, data)

        # Greeting and substantive question in one turn must still search the menu.
        dish = client.post("/api/bokharest/demo-chat",
                           json={"message": "صباح الخير عندكم دجاج؟"}).json()
        assert dish["items"] and "دجاج" in dish["text"]
        allergy = client.post("/api/bokharest/demo-chat",
                              json={"message": "صباح الخير عندي حساسية مكسرات"}).json()
        assert not allergy["items"] and "موظف" in allergy["text"]
        booking = client.post("/api/bokharest/demo-chat",
                              json={"message": "مساء الخير عايزة أحجز طاولة"}).json()
        assert booking["link"] == "/bokharest/reserve"



def test_bokharest_chat_remembers_chicken_and_recommends_with_reason(tmp_path):
    """Multi-turn dialogue must resolve pronouns without inventing menu products."""
    with new_client(tmp_path) as client:
        def chat(message, history=()):
            response = client.post("/api/bokharest/demo-chat",
                                   json={"message": message, "history": list(history)})
            assert response.status_code == 200, response.text
            return response.json()

        customer = "عندكم فراخ؟"
        listed = chat(customer)
        assert len(listed["items"]) == 2
        assert "كانتري تشيكن" in listed["text"]
        assert "ترياكي تشيكن" in listed["text"]

        history = [customer, listed["text"]]
        chosen = chat("إيه أفضلهم؟", history)
        assert "ترياكي تشيكن" in chosen["text"]
        assert chosen["items"][0]["id"] == 96
        assert "مشوي" in chosen["text"]
        assert "مش لاقي صنف" not in chosen["text"]

        expanded_history = history + ["إيه أفضلهم؟", chosen["text"]]
        price = chat("طب بكام؟", expanded_history)
        assert "ترياكي تشيكن" in price["text"]
        assert "129.99" in price["text"]
        assert "كانتري تشيكن" not in price["text"]

        compared = chat("إيه الفرق بينهم؟", history)
        assert "كانتري تشيكن" in compared["text"]
        assert "ترياكي تشيكن" in compared["text"]

        healthy = chat("مين أخف أو صحي أكتر؟", history)
        assert healthy["items"][0]["id"] == 96
        assert "ما عندناش سعرات" in healthy["text"]

        choice = chat("اختارلي حاجة على زوقك")
        assert choice["items"] and "أرشّحلك" in choice["text"]
        assert "مش لاقي صنف" not in choice["text"]
        allergy = chat("عندي حساسية سمسم", expanded_history)
        assert not allergy["items"]
        assert "موظف المطعم" in allergy["text"]



def test_reservations_chat_isolated_from_table_script(tmp_path):
    """The chat must still initialize if table booking fails on the client."""
    with new_client(tmp_path) as client:
        page = client.get("/bokharest/reserve")
        assert page.status_code == 200
        assert 'id="chatForm"' in page.text
        assert 'id="sendChat"' in page.text
        assert 'id="chatInput"' in page.text
        assert 'id="micChat"' in page.text
        assert '/static/bokharest_reservations_chat.js?v=1' in page.text
        assert "function bubble(" not in page.text
        script = client.get("/static/bokharest_reservations_chat.js")
        assert script.status_code == 200
        assert 'form.addEventListener("submit"' in script.text
        assert 'suggestions.addEventListener("click"' in script.text
        assert "/api/bokharest/demo-chat" in script.text
        assert "history.push(question, answer)" in script.text
        assert "AbortController" in script.text
        assert "DOMContentLoaded" in script.text
        assert "rec.onend" in script.text

        chicken = client.post("/api/bokharest/demo-chat",
                              json={"message": "عندكم دجاج؟", "history": []})
        assert chicken.status_code == 200
        assert chicken.json()["items"]

        followup = client.post("/api/bokharest/demo-chat",
                               json={"message": "إيه أفضلهم؟",
                                     "history": ["عندكم دجاج؟", chicken.json()["text"]]})
        assert followup.status_code == 200
        assert "ترياكي تشيكن" in followup.json()["text"]


def test_tell_me_more_about_previous_recommendation(tmp_path):
    """Customers should not lose context after accepting 'أحكيلك عنه أكتر؟'."""
    with new_client(tmp_path) as client:
        def send(message, history):
            result = client.post("/api/bokharest/demo-chat",
                                 json={"message": message, "history": history[-6:]})
            assert result.status_code == 200, result.text
            return result.json()

        history = []
        def turn(message):
            response = send(message, history)
            history.extend([message, response["text"]])
            return response

        listed = turn("عندك ايه فراخ النهاردة؟")
        assert len(listed["items"]) == 2
        recommended = turn("اختارلي واحد على ذوقك")
        assert recommended["items"][0]["id"] == 96
        assert "تحبي أحكيلك عنه أكتر" in recommended["text"]

        explained = turn("احكيلي عنه اكتر")
        assert explained["items"][0]["id"] == 96
        assert "ترياكي تشيكن" in explained["text"]
        assert "مشوية" in explained["text"]
        assert "129.99" in explained["text"]
        assert "مش قادر أحدد" not in explained["text"]

        price = turn("طب هو بكام؟")
        assert "ترياكي تشيكن" in price["text"]
        assert "129.99" in price["text"]

        # Common voice dictation and Arabic colloquial variants.
        for variant in ("احكيلي عنها أكتر", "احكي له عنها أكتر",
                        "قوليلي تفاصيله", "اشرحلي عنه", "tell me more"):
            explanation = send(variant, history)
            assert explanation["items"][0]["id"] == 96, (variant, explanation)
            assert "ترياكي تشيكن" in explanation["text"]

        # Explicit new menu item overrides prior assistant suggestions.
        other = send("احكيلي عن كانتري تشيكن", history)
        assert other["items"][0]["id"] == 95
        assert "كانتري تشيكن" in other["text"]

        no_history = send("احكيلي عنه أكتر", [])
        assert no_history["items"] == []
        assert "أنهي صنف" in no_history["text"]

        allergy = send("عندي حساسية سمسم، احكيلي عنه", history)
        assert allergy["items"] == []
        assert "موظف المطعم" in allergy["text"]
