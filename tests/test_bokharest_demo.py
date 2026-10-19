"""Bokharest demo checkout remains separate from real restaurant orders."""
import secrets
import sqlite3
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from app import create_app
from bokharest_ordering import _catalog


def payload_for(client):
    _, catalog = _catalog()
    item_id = next(iter(catalog))
    order_lines = [{"item_id": item_id, "quantity": 2}]
    price = client.post("/api/bokharest/quote", json={"items": order_lines})
    assert price.status_code == 200, price.text
    assert price.json()["checkout_enabled"] is False
    return {
        "items": order_lines, "table_no": 7, "note": "اختبار فقط",
        "expected_total_piasters": price.json()["total_piasters"],
        "idempotency_key": "test-" + secrets.token_hex(20)
    }


def test_cart_quote_demo_idempotency_and_isolation(tmp_path):
    db_path = tmp_path / "demo.sqlite"
    with patch.dict("os.environ", {}, clear=False):
        app = create_app(db_path, admin_password="test-password", secret_key="s"*50)
        with TestClient(app) as client:
            payload = payload_for(client)
            with patch("bokharest_demo._send_whatsapp", return_value="not_configured") as wa:
                response = client.post("/api/bokharest/demo-orders", json=payload)
                assert response.status_code == 201, response.text
                result = response.json()
                assert result["reference"].startswith("BKH-TEST-")
                assert result["alert_status"] == "not_configured"
                assert wa.call_count == 1
                repeat = client.post("/api/bokharest/demo-orders", json=payload)
                assert repeat.status_code == 201
                assert repeat.json()["reference"] == result["reference"]
                assert wa.call_count == 1
            bad_price = payload.copy()
            bad_price["idempotency_key"] = "test-" + secrets.token_hex(20)
            bad_price["expected_total_piasters"] += 1
            assert client.post("/api/bokharest/demo-orders", json=bad_price).status_code == 409
            bad_table = payload.copy()
            bad_table["idempotency_key"] = "test-" + secrets.token_hex(20)
            bad_table["table_no"] = 0
            assert client.post("/api/bokharest/demo-orders", json=bad_table).status_code == 422
            assert client.get("/admin/bokharest-demo", follow_redirects=False).status_code == 303
            assert client.get("/static/bokharest_cart.js").status_code == 200
    with sqlite3.connect(db_path) as con:
        assert con.execute("select count(*) from bokharest_demo_orders").fetchone()[0] == 1
        assert con.execute("select table_no from bokharest_demo_orders").fetchone()[0] == 7
        assert con.execute("select count(*) from orders").fetchone()[0] == 0


def test_whatsapp_disabled_without_api_secrets():
    from bokharest_demo import _wa_ready, _send_whatsapp
    with patch.dict("os.environ", {
        "BOKHAREST_ALERT_PHONE": "201000000000",
        "BOKHAREST_WA_TOKEN": "",
        "BOKHAREST_WA_PHONE_ID": "",
        "BOKHAREST_WA_TEMPLATE": ""
    }):
        assert not _wa_ready()
        assert _send_whatsapp({"table_no": 3, "total_piasters": 12000}, []) == "not_configured"
