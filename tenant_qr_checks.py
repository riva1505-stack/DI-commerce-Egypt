from tenant_qr_pilot import qr_path


def check_qr_path():
    assert qr_path('cafe-east', 2) == '/r/cafe-east?table=2'
