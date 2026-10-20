"""Dynamic catalogue and privacy-safe nutritional preference conversation."""
from pathlib import Path
from fastapi.testclient import TestClient
from app import create_app
import re
import sqlite3


def new_client(tmp_path: Path):
    return TestClient(create_app(db_path=tmp_path / "dynamic-menu.sqlite",
                                 admin_password="local-test-password",
                                 secret_key="dynamic-menu-secret-must-be-long-enough-999999"))


def csrf_token(client):
    login = client.post("/admin/login", data={"password": "local-test-password"}, follow_redirects=False)
    assert login.status_code == 303
    page = client.get("/admin")
    assert page.status_code == 200
    return re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)


def chat(client, text, *, language="ar"):
    resp = client.post("/api/chat", json={"language": language,
                       "messages": [{"role": "user", "content": text}]})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_custom_category_insert_and_dynamic_chat(tmp_path):
    with new_client(tmp_path) as client:
        csrf = csrf_token(client)
        form = {"csrf": csrf, "name": "شوربة عدس بالليمون", "description": "عدس وليمون",
                "category": "أخرى", "category_custom": "شوربات شرقية", "price": "73.50"}
        result = client.post("/admin/menu", data=form, follow_redirects=False)
        assert result.status_code == 303, result.text
        all_menu = client.get("/api/menu").json()
        added = next(i for i in all_menu["items"] if i["name"] == "شوربة عدس بالليمون")
        assert added["category"] == "شوربات شرقية"
        assert added["price_piasters"] == 7350
        assert "شوربات شرقية" in all_menu["categories"]
        answer = chat(client, "عندكم شوربة عدس؟")
        assert any(i["id"] == added["id"] for i in answer["choices"]), answer
        assert answer["mode"] == "guided"
        all_answer = chat(client, "إيه المنيو عندكم؟")
        assert "شوربات شرقية" in all_answer["text"]
        assert "قسم جديد" in client.get("/admin").text

        edited = client.post(f'/admin/menu/{added["id"]}', data={
            "csrf": csrf, "name": "شوربة عدس بالليمون", "category": "أخرى",
            "category_custom": "شوربات موسمية", "price": "90", "available": "on"
        }, follow_redirects=False)
        assert edited.status_code == 303
        assert "شوربات موسمية" in client.get("/api/menu").json()["categories"]
        assert "شوربات موسمية" in chat(client, "المنيو")["text"]


def test_chicken_is_never_confused_with_brownies(tmp_path):
    with new_client(tmp_path) as client:
        reply = chat(client, "عندكم فراخ؟")
        assert reply["choices"], reply
        assert all("براونيز" not in i["name"] for i in reply["choices"])


def test_dietary_disclosure_gives_cautious_answer_without_food_recommendations(tmp_path):
    with new_client(tmp_path) as client:
        for phrase in ("أنا عندي سكر", "عندي ضغط عالي", "عندي كوليسترول",
                       "عايزة أكل قليل الملح", "عايزة حاجة بدون سكر"):
            result = chat(client, phrase)
            assert result["needs_staff"], (phrase, result)
            assert result["choices"] == []
            assert "مش هقدر" in result["text"]
            assert "طبيب" in result["text"]
        result = chat(client, "I have diabetes", language="en")
        assert result["needs_staff"]
        assert result["choices"] == []


def test_health_disclosure_not_sent_to_external_ai(tmp_path, monkeypatch):
    import app as app_module
    async def fake_ai(*args, **kwargs):
        raise AssertionError("Sensitive dietary details must not be forwarded to AI provider")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-local-key")
    monkeypatch.setattr(app_module, "ai_chat", fake_ai)
    with new_client(tmp_path) as client:
        response = chat(client, "عندي سكر وعايز بيتزا")
        assert response["mode"] == "guided"
        assert response["needs_staff"]
        assert response["choices"] == []
        assert chat(client, "عندي حساسية مكسرات")["needs_staff"]


def test_logo_mobile_brand_and_cache_bust(tmp_path):
    with new_client(tmp_path) as client:
        assert "/static/brand.css?v=1.5" in client.get("/").text
        assert "/static/brand.css?v=1.3" in client.get("/admin/login").text
        css = client.get("/static/brand.css").text
        assert "overflow:visible" in css
        assert "object-fit:contain" in css
        assert "@media(max-width:700px)" in css
