from tenant_qr_pilot import qr_path


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
