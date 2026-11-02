"""Exercise the real provider adapters and API with isolated DBs and HTTP mocks."""
import asyncio
import json
import sqlite3
from time import monotonic

import httpx
import pytest
from fastapi.testclient import TestClient

import app as app_module
from app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    with TestClient(create_app(tmp_path / 'safety.sqlite',
                    admin_password='strong-local-test-password', secret_key='s' * 50)) as client:
        yield client


@pytest.fixture
def install_transport(monkeypatch):
    original_client = httpx.AsyncClient

    def install(handler):
        transport = httpx.MockTransport(handler)
        monkeypatch.setattr(httpx, 'AsyncClient',
                            lambda **kwargs: original_client(transport=transport, **kwargs))
    return install


def enable(monkeypatch, provider):
    monkeypatch.setenv('GEMINI_API_KEY' if provider == 'gemini' else 'OPENAI_API_KEY',
                       'private-dummy-test-key')


def provider_reply(provider, answer, *, complete=True):
    raw = answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)
    if provider == 'gemini':
        data = {'candidates': [{'finishReason': 'STOP' if complete else 'MAX_TOKENS',
                               'content': {'parts': [{'text': raw}]}}]}
    else:
        data = {'choices': [{'finish_reason': 'stop' if complete else 'length',
                             'message': {'content': raw}}]}
    return httpx.Response(200, json=data)


def chat(client, *, language='ar', dialect='egyptian', words='رشحلي بيتزا نباتي في حدود 200 جنيه'):
    result = client.post('/api/chat', json={'language': language, 'dialect': dialect,
                         'messages': [{'role': 'user', 'content': words}]})
    assert result.status_code == 200, result.text
    return result.json()


@pytest.mark.parametrize('provider', ['gemini', 'openai'])
@pytest.mark.parametrize('extra', [
    {'text': 'السعر 1 جنيه'},
    {'text': 'السعر ١ جنيه'},
    {'text': 'The total is one hundred Egyptian pounds.'},
    {'text': 'تم إرسال الطلب للمطبخ'},
    {'text': 'Votre commande est confirmée.'},
    {'quick_replies': ['السعر 1 جنيه']},
    {'quick_replies': ['Order completed']},
    {'price_piasters': 1},
])
def test_generated_prose_and_prices_never_reach_customer(client, monkeypatch, install_transport,
                                                         provider, extra):
    enable(monkeypatch, provider)
    unsafe = {'intent': 'recommend', 'item_ids': [1], **extra}
    install_transport(lambda request: provider_reply(provider, unsafe))
    answer = chat(client)
    assert answer['mode'] == 'guided'
    assert answer['choices'][0]['price_piasters'] == 18500
    displayed = answer['text'] + ' '.join(answer['quick_replies'])
    for value in extra.values():
        for phrase in value if isinstance(value, list) else [value]:
            if isinstance(phrase, str):
                assert phrase not in displayed
    with sqlite3.connect(client.app.state.db_path) as db:
        assert db.execute('SELECT COUNT(*) FROM orders').fetchone()[0] == 0


@pytest.mark.parametrize('provider', ['gemini', 'openai'])
@pytest.mark.parametrize('answer', [
    {'intent': 'recommend', 'item_ids': [9999]},
    {'intent': 'recommend', 'item_ids': [1, 1]},
    {'intent': 'recommend', 'item_ids': [True]},
    {'intent': 'recommend', 'item_ids': [1.0]},
    {'intent': 'recommend', 'item_ids': ['1']},
    {'intent': 'recommend', 'item_ids': []},
    {'intent': 'recommend', 'item_ids': [1, 2, 3, 4]},
    {'intent': 'order_help', 'item_ids': [1]},
    {'intent': 'order_confirmed', 'item_ids': []},
    {'intent': [], 'item_ids': []},
    {'intent': 'recommend'}, [], 'not JSON',
])
def test_malformed_decisions_fall_back(client, monkeypatch, install_transport, provider, answer):
    enable(monkeypatch, provider)
    install_transport(lambda request: provider_reply(provider, answer))
    result = chat(client)
    assert result['mode'] == 'guided'
    assert all(p['id'] != 9999 for p in result['choices'])


@pytest.mark.parametrize('provider', ['gemini', 'openai'])
@pytest.mark.parametrize('language,dialect,expected', [
    ('ar', 'egyptian', 'دي اختيارات'), ('ar', 'lebanese', 'هيدي خيارات'),
    ('ar', 'standard', 'هذه خيارات'), ('en', 'egyptian', 'Here are'),
    ('fr', 'egyptian', 'Voici'),
])
def test_valid_recommendations_keep_language_and_database_prices(client, monkeypatch, install_transport,
                                                                provider, language, dialect, expected):
    enable(monkeypatch, provider)
    install_transport(lambda request: provider_reply(provider, {'intent': 'recommend', 'item_ids': [1]}))
    result = chat(client, language=language, dialect=dialect)
    assert result['mode'] == 'ai' and result['provider'] == provider
    assert result['text'].startswith(expected)
    original = client.get('/api/menu').json()['items'][0]
    assert result['choices'][0]['name'] == original['name']
    assert result['choices'][0]['price_piasters'] == original['price_piasters']


@pytest.mark.parametrize('intent', ['greet', 'ask_category', 'ask_budget', 'ask_preference',
                                  'no_match', 'menu_help', 'order_help', 'staff_help'])
def test_non_recommendation_intents_cannot_create_orders(client, monkeypatch, install_transport, intent):
    enable(monkeypatch, 'gemini')
    install_transport(lambda request: provider_reply('gemini', {'intent': intent, 'item_ids': []}))
    result = chat(client)
    assert result['mode'] == 'ai' and result['choices'] == []
    assert result['needs_staff'] is (intent == 'staff_help')
    with sqlite3.connect(client.app.state.db_path) as db:
        assert db.execute('SELECT COUNT(*) FROM orders').fetchone()[0] == 0


@pytest.mark.parametrize('provider', ['gemini', 'openai'])
def test_price_edit_during_generation_is_reflected_in_response(client, monkeypatch, install_transport, provider):
    enable(monkeypatch, provider)
    def handler(request):
        with sqlite3.connect(client.app.state.db_path) as db:
            db.execute('UPDATE menu_items SET price_piasters=19900 WHERE id=1')
        return provider_reply(provider, {'intent': 'recommend', 'item_ids': [1]})
    install_transport(handler)
    assert chat(client)['choices'][0]['price_piasters'] == 19900


@pytest.mark.parametrize('provider', ['gemini', 'openai'])
@pytest.mark.parametrize('change_during_request', [False, True])
def test_unavailable_choices_use_fresh_local_menu(client, monkeypatch, install_transport,
                                                provider, change_during_request):
    enable(monkeypatch, provider)
    def hide_item():
        with sqlite3.connect(client.app.state.db_path) as db:
            db.execute('UPDATE menu_items SET available=0 WHERE id=1')
    if not change_during_request:
        hide_item()
    def handler(request):
        if change_during_request:
            hide_item()
        return provider_reply(provider, {'intent': 'recommend', 'item_ids': [1]})
    install_transport(handler)
    result = chat(client)
    assert result['mode'] == 'guided'
    assert all(p['id'] != 1 for p in result['choices'])


@pytest.mark.parametrize('provider', ['gemini', 'openai'])
def test_incomplete_provider_response_is_rejected(client, monkeypatch, install_transport, provider):
    enable(monkeypatch, provider)
    install_transport(lambda request: provider_reply(provider, {'intent': 'recommend', 'item_ids': [1]},
                                                      complete=False))
    assert chat(client)['mode'] == 'guided'


@pytest.mark.parametrize('failure', [401, 403, 404, 429, 500, 503, 'timeout', 'empty', 'malformed'])
@pytest.mark.parametrize('openai_enabled', [False, True])
def test_gemini_failures_reach_configured_fallback(client, monkeypatch, install_transport,
                                                 failure, openai_enabled):
    enable(monkeypatch, 'gemini')
    if openai_enabled:
        enable(monkeypatch, 'openai')
    calls = []
    def handler(request):
        provider = 'gemini' if request.url.host == 'generativelanguage.googleapis.com' else 'openai'
        calls.append(provider)
        if provider == 'openai':
            return provider_reply(provider, {'intent': 'recommend', 'item_ids': [1]})
        if failure == 'timeout':
            raise httpx.ReadTimeout('provider timeout', request=request)
        if failure == 'empty':
            return httpx.Response(200, json={'candidates': []})
        if failure == 'malformed':
            return httpx.Response(200, content=b'not-json')
        return httpx.Response(failure, json={'error': {'message': 'provider unavailable'}})
    install_transport(handler)
    answer = chat(client)
    assert answer['choices'][0]['price_piasters'] == 18500
    if openai_enabled:
        assert calls == ['gemini', 'openai']
        assert answer['provider'] == 'openai' and answer['mode'] == 'ai'
    else:
        assert calls == ['gemini'] and answer['mode'] == 'guided'


def test_both_providers_fail_without_leaking_exceptions(client, monkeypatch, install_transport, caplog):
    enable(monkeypatch, 'gemini')
    enable(monkeypatch, 'openai')
    calls = []
    def handler(request):
        calls.append(request.url.host)
        raise RuntimeError('private-dummy-test-key customer-private-message')
    install_transport(handler)
    assert chat(client)['mode'] == 'guided'
    assert len(calls) == 2
    assert 'private-dummy-test-key' not in caplog.text
    assert 'customer-private-message' not in caplog.text
    assert 'RuntimeError' in caplog.text


def test_overall_provider_deadline_cancels_stalled_call(client, monkeypatch):
    enable(monkeypatch, 'gemini')
    monkeypatch.setattr(app_module, 'CHAT_PROVIDER_TIMEOUT_SECONDS', 0.01)
    cancelled = []
    async def stalled(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)
    monkeypatch.setattr(app_module, 'gemini_chat', stalled)
    started = monotonic()
    assert chat(client)['mode'] == 'guided'
    assert monotonic() - started < 1
    assert cancelled == [True]


def test_health_context_and_rate_limit_do_not_call_provider(client, monkeypatch, install_transport):
    enable(monkeypatch, 'gemini')
    enable(monkeypatch, 'openai')
    calls = []
    def handler(request):
        calls.append(request.url.host)
        return provider_reply('gemini', {'intent': 'recommend', 'item_ids': [1]})
    install_transport(handler)
    for words in ['عندي حساسية من المكسرات', 'عايز أكل قليل الملح']:
        answer = chat(client, words=words)
        assert answer['mode'] == 'guided' and answer['needs_staff']
    assert calls == []
    for _ in range(12):
        assert chat(client)['provider'] == 'gemini'
    result = client.post('/api/chat', json={'messages': [{'role': 'user', 'content': 'بيتزا'}]})
    assert result.status_code == 429
    assert len(calls) == 12
