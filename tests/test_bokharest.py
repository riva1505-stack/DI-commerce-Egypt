"""Read-only Bokharest menu is separate from the existing single-restaurant checkout."""
from pathlib import Path
import json

from fastapi.testclient import TestClient
from app import create_app, BASE_DIR


def test_bokharest_preview_and_independent_demo(tmp_path: Path):
    app = create_app(tmp_path / "menu-test.sqlite", admin_password="test-password",
                     secret_key="x" * 50)
    with TestClient(app) as client:
        page = client.get("/bokharest")
        assert page.status_code == 200
        assert "بوخاريست" in page.text
        assert "/static/bokharest.js" in page.text
        assert "checkout" not in page.text.lower()
        assert client.get("/static/bokharest.css").status_code == 200
        assert client.get("/static/bokharest.js").status_code == 200
        # The old pilot remains untouched and still shows its original catalogue.
        home = client.get("/")
        assert home.status_code == 200
        assert 'href="/bokharest"' in home.text
        original = client.get("/api/menu").json()
        assert original["settings"]["restaurant_name"] == "بيت المذاق"


def test_photo_menu_data_has_valid_prices_and_explicit_preview_status():
    path = BASE_DIR / "static" / "data" / "bokharest_menu.json"
    menu = json.loads(path.read_text(encoding="utf-8"))
    assert menu["restaurant"]["checkout_enabled"] is False
    assert menu["restaurant"]["status"] == "menu-preview-only"
    assert menu["restaurant"]["service_charge_percent"] == 12
    assert menu["restaurant"]["vat_percent"] == 14
    categories = menu["categories"]
    assert len(categories) == 10
    items = [i for c in categories for i in c["items"]]
    assert len(items) == 104
    assert len({i["id"] for i in items}) == 104
    assert all(isinstance(i["price_piasters"], int) and i["price_piasters"] > 0
               and i["name_ar"].strip() and i["name_en"].strip() for i in items)
    prices = {i["name_en"]: i["price_piasters"] for i in items}
    assert prices["Country Chicken"] == 14999
    assert prices["Mocha After 8"] == 4499
    assert prices["Bokharest Burger Double"] == 11999
    assert prices["Mojito Orange"] == 5999


def test_bokharest_responsive_layout_keeps_menu_accessible():
    """Guard the phone/tablet/desktop styling and cache-busted stylesheet."""
    html = (BASE_DIR / "templates" / "bokharest.html").read_text(encoding="utf-8")
    css = (BASE_DIR / "static" / "bokharest.css").read_text(encoding="utf-8")
    assert 'name="viewport"' in html
    assert "width=device-width" in html
    assert "/static/bokharest.css?v=3" in html
    assert 'id="search"' in html and 'id="categories"' in html
    assert "@media (max-width:639px)" in css
    assert "@media (max-width:1023px)" in css
    assert "@media (min-width:1024px)" in css
    assert ".menu-grid{grid-template-columns:minmax(0,1fr)" in css
    assert ".menu-grid{grid-template-columns:repeat(2,minmax(0,1fr))}" in css
    assert ".menu-grid{grid-template-columns:repeat(3,minmax(0,1fr))" in css
    assert ".categories{flex-wrap:nowrap;overflow-x:auto" in css
    assert ".search input{min-width:0;font-size:16px}" in css
    assert ".cat:focus-visible" in css
    assert "@media (prefers-reduced-motion:reduce)" in css
    assert css.count("{") == css.count("}")


def test_bokharest_demo_order_separate_from_existing_restaurant(tmp_path: Path, monkeypatch):
    """Server estimates prices, records a test order, and cannot contact live restaurant."""
    from bokharest_demo import _send_whatsapp
    monkeypatch.delenv("BOKHAREST_WA_TOKEN", raising=False)
    monkeypatch.delenv("BOKHAREST_ALERT_PHONE", raising=False)
    assert _send_whatsapp({"table_no": 5, "total_piasters": 100}, []) == "not_configured"
    app = create_app(tmp_path / "isolated-demo.sqlite", admin_password="test-password",
                     secret_key="x" * 50)
    with TestClient(app) as client:
        bad = client.post("/api/bokharest/quote",
                          json={"items": [{"item_id": 999999, "quantity": 1}]})
        assert bad.status_code == 409
        quote = client.post("/api/bokharest/quote",
                            json={"items": [{"item_id": 1, "quantity": 2}]})
        assert quote.status_code == 200
        q = quote.json()
        assert q["subtotal_piasters"] == 11998
        assert q["total_piasters"] > q["subtotal_piasters"]
        assert q["checkout_enabled"] is False
        payload = {"table_no": 5, "note": "من غير سكر",
                   "idempotency_key": "test-bokharest-isolated-123",
                   "items": [{"item_id": 1, "quantity": 2}],
                   "expected_total_piasters": q["total_piasters"]}
        wrong = client.post("/api/bokharest/demo-orders",
                            json={**payload, "expected_total_piasters": 1})
        assert wrong.status_code == 409
        created = client.post("/api/bokharest/demo-orders", json=payload)
        assert created.status_code == 201, created.text
        data = created.json()
        assert data["status"] == "demo"
        assert data["reference"].startswith("BKH-TEST-")
        assert data["alert_status"] == "not_configured"
        assert data["total_piasters"] == q["total_piasters"]
        repeated = client.post("/api/bokharest/demo-orders", json=payload)
        assert repeated.status_code == 201
        assert repeated.json()["reference"] == data["reference"]
        assert client.post("/api/bokharest/orders", json=payload).status_code == 404
        assert client.get("/admin/bokharest-demo", follow_redirects=False).status_code == 303
        import sqlite3
        with sqlite3.connect(tmp_path / "isolated-demo.sqlite") as db:
            assert db.execute("SELECT COUNT(*) FROM bokharest_demo_orders").fetchone()[0] == 1
            row = db.execute("SELECT table_no,note FROM bokharest_demo_orders").fetchone()
            assert row == (5, "من غير سكر")
            assert db.execute("SELECT COUNT(*) FROM bokharest_demo_lines").fetchone()[0] == 1
            assert db.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0


def test_bokharest_demo_cart_files_and_no_phone_leak():
    html = (BASE_DIR / "templates" / "bokharest.html").read_text(encoding="utf-8")
    js = (BASE_DIR / "static" / "bokharest_cart.js").read_text(encoding="utf-8")
    css = (BASE_DIR / "static" / "bokharest.css").read_text(encoding="utf-8")
    backend = (BASE_DIR / "bokharest_demo.py").read_text(encoding="utf-8")
    assert "/static/bokharest_cart.js?v=1" in html
    assert 'id="demoTable"' in html and 'id="demoSubmit"' in html
    assert ".demo-cart-panel" in css
    assert "/api/bokharest/quote" in js and "/api/bokharest/demo-orders" in js
    assert "BOKHAREST_ALERT_PHONE" in backend
    assert "_send_whatsapp" in backend
    assert "BOKHAREST_WA_TOKEN" in backend
    assert "01030954545" not in html + js + backend
    assert "https://wa.me/" not in html + js  # never disclose the private recipient in frontend
