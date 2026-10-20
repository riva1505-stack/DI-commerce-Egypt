"""Tenant QR links: experimental, not installed on production."""


def qr_path(slug: str, table: int) -> str:
    return f"/r/{slug}?table={table}"
