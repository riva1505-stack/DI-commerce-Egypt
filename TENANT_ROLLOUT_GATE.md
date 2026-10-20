# DI Commerce Egypt — tenant rollout gate (2026-10-20)

This branch is **not approved for production rollout**. It fixes packaging only; it does not authorize restaurant checkout or external messaging.

## Verified code boundaries
- Restaurant menus, photos and demo orders use tenant_id filters in restaurant_tenants.py.
- Manager cookies are scoped to /r/<slug> and signed with a per-slug salt.
- The separate Bokharest catalogue remains 104 entries, preview-only.
- Bokharest checkout requires both restaurant approval and separate server flags; keep those flags disabled.
- Trial WhatsApp notifications exist in bokharest_demo.py but require private Meta credentials; never publish credentials or recipient numbers.
- Prices are unconfirmed by the restaurant. The source pages list 12% service charge and 14% VAT; receipt calculations need restaurant confirmation.

## Required before activating multiple restaurants
1. Pass Python tests and the Docker runtime-import packaging tests in GitHub Actions.
2. Review manager logout token replay: clearing the browser cookie alone does not revoke a captured signed token; implement server-side session revocation and tests.
3. Implement per-restaurant table QR URLs and validate table ownership, allowed table range and cross-tenant access.
4. Add origin protection and login-CSRF review for manager login, plus session rate-limit tests.
5. Confirm tenant-scoped order idempotency, database backup/restore and audit logging.
6. Require a separate, explicit sandbox notification switch and a Meta test recipient before any WhatsApp send.
7. Confirm all Bokharest menu entries and tax/service-charge semantics with the restaurant; do not enable checkout until written approval.
8. Require explicit user approval for merge and Railway deployment. Do not use automatic merges.

## Deployment blocker
Railway's 2026-10-20 deployment for main d4ec6b9 failed its /health check because Dockerfile did not copy bokharest_showcase.py or restaurant_tenants.py into the image. This branch adds both files to the Dockerfile COPY list and regression tests. The last successful Railway deployment remains on the previous commit until a separately approved fix is deployed.
