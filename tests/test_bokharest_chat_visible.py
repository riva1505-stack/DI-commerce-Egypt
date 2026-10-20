"""Bokharest's self-service chat must be present on the public menu without paid AI."""
from fastapi.testclient import TestClient
from app import create_app


def test_bokharest_chat_appears_on_menu_and_answers_from_catalogue(tmp_path):
    app = create_app(db_path=tmp_path / "chat-visible.sqlite",
                     admin_password="test-chat-pilot",
                     secret_key="x" * 48)
    with TestClient(app) as c:
        page = c.get("/bokharest")
        assert page.status_code == 200
        html = page.text
        assert 'id="bokharestChat"' in html
        assert 'id="bokharestChatMessages"' in html
        assert 'id="bokharestChatForm"' in html
        assert 'id="bokharestChatMic"' in html
        assert 'id="bokharestChatVoice"' in html
        assert '/static/bokharest_chat.js?v=3' in html
        assert '/static/bokharest.css?v=5' in html
        assert '/static/images/ai-commerce-logo.webp' in html

        script = c.get("/static/bokharest_chat.js")
        assert script.status_code == 200
        assert "/api/bokharest/demo-chat" in script.text
        assert "speechSynthesis" in script.text
        assert "SpeechRecognition" in script.text
        assert "history.push(message, reply)" in script.text
        assert "micTimeout" in script.text
        assert "AbortController" in script.text
        assert "textContent" in script.text  # render untrusted text safely
        assert 'body: JSON.stringify({message, history:history.slice(-6)})' in script.text
        assert "/admin/" not in script.text

        reply = c.post("/api/bokharest/demo-chat",
                       json={"message": "عندكم فراخ؟", "history": []})
        assert reply.status_code == 200
        body = reply.json()
        assert body["mode"] == "catalogue-demo"
        assert body["items"]
        assert "دجاج" in body["text"]
        assert "الأسعار" in body["text"]
        assert c.get("/bokharest/reserve").status_code == 200


def test_real_di_logo_is_used_on_primary_pages(tmp_path):
    app = create_app(db_path=tmp_path / "logo-visible.sqlite",
                     admin_password="test-chat-pilot",
                     secret_key="y" * 48)
    with TestClient(app) as c:
        for route in ("/", "/bokharest", "/bokharest/reserve", "/admin/login"):
            page = c.get(route)
            assert page.status_code == 200
            assert '/static/images/ai-commerce-logo.webp' in page.text
        login = c.post("/admin/login", data={"password":"test-chat-pilot"},
                       follow_redirects=True)
        assert login.status_code == 200
        assert '/static/images/ai-commerce-logo.webp' in c.get("/admin").text
