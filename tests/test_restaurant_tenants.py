"""Tenant isolation, real image uploads, and demo ordering regression tests."""
import io
import re
import sqlite3
from pathlib import Path

from PIL import Image
from fastapi.testclient import TestClient

from app import create_app


def client_for(tmp_path):
    return TestClient(create_app(
        tmp_path / "restaurant-platform.sqlite",
        admin_password="platform-secret-password",
        secret_key="tenant-integration-secret-123456789-long"
    ))


def _csrf(content):
    match = re.search(r'name="csrf" value="([0-9a-f]+)"', content)
    assert match, content[:250]
    return match.group(1)


def _admin_platform(client):
    login = client.post("/admin/login", data={"password": "platform-secret-password"},
                        follow_redirects=False)
    assert login.status_code == 303
    return _csrf(client.get("/admin/restaurants").text)


def _make_tenant(client, token, slug, name, password):
    reply = client.post("/admin/restaurants",
                        data={"csrf": token, "slug": slug, "name": name, "password": password},
                        follow_redirects=False)
    assert reply.status_code == 303, reply.text


def _tenant_login(client, slug, password):
    r = client.post(f"/r/{slug}/admin/login", data={"password": password},
                    follow_redirects=False)
    assert r.status_code == 303, r.text
    panel = client.get(f"/r/{slug}/admin")
    assert panel.status_code == 200, panel.text
    return _csrf(panel.text)


def _dish(client, slug, token, name):
    r = client.post(f"/r/{slug}/admin/menu",
                    data={"csrf": token, "name": name, "category": "مشويات",
                          "description": "وجبة ساخنة", "price": "135.50"},
                    follow_redirects=False)
    assert r.status_code == 303, r.text
    rows = client.get(f"/r/{slug}/api/menu").json()["items"]
    return next(x for x in rows if x["name"] == name)["id"]


def _jpeg():
    out = io.BytesIO()
    Image.new("RGB", (1500, 1300), (231, 53, 31)).save(out, format="JPEG")
    return out.getvalue()


def test_two_restaurants_have_isolated_login_menu_photos_and_orders(tmp_path):
    with client_for(tmp_path) as client:
        owner = _admin_platform(client)
        _make_tenant(client, owner, "koshary-east", "كشري الشرق", "Password-for-east-789")
        _make_tenant(client, owner, "grill-west", "مشاوي الغرب", "Password-for-west-789")
        assert "كشري الشرق" in client.get("/restaurants").text
        assert "مشاوي الغرب" in client.get("/restaurants").text

        east_token = _tenant_login(client, "koshary-east", "Password-for-east-789")
        assert client.get("/r/grill-west/admin", follow_redirects=False).status_code == 303
        eid = _dish(client, "koshary-east", east_token, "فراخ على الفحم")
        assert client.get("/r/grill-west/api/menu").json()["items"] == []
        assert "فراخ على الفحم" in client.get("/r/koshary-east/api/menu").text

        # Wrong tenant session cannot use another tenant's item or photo path.
        rejected = client.post(f"/r/grill-west/admin/menu/{eid}/photo",
                               data={"csrf": east_token},
                               files={"photo": ("dish.jpg", _jpeg(), "image/jpeg")},
                               follow_redirects=False)
        assert rejected.status_code == 401
        rejected = client.post(f"/r/grill-west/admin/menu/{eid}",
                               data={"csrf": east_token, "name": "متلاعب",
                                     "category": "أخرى", "price": "1"})
        assert rejected.status_code == 401

        photo = client.post(f"/r/koshary-east/admin/menu/{eid}/photo",
                            data={"csrf": east_token},
                            files={"photo": ("meal.jpg", _jpeg(), "image/jpeg")},
                            follow_redirects=False)
        assert photo.status_code == 303, photo.text
        picture = client.get(f"/r/koshary-east/images/{eid}.webp")
        assert picture.status_code == 200
        assert picture.content[:4] == b"RIFF"
        assert picture.headers["content-type"] == "image/webp"
        with Image.open(io.BytesIO(picture.content)) as im:
            assert im.format == "WEBP"
            assert max(im.size) <= 1100

        assert client.get(f"/r/grill-west/images/{eid}.webp").status_code == 404
        result = client.get("/r/koshary-east/api/menu").json()
        assert result["items"][0]["has_photo"] is True
        assert result["items"][0]["photo_version"]
        assert f"/r/koshary-east/images/{eid}.webp" in client.get("/r/koshary-east").text

        chat = client.post("/r/koshary-east/api/chat", json={"message": "فراخ"}).json()
        assert chat["choices"] and chat["choices"][0]["id"] == eid
        assert client.post("/r/grill-west/api/chat", json={"message": "فراخ"}).json()["choices"] == []

        order = client.post("/r/koshary-east/api/orders", json={"table_no": 2,
                           "items": [{"id": eid, "quantity": 2}]})
        assert order.status_code == 200, order.text
        assert order.json()["demo_only"] is True
        assert order.json()["total_piasters"] == 27100
        assert client.post("/r/grill-west/api/orders", json={"table_no": 2,
                           "items": [{"id": eid, "quantity": 1}]}).status_code == 409

        _tenant_login(client, "grill-west", "Password-for-west-789")
        assert "فراخ على الفحم" not in client.get("/r/grill-west/admin").text
        assert "فراخ على الفحم" in client.get("/r/koshary-east/admin").text
        with sqlite3.connect(client.app.state.db_path) as db:
            assert db.execute("SELECT COUNT(*) FROM tenant_demo_orders").fetchone()[0] == 1
            assert db.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0


def test_photo_replace_delete_invalid_files_and_csrf(tmp_path):
    with client_for(tmp_path) as client:
        owner = _admin_platform(client)
        _make_tenant(client, owner, "cafe-green", "كافيه جرين", "Password-for-cafe-789")
        csrf = _tenant_login(client, "cafe-green", "Password-for-cafe-789")
        item = _dish(client, "cafe-green", csrf, "عصير مانجو")
        endpoint = f"/r/cafe-green/admin/menu/{item}/photo"

        assert client.post(endpoint, data={"csrf": "wrong"},
                           files={"photo": ("meal.jpg", _jpeg(), "image/jpeg")}).status_code == 403
        assert client.post(endpoint, data={"csrf": csrf},
                           files={"photo": ("script.svg", b'<svg><script/></svg>', "image/svg+xml")}).status_code in (415, 422)
        assert client.post(endpoint, data={"csrf": csrf},
                           files={"photo": ("huge.jpg", b"0" * (5 * 1024 * 1024 + 1),
                                            "image/jpeg")}).status_code == 413
        assert client.get(f"/r/cafe-green/images/{item}.webp").status_code == 404

        assert client.post(endpoint, data={"csrf": csrf},
                           files={"photo": ("one.jpg", _jpeg(), "image/jpeg")},
                           follow_redirects=False).status_code == 303
        original = client.get(f"/r/cafe-green/images/{item}.webp").content
        other = io.BytesIO()
        Image.new("RGB", (50, 70), (33, 91, 128)).save(other, format="PNG")
        assert client.post(endpoint, data={"csrf": csrf},
                           files={"photo": ("new.png", other.getvalue(), "image/png")},
                           follow_redirects=False).status_code == 303
        replaced = client.get(f"/r/cafe-green/images/{item}.webp").content
        assert replaced != original
        assert client.post(endpoint + "/delete", data={"csrf": csrf},
                           follow_redirects=False).status_code == 303
        assert client.get(f"/r/cafe-green/images/{item}.webp").status_code == 404
        assert client.get("/r/cafe-green/api/menu").json()["items"][0]["has_photo"] is False


def test_password_reset_invalidates_existing_restaurant_session(tmp_path):
    with client_for(tmp_path) as client:
        owner = _admin_platform(client)
        _make_tenant(client, owner, "cafe-rotation", "مقهى جديد", "Password-first-789")
        _tenant_login(client, "cafe-rotation", "Password-first-789")
        before = client.get("/r/cafe-rotation/admin")
        assert before.status_code == 200
        change = client.post("/admin/restaurants/cafe-rotation/reset-password",
                             data={"csrf": owner, "password": "Password-second-789"},
                             follow_redirects=False)
        assert change.status_code == 303
        assert client.get("/r/cafe-rotation/admin", follow_redirects=False).status_code == 303
        _tenant_login(client, "cafe-rotation", "Password-second-789")


def test_legacy_data_unchanged_by_new_tenant_platform(tmp_path):
    with client_for(tmp_path) as client:
        old = client.get("/api/menu").json()
        assert len(old["items"]) >= 9
        assert client.get("/r/unknown").status_code == 404
        assert client.get("/admin/restaurants", follow_redirects=False).status_code == 303
        assert client.get("/api/menu").json() == old
