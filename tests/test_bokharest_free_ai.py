"""Bokharest optional Gemini AI integration tests.

Provider responses are mocked: live natural-language quality still requires
valid provider credentials and a real quota.
"""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app import create_app
from bokharest_free_ai import _render_decision, gemini_menu_reply
from bokharest_showcase import _menu_items_with_categories

COLLOQUIAL_CASES = [
    "عندك فراخ؟",
    "شو عندكن دجاج اليوم؟",
    "رشحلي حاجة ع زوقك",
    "شو بتنصحيني آكل؟",
    "إيه أحلى حاجة عندك؟",
    "بدي شي مشوي",
    "عايزة حاجة مش غالية",
    "فيه عصاير فريش؟",
    "عندكو ساندوتشات؟",
    "بدنا شي نتقاسمه",
    "طب إيه الأفضل فيهم؟",
    "مين أوفر؟",
    "ده بكام؟",
    "طيب احكيلي عنه أكتر",
    "خبريني عنه شوي",
    "شو مكوناته؟",
    "هو فيه فلفل؟",
    "شو الفرق بين هالنوعين؟",
    "طب ليه اخترتهولي؟",
    "أنا مش عارفة أقرر",
    "يعني تقترح إيه؟",
    "عايزة أكل خفيف",
    "ما بحب الحار",
    "عاوز حاجة فيها جبنة",
    "عندك حلويات؟",
    "وشو عندكم قهوة؟",
    "إيه المشروبات الساقعة؟",
    "صباح الخير، ممكن ترشحلي طبق؟",
    "ازيك، كنت عاوز أسأل عن المنيو",
    "عاوزة حاجة تانية غير اللي قولتلي عليها",
]
assert len(COLLOQUIAL_CASES) == 30


def test_trial_flag_and_30_dialect_prompts_with_mock_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-only-secret-never-real")
    app = create_app(tmp_path / "trial.sqlite",
                     admin_password="test-restaurant-password",
                     secret_key="z" * 52)
    called = []

    async def pretend_provider(message, history, items, *, api_key, model):
        called.append((message, list(history), api_key, model))
        return _render_decision(
            {"intent": "recommend", "lead": "ده اختيار لطيف",
             "item_ids": [96]}, items
        )

    monkeypatch.setattr("bokharest_showcase.gemini_menu_reply", pretend_provider)
    with TestClient(app) as client:
        config = client.get("/api/bokharest/chat-config")
        assert config.status_code == 200
        assert config.json()["ai_enabled"] is True
        assert config.json()["mode"] == "gemini-ai-demo"
        assert "test-only-secret" not in config.text
        history = []
        for message in COLLOQUIAL_CASES:
            result = client.post("/api/bokharest/demo-chat", json={
                "message": message, "history": history[-6:],
            })
            assert result.status_code == 200, (message, result.text)
            answer = result.json()
            assert answer["mode"] == "gemini-ai-demo"
            assert answer["items"][0]["id"] == 96
            assert answer["items"][0]["price_piasters"] == 12999
            assert "ترياكي تشيكن" in answer["text"]
            assert "129.99 جنيه" in answer["text"]
            history.extend([message, answer["text"]])
        assert len(called) == 30
        assert called[-1][1] == history[-8:-2]
        assert all(secret == "test-only-secret-never-real"
                   for _, _, secret, _ in called)

        # Allergens and reservations are handled locally, not sent to Gemini.
        for protected in ("أنا عندي حساسية سمسم", "عايزة أحجز ترابيزة",
                          "أنا مريضة سكري"):
            response = client.post("/api/bokharest/demo-chat",
                                   json={"message": protected, "history": []})
            assert response.status_code == 200
            assert response.json()["mode"] == "catalogue-demo"
        assert len(called) == 30


def test_no_key_uses_catalogue_without_provider(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    app = create_app(tmp_path / "nokey.sqlite",
                     admin_password="test-restaurant-password",
                     secret_key="z" * 52)
    with TestClient(app) as client:
        config = client.get("/api/bokharest/chat-config").json()
        assert config["ai_enabled"] is False
        assert config["provider"] is None
        response = client.post("/api/bokharest/demo-chat",
                               json={"message": "عندكم فراخ؟"}).json()
        assert response["mode"] == "catalogue-demo"


def test_provider_failure_recovers_with_local_catalogue(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-only-key")
    app = create_app(tmp_path / "offline.sqlite",
                     admin_password="test-restaurant-password",
                     secret_key="z" * 52)

    async def offline(*args, **kwargs):
        raise RuntimeError("provider rejected quota")

    monkeypatch.setattr("bokharest_showcase.gemini_menu_reply", offline)
    with TestClient(app) as client:
        result = client.post("/api/bokharest/demo-chat",
                             json={"message": "عندكم فراخ؟", "history": []})
        assert result.status_code == 200
        assert result.json()["mode"] == "catalogue-demo"
        assert result.json()["ai_fallback"] is True
        assert "كانتري تشيكن" in result.json()["text"]


def test_real_http_client_request_shape_with_mock_transport(monkeypatch):
    catalogue = _menu_items_with_categories()
    sent = []
    gemini_body = {"candidates": [{"content": {"parts": [{"text": json.dumps({
        "intent": "recommend", "lead": "ده اختياري",
        "item_ids": [96],
    })}]}}]}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return gemini_body

    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, headers, json):
            sent.append((url, headers, json))
            return FakeResponse()

    monkeypatch.setattr("bokharest_free_ai.httpx.AsyncClient", FakeClient)
    answer = asyncio.run(gemini_menu_reply(
        "اختارلي على ذوقك", ["عندكم فراخ؟", "عندنا تشيكن"],
        catalogue, api_key="secret-in-test"))
    assert answer["mode"] == "gemini-ai-demo"
    assert answer["items"] == [{
        "id": 96, "name": "ترياكي تشيكن", "price_piasters": 12999,
    }]
    assert "129.99 جنيه" in answer["text"]
    url, headers, body = sent[0]
    assert url.startswith("https://generativelanguage.googleapis.com/")
    assert headers["x-goog-api-key"] == "secret-in-test"
    assert "secret-in-test" not in json.dumps(body)
    posted = json.loads(body["contents"][0]["parts"][0]["text"])
    assert len(posted["history"]) == 2
    assert "ترياكي تشيكن" in str(posted["menu"])


@pytest.mark.parametrize("generated", [
    {"intent": "recommend", "lead": "صنف جديد", "item_ids": [999999]},
    {"intent": "recommend", "lead": "ماشي", "item_ids": []},
    {"intent": "compare", "lead": "مقارنة", "item_ids": [96]},
    {"intent": "recommend", "lead": "اختيار", "item_ids": [96, 96]},
    {"intent": "recommend", "lead": "اختيار", "item_ids": ["96"]},
    {"intent": "fake", "lead": "اختيار", "item_ids": [96]},
])
def test_generated_menu_id_is_checked_against_catalogue(generated):
    with pytest.raises(ValueError):
        _render_decision(generated, _menu_items_with_categories())


def test_generated_price_cannot_override_real_price():
    answer = _render_decision({
        "intent": "price", "lead": "بـ1 جنيه بس!",
        "item_ids": [96],
    }, _menu_items_with_categories())
    assert "129.99 جنيه" in answer["text"]
    assert "بـ1 جنيه بس!" not in answer["text"]
