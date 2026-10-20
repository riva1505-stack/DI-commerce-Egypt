"""Mocked tests for the DI primary assistant Gemini integration."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app import create_app
from gemini_main import gemini_chat


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with TestClient(create_app(tmp_path / "gemini.sqlite",
                               admin_password="test-strong-password",
                               secret_key="a" * 50)) as result:
        yield result


def _chat(client, words="رشحلي بيتزا"):
    return client.post("/api/chat", json={"messages": [
        {"role": "user", "content": words}
    ]})


def test_primary_chat_prefers_gemini_and_never_exposes_key(client, monkeypatch):
    import app as app_module
    monkeypatch.setenv("GEMINI_API_KEY", "fake-secret-key-for-test")
    called = []

    async def provider(messages, menu, **kwargs):
        called.append(kwargs)
        from assistant_engine import response
        return response("دي اختيارات من المنيو", menu, [1, 2], mode="ai") | {"provider": "gemini"}

    monkeypatch.setattr(app_module, "gemini_chat", provider)
    config = client.get("/api/chat/config")
    assert config.json()["ai_enabled"] is True
    assert config.json()["ai_provider"] == "gemini"
    assert config.json()["voice_stt_enabled"] is False
    assert "fake-secret-key" not in config.text

    answer = _chat(client).json()
    assert answer["provider"] == "gemini"
    assert answer["mode"] == "ai"
    assert [x["id"] for x in answer["choices"]] == [1, 2]
    assert called[0]["key"] == "fake-secret-key-for-test"


def test_key_missing_or_provider_offline_keeps_local_assistant(client, monkeypatch):
    assert client.get("/api/chat/config").json()["ai_enabled"] is False
    assert _chat(client).json()["mode"] == "guided"
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    import app as app_module

    async def failed(*args, **kwargs):
        raise RuntimeError("quota unavailable")

    monkeypatch.setattr(app_module, "gemini_chat", failed)
    assert _chat(client).json()["mode"] == "guided"


def test_allergy_goes_local_without_provider_call(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    import app as app_module

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("Must not send disclosed allergy to Gemini")

    monkeypatch.setattr(app_module, "gemini_chat", fail_if_called)
    answer = _chat(client, "عندي حساسية من المكسرات").json()
    assert answer["needs_staff"] is True
    assert answer["mode"] == "guided"


def test_gemini_http_request_and_validated_menu_items(client, monkeypatch):
    items = client.get("/api/menu").json()["items"]
    events = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": json.dumps({
                "text": "أرشّحلك الاختيارات دي من منيو المطعم.",
                "item_ids": [1], "quick_replies": ["عايز مشروب"]
            }, ensure_ascii=False)}]}}]}

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, endpoint, *, headers, json):
            events.append((endpoint, headers, json))
            return FakeResponse()

    monkeypatch.setattr("gemini_main.httpx.AsyncClient", FakeClient)
    result = asyncio.run(gemini_chat(
        [{"role": "user", "content": "رشّح بيتزا"}], items, key="test-key"))
    assert result["mode"] == "ai"
    assert result["choices"][0]["price_piasters"] == 18500
    assert events[0][1]["x-goog-api-key"] == "test-key"
    assert "gemini-2.5-flash:generateContent" in events[0][0]
    assert "test-key" not in json.dumps(events[0][2])


def test_gemini_rejects_invented_ids_and_generated_prices(client, monkeypatch):
    items = client.get("/api/menu").json()["items"]

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"candidates": [{"content": {"parts": [
                {"text": json.dumps(monkeypatch.answer)}
            ]}}]}

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr("gemini_main.httpx.AsyncClient", FakeClient)
    for answer in (
        {"text": "أرشح الاختيارات دي.", "item_ids": [9999], "quick_replies": []},
        {"text": "ده سعره 999 جنيه", "item_ids": [1], "quick_replies": []},
    ):
        monkeypatch.answer = answer
        with pytest.raises(ValueError):
            asyncio.run(gemini_chat(
                [{"role": "user", "content": "قولي السعر"}], items, key="test-key"))
