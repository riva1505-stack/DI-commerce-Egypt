# Tenant security rollout gate (not approved for production)

Current production is still a demo. This branch must not enable real restaurant checkout,
real WhatsApp sends, or modify the independent Bokharest preview.

## Verified starting point (2026-10-20)

- Main branch contains tenant demo menus, photos, separate manager login, and demo orders.
- Existing tenant manager cookies are signed and bound to the tenant password hash,
  but there is no server-side revocable manager session record. Logging out only
  removes the browser cookie, so a copied cookie could remain valid until expiry.
- Tenant demo orders are scoped by tenant ID, but retries have no idempotency key.
- Demo order table numbers accept 1..500 regardless of a restaurant's actual table count.
- Tenant QR URL helper exists only in a feature branch and is not a live endpoint.
- WhatsApp recipient policy exists only in the sandbox feature branch; no real send
  is authorized.
- Bokharest's existing menu data is deliberately untouched.

## Required before production review

1. Create a durable tenant-bound session store with random session IDs stored only
   as hashes; check tenant, expiry and revocation on every manager request.
   Revoke the current session on logout and all tenant sessions on password reset.
   Test stolen-cookie replay after logout, cross-tenant use and expiry.
2. Persist table_count per restaurant (1..500), enforce it when accepting demo
   orders and building QR links, and render QR only for an HTTPS public origin.
3. Make demo order retries idempotent with a per-tenant unique key and a
   canonical request fingerprint. Same key + same request returns the original
   result; same key + changed request returns 409. Keep prices server-authoritative.
4. Keep WhatsApp disabled by default. Require an explicit opt-in flag and a
   verified, exact E.164-format test recipient before any sandbox call.
   Do not implement a live send path without a separate approval.
5. Confirm Bokharest prices with the restaurant and document whether the
   12% service charge and 14% VAT are inclusive or additive, including rounding.
   Until then, no real checkout and no real order forwarding.
6. Run tenant A/B isolation, CSRF, session replay, idempotency concurrency,
   table boundary and QR origin tests. Review and approve any merge separately.

## Existing QR helper

The experimental QR target validation is under tenant_qr_pilot.py and its
unit tests are under tests/test_tenant_qr_pilot.py. This branch does not
register any QR route and cannot alter production behavior.
