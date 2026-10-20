from tenant_qr_pilot import qr_path, qr_target
from whatsapp_trial_policy import sandbox_ready


def check_qr_path():
    assert qr_path('cafe-east', 2) == '/r/cafe-east?table=2'


def check_restaurant_isolation():
    assert qr_path("cafe-west", 2) != qr_path("cafe-east", 2)


def check_invalid_table():
    try:
        qr_path("cafe-east", 21)
    except ValueError:
        return
    raise AssertionError("QR accepted table outside configured range")


def check_https_and_sandbox():
    assert qr_target("https://example.org", "cafe-east", 2) == "https://example.org/r/cafe-east?table=2"
    assert not sandbox_ready(False, "201000000000", "201000000000")
    assert not sandbox_ready(True, "201000000000", "201000000001")
