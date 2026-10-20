"""Safe tenant table QR URL builder; experimental until integrated."""
import re
from urllib.parse import urlsplit

SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,45}[a-z0-9])?$")


def qr_path(slug: str, table: int, table_count: int = 20) -> str:
    if not SLUG.fullmatch(slug) or not 1 <= table <= table_count <= 500:
        raise ValueError("Invalid restaurant or table")
    return f"/r/{slug}?table={table}"


def qr_target(base_url: str, slug: str, table: int, table_count: int = 20) -> str:
    parsed = urlsplit(base_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("HTTPS public domain required")
    return base_url.rstrip("/") + qr_path(slug, table, table_count)
