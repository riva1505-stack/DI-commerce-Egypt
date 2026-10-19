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
    assert "/static/bokharest.css?v=2" in html
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
