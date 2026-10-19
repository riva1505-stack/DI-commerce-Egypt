"""Isolation regression tests; run only against temporary SQLite."""
import sqlite3
import pytest
from tenant_db import bootstrap, database

def test_tenant_defaults_and_cross_tenant_manager_session(tmp_path):
    path = tmp_path / "tenants.db"
    bootstrap(path)
    with database(path) as db:
        db.execute("INSERT INTO di_tenants(slug,name) VALUES ('alpha','Alpha')")
        db.execute("INSERT INTO di_tenants(slug,name) VALUES ('bravo','Bravo')")
        rows = db.execute("SELECT * FROM di_tenants ORDER BY id").fetchall()
        assert len(rows) == 2
        assert all(r["checkout_enabled"] == 0 and r["prices_approved"] == 0 for r in rows)
        db.execute("INSERT INTO di_managers(tenant_id,username,password_hash) VALUES (1,'a','hash')")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO di_sessions(token_hash,tenant_id,manager_id,expires_at) "
                       "VALUES ('token',2,1,9999999999)")
