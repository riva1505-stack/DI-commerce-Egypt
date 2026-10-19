"""Separate tenant schema. Feature branch only; no live migration."""
import sqlite3
from contextlib import contextmanager

@contextmanager
def database(path):
    db = sqlite3.connect(path, timeout=10, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
    finally:
        db.close()

def bootstrap(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with database(path) as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS di_tenants (
          id INTEGER PRIMARY KEY,
          slug TEXT NOT NULL UNIQUE,
          name TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'draft',
          prices_approved INTEGER NOT NULL DEFAULT 0,
          checkout_enabled INTEGER NOT NULL DEFAULT 0,
          table_count INTEGER NOT NULL DEFAULT 20
        );
        CREATE TABLE IF NOT EXISTS di_managers (
          id INTEGER PRIMARY KEY,
          tenant_id INTEGER NOT NULL REFERENCES di_tenants(id),
          username TEXT NOT NULL,
          password_hash TEXT NOT NULL,
          UNIQUE(tenant_id,username)
        );
        CREATE TABLE IF NOT EXISTS di_sessions (
          token_hash TEXT PRIMARY KEY,
          tenant_id INTEGER NOT NULL,
          manager_id INTEGER NOT NULL REFERENCES di_managers(id),
          expires_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS di_menu_items (
          id INTEGER PRIMARY KEY,
          tenant_id INTEGER NOT NULL REFERENCES di_tenants(id),
          name TEXT NOT NULL,
          category TEXT NOT NULL,
          price_piasters INTEGER NOT NULL CHECK(price_piasters BETWEEN 0 AND 10000000),
          available INTEGER NOT NULL DEFAULT 1,
          price_confirmed INTEGER NOT NULL DEFAULT 0,
          UNIQUE(tenant_id,id)
        );
        """)
