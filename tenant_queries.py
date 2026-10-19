"""Tenant-qualified menu reads; never fall back to a global menu."""
def menu(db, tenant_id, *, all_items=False):
    where = "" if all_items else "AND available=1 "
    return [dict(row) for row in db.execute(
        "SELECT id,name,category,price_piasters,available,price_confirmed "
        "FROM di_menu_items WHERE tenant_id=? " + where + "ORDER BY id", (tenant_id,))]
