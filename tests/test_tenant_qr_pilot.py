from tenant_qr_pilot import qr_path, qr_target


def test_qr_tenant_scoped_and_https():
    assert qr_path('cafe-east', 2, 3) == '/r/cafe-east?table=2'
    assert qr_path('cafe-east', 2, 3) != qr_path('cafe-west', 2, 3)
    assert qr_target('https://example.org', 'cafe-east', 2, 3) == 'https://example.org/r/cafe-east?table=2'


def test_qr_invalid_values():
    import pytest
    for slug, table, count in [('cafe-east', 4, 3), ('../admin', 1, 3), ('cafe-east', 0, 3)]:
        with pytest.raises(ValueError):
            qr_path(slug, table, count)
    with pytest.raises(ValueError):
        qr_target('http://example.org', 'cafe-east', 1)
