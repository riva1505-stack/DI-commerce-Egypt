"""Unit tests for the experimental per-restaurant QR target builder.

No QR endpoint or checkout is activated by these tests.
"""
import pytest

from tenant_qr_pilot import qr_path, qr_target


def test_restaurants_get_distinct_table_links():
    assert qr_path("cafe-east", 2, 4) == "/r/cafe-east?table=2"
    assert qr_path("cafe-west", 2, 4) != qr_path("cafe-east", 2, 4)
    assert qr_target("https://example.org", "cafe-east", 2, 4) == (
        "https://example.org/r/cafe-east?table=2"
    )


@pytest.mark.parametrize("slug,table,count", [
    ("../admin", 1, 20),
    ("Cafe-West", 1, 20),
    ("cafe-west", 0, 20),
    ("cafe-west", 21, 20),
    ("cafe-west", 1, 0),
    ("cafe-west", 1, 501),
])
def test_invalid_slug_or_table_fails_closed(slug, table, count):
    with pytest.raises(ValueError):
        qr_path(slug, table, count)


@pytest.mark.parametrize("origin", [
    "http://example.org",
    "https://example.org/tenant",
    "https://example.org/?a=1",
    "https://user:password@example.org",
    "https://example.org#fragment",
    "https://example.org:8080",
    "//example.org",
])
def test_untrusted_origins_cannot_be_encoded(origin):
    with pytest.raises(ValueError):
        qr_target(origin, "cafe-east", 1, 20)


def test_https_default_port_allowed():
    assert qr_target("https://example.org:443", "cafe-east", 1, 20) == (
        "https://example.org:443/r/cafe-east?table=1"
    )
