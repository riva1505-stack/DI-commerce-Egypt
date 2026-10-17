import hashlib
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from itsdangerous import URLSafeTimedSerializer

from app import COOKIE_NAME, create_app
from auth_security import AdminAuth, PREVIEW_SECRET, hash_password

PASSWORD = "a-long-test-password-123"
SECRET = "test-signing-secret-at-least-32-characters"


@pytest.fixture(autouse=True)
def clean_config(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    for key in ("ADMIN_PASSWORD", "ADMIN_PASSWORD_HASH", "SECRET_KEY", "PUBLIC_BASE_URL", "RAILWAY_PUBLIC_DOMAIN"):
        monkeypatch.delenv(key, raising=False)


def make_app(path, password=PASSWORD, secret=SECRET):
    return create_app(path, admin_password=password, secret_key=secret)


def login(client):
    response = client.post("/admin/login", data={"password": PASSWORD}, follow_redirects=False)
    assert response.status_code == 303
    return client.cookies.get(COOKIE_NAME)


def csrf(client):
    return re.search(r'name="csrf" value="([a-f0-9]+)"', client.get("/admin").text).group(1)


def test_logout_revokes_stolen_cookie_and_preserves_other_session(tmp_path):
    app = make_app(tmp_path / "test.db")
    with TestClient(app) as first, TestClient(app) as second, TestClient(app) as thief:
        stolen = login(first)
        login(second)
        assert first.post("/admin/logout", data={"csrf": csrf(first)}, follow_redirects=False).status_code == 303
        thief.cookies.set(COOKIE_NAME, stolen)
        assert thief.get("/admin/pulse").status_code == 401
        assert first.get("/admin/pulse").status_code == 401
        assert second.get("/admin/pulse").status_code == 200


def test_password_change_revokes_sessions_and_stale_worker_cannot_issue(tmp_path):
    path = tmp_path / "test.db"
    original = make_app(path)
    with TestClient(original) as old:
        cookie = login(old)
        changed = make_app(path, password="a-new-long-password")
        with TestClient(changed) as new:
            new.cookies.set(COOKIE_NAME, cookie)
            assert new.get("/admin/pulse").status_code == 401
        assert old.get("/admin/pulse").status_code == 401
        assert old.post("/admin/login", data={"password": PASSWORD}).status_code == 401


def test_sessions_survive_restart_with_same_config_and_expire(tmp_path):
    path = tmp_path / "test.db"
    with TestClient(make_app(path)) as client:
        cookie = login(client)
        issued = client.app.state.serializer.loads(cookie)
    with sqlite3.connect(path) as db:
        stored, expires = db.execute("SELECT token_hash,expires_at FROM admin_sessions").fetchone()
        assert stored == hashlib.sha256(issued["sid"].encode()).hexdigest()
        assert stored != issued["sid"]
    with TestClient(make_app(path)) as restarted:
        restarted.cookies.set(COOKIE_NAME, cookie)
        assert restarted.get("/admin/pulse").status_code == 200
        with patch("auth_security.time.time", return_value=expires + 1):
            assert restarted.get("/admin/pulse").status_code == 401


@pytest.mark.parametrize("payload", [{"role": "admin"}, {"role": "admin", "sid": "a" * 43}, {"role": "admin", "sid": []}, [], "admin"])
def test_signed_but_unregistered_or_malformed_cookie_is_rejected(tmp_path, payload):
    app = make_app(tmp_path / "test.db")
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, app.state.serializer.dumps(payload))
        assert client.get("/admin/pulse").status_code == 401


def test_preview_secret_cannot_forge_and_tampering_is_rejected(tmp_path):
    app = make_app(tmp_path / "test.db", secret=PREVIEW_SECRET)
    with TestClient(app) as client:
        forged = URLSafeTimedSerializer(PREVIEW_SECRET, salt="ace-session-v1").dumps({"role": "admin"})
        client.cookies.set(COOKIE_NAME, forged)
        assert client.get("/admin/pulse").status_code == 401
        client.cookies.clear()
        real = login(client)
        client.cookies.clear()
        client.cookies.set(COOKIE_NAME, real + "tampered")
        assert client.get("/admin/pulse").status_code == 401


def test_login_limit_shared_across_instances_and_expires(tmp_path):
    path = tmp_path / "test.db"
    with TestClient(make_app(path)) as first, TestClient(make_app(path)) as second:
        for _ in range(5):
            assert first.post("/admin/login", data={"password": "wrong"}).status_code == 401
        blocked = second.post("/admin/login", data={"password": PASSWORD})
        assert blocked.status_code == 429
        assert 0 < int(blocked.headers["retry-after"]) <= 300
        # Forwarded headers supplied by a client must not reset the application bucket.
        assert second.post("/admin/login", headers={"X-Forwarded-For": "192.0.2.20"}, data={"password": PASSWORD}).status_code == 429
        import time
        future = time.time() + 301
        with patch("auth_security.time.time", return_value=future):
            assert second.post("/admin/login", data={"password": PASSWORD}, follow_redirects=False).status_code == 303


def test_atomic_limits_and_global_limit(tmp_path):
    encoded = hash_password(PASSWORD)
    auth = AdminAuth(tmp_path / "test.db", encoded, "test-credential-tag")
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(auth.reserve_login_attempt, ["same-client"] * 12))
    assert results.count(0) == 5
    for i in range(45):
        assert auth.reserve_login_attempt(f"other-client-{i}") == 0
    assert auth.reserve_login_attempt("new-client") > 0


@pytest.mark.parametrize("password", ["", "a", "demo12345", "           abc", "x" * 1025])
def test_production_rejects_unsafe_passwords(monkeypatch, tmp_path, password):
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(RuntimeError):
        make_app(tmp_path / "test.db", password=password)


@pytest.mark.parametrize("secret", ["", "short", PREVIEW_SECRET])
def test_production_rejects_unsafe_signing_keys(monkeypatch, tmp_path, secret):
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(RuntimeError):
        make_app(tmp_path / "test.db", secret=secret)


def test_hash_only_config_and_change_invalidation(monkeypatch, tmp_path):
    path = tmp_path / "test.db"
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", hash_password(PASSWORD))
    app = create_app(path, secret_key=SECRET)
    assert not hasattr(app.state, "admin_password")
    with TestClient(app, base_url="https://testserver") as client:
        cookie = login(client)
        assert client.get("/admin/pulse").status_code == 200
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", hash_password("another-good-password"))
    with TestClient(create_app(path, secret_key=SECRET), base_url="https://testserver") as changed:
        changed.cookies.set(COOKIE_NAME, cookie)
        assert changed.get("/admin/pulse").status_code == 401


def test_secret_rotation_revokes_cookie(tmp_path):
    path = tmp_path / "test.db"
    with TestClient(make_app(path)) as client:
        cookie = login(client)
    with TestClient(make_app(path, secret="another-long-signing-secret-for-the-test")) as changed:
        changed.cookies.set(COOKIE_NAME, cookie)
        assert changed.get("/admin/pulse").status_code == 401


@pytest.mark.parametrize("encoded", ["garbage", "pbkdf2_sha256$1$" + "00"*16 + "$" + "00"*32])
def test_bad_password_hash_fails_startup(monkeypatch, tmp_path, encoded):
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", encoded)
    with pytest.raises(ValueError):
        create_app(tmp_path / "test.db", secret_key=SECRET)


def test_cross_origin_login_and_non_ascii_csrf_are_rejected(tmp_path):
    with TestClient(make_app(tmp_path / "test.db")) as client:
        for headers in ({"Origin":"https://attacker.invalid"}, {"Origin":"null"}, {"Sec-Fetch-Site":"cross-site"}):
            assert client.post("/admin/login", data={"password":PASSWORD}, headers=headers).status_code == 403
        assert client.post("/admin/login", data={"password":PASSWORD}, headers={"Origin":"http://testserver"}, follow_redirects=False).status_code == 303
        assert client.post("/admin/logout", data={"csrf":"é"}).status_code == 403
        assert client.get("/admin/pulse").status_code == 200


def test_configured_https_origin_works_behind_proxy(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://restaurant.example")
    with TestClient(make_app(tmp_path / "test.db")) as client:
        r = client.post("/admin/login", headers={"Origin":"https://restaurant.example"}, data={"password":PASSWORD}, follow_redirects=False)
        assert r.status_code == 303
        assert "Secure" in r.headers["set-cookie"]


def test_non_ascii_tracking_token_is_404(tmp_path):
    with TestClient(make_app(tmp_path / "test.db")) as client:
        order = client.post("/api/orders", json={"table_no":1,"idempotency_key":"auth-regression-order-1234","expected_total_piasters":18500,"items":[{"item_id":1,"quantity":1}]}).json()
        assert client.get(f"/api/orders/{order['reference']}", params={"token":"é"}).status_code == 404
