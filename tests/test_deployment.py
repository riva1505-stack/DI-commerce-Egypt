"""Checks essential deployment behavior without contacting a hosting provider."""

from pathlib import Path
from fastapi.testclient import TestClient
import pytest

from app import create_app


def test_production_rejects_default_password_and_secret(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(RuntimeError):
        create_app(tmp_path / "prod.db")


def test_production_https_admin_cookie_and_railway_domain(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    monkeypatch.setenv("RAILWAY_PUBLIC_DOMAIN", "my-demo.up.railway.app")
    app = create_app(tmp_path / "prod.db", admin_password="uniquely-secure-long-password",
                     secret_key="unit-test-secret-key-over-32-characters-long")
    assert app.state.public_base == "https://my-demo.up.railway.app"
    with TestClient(app, base_url="https://my-demo.up.railway.app") as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/menu").status_code == 200
        response = client.post("/admin/login", data={"password": "uniquely-secure-long-password"}, follow_redirects=False)
        assert response.status_code == 303
        assert "secure" in response.headers["set-cookie"].lower()
        assert client.get("/admin").status_code == 200
