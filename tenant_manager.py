"""Tenant manager helpers, isolated from platform administrator sessions."""
from tenant_db import database

def manager_lookup(db, tenant_id, username):
    return db.execute(
        "SELECT id,tenant_id,username,password_hash FROM di_managers "
        "WHERE tenant_id=? AND username=?", (tenant_id, username)).fetchone()
