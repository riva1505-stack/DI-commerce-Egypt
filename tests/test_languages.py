"""Language and dialect regression coverage; no live AI or TTS calls."""
import asyncio
from pathlib import Path

from fastapi.testclient import TestClient
from app import create_app
import voice_gateway


def make_client(tmp_path: Path):
    return TestClient(create_app(tmp_path / "language-test.sqlite",
                     admin_password="a-strong-test-password",
                     secret_key="a-test-secret-over-32-characters-long-0123"))


def test_customer_can_select_language_and_dialect(tmp_path):
    with make_client(tmp_path) as client:
        homepage = client.get("/")
        assert homepage.status_code == 200
        assert 'id="diLanguage"' in homepage.text
        assert 'value="ar-eg"' in homepage.text
        assert 'value="ar-lb"' in homepage.text
        assert 'value="en"' in homepage.text
        assert 'value="fr"' in homepage.text
        assert '/static/i18n.js' in homepage.text
        assert client.get("/static/i18n.js").status_code == 200


def test_english_guided_dialogue_uses_only_real_menu_items(tmp_path):
    with make_client(tmp_path) as client:
        r = client.post("/api/chat", json={
            "language": "en", "messages": [{"role": "user", "content": "Pizza under 200 EGP"}]
        })
        assert r.status_code == 200
        reply = r.json()
        assert reply["mode"] == "guided"
        assert "recommend" in reply["text"].lower()
        assert reply["choices"]
        assert all(item["price_piasters"] <= 20000 for item in reply["choices"])
        menu_ids = {item["id"] for item in client.get("/api/menu").json()["items"]}
        assert all(item["id"] in menu_ids for item in reply["choices"])


def test_french_dialogue_and_food_allergy_escalation(tmp_path):
    with make_client(tmp_path) as client:
        r = client.post("/api/chat", json={
            "language": "fr", "messages": [{"role": "user", "content": "Je veux une pizza à 300 EGP"}]
        })
        assert r.status_code == 200
        assert "recommande" in r.json()["text"]
        allergic = client.post("/api/chat", json={
            "language": "fr", "messages": [{"role": "user", "content": "Je suis allergique aux arachides"}]
        }).json()
        assert allergic["needs_staff"] is True
        assert allergic["choices"] == []


def test_unsupported_languages_and_dialects_are_rejected(tmp_path):
    with make_client(tmp_path) as client:
        msg = {"messages": [{"role": "user", "content": "hi"}]}
        assert client.post("/api/chat", json={**msg, "language": "de"}).status_code == 422
        assert client.post("/api/chat", json={**msg, "dialect": "invented"}).status_code == 422
        assert client.post("/api/voice/transcribe?language=xx",
                           headers={"Content-Type": "audio/mp4"}, content=b"voice").status_code == 422
        assert client.post("/api/voice/speak",
                           json={"text": "hi", "language": "xx"}).status_code == 422


def test_voice_endpoint_forwards_selected_language_and_dialect(tmp_path, monkeypatch):
    import app as application
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key-for-local-tests")
    seen = {}
    async def fake_stt(*args, **kwargs):
        seen["stt"] = kwargs
        return "bonjour"
    async def fake_tts(text, **kwargs):
        seen["tts"] = kwargs
        return b"fake mp3"
    monkeypatch.setattr(application, "transcribe_audio", fake_stt)
    monkeypatch.setattr(application, "synthesize_speech", fake_tts)
    with make_client(tmp_path) as client:
        stt = client.post("/api/voice/transcribe?language=fr",
                          headers={"Content-Type": "audio/mp4"}, content=b"audio")
        assert stt.status_code == 200
        assert seen["stt"]["language"] == "fr"
        tts = client.post("/api/voice/speak", json={
            "text": "مرحبا", "language": "ar", "dialect": "lebanese"})
        assert tts.status_code == 200
        assert seen["tts"]["language"] == "ar"
        assert seen["tts"]["dialect"] == "lebanese"


def test_tts_instructions_change_by_language_and_dialect(monkeypatch):
    calls = []
    class FakeResult:
        content = b"audio-result"
        def raise_for_status(self):
            pass
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def post(self, url, **kwargs):
            calls.append(kwargs["json"])
            return FakeResult()
    monkeypatch.setattr(voice_gateway.httpx, "AsyncClient", FakeClient)
    async def exercise():
        await voice_gateway.synthesize_speech("hello", api_key="test", language="en")
        await voice_gateway.synthesize_speech("bonjour", api_key="test", language="fr")
        await voice_gateway.synthesize_speech("أهلا", api_key="test", language="ar", dialect="lebanese")
    asyncio.run(exercise())
    assert "English" in calls[0]["instructions"]
    assert "français" in calls[1]["instructions"]
    assert "اللبنانية" in calls[2]["instructions"]
