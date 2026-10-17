# Admin authentication and deployment

The application still has one shared restaurant administrator identity. This change hardens that login; it does not add separate employee accounts or a multi-restaurant permission model.

## Configure a deployment

1. Run `python hash_admin_password.py` locally. Enter a unique password of at least 12 characters (a long random password or passphrase is recommended). Input is hidden and does not enter command history. Copy the generated `ADMIN_PASSWORD_HASH` into the hosting secret settings, then remove `ADMIN_PASSWORD` there. Treat the hash as sensitive configuration too.
2. Generate `SECRET_KEY` with `python -c "import secrets; print(secrets.token_urlsafe(48))"` and store it in hosting secrets. Production rejects missing, short, and known-preview signing keys. Keep the same random key across restarts unless intentionally revoking sessions.
3. Set `APP_ENV=production`, `DATABASE_PATH` on a persistent volume, and `PUBLIC_BASE_URL` to the real HTTPS origin (or use Railway's supplied public domain). The Docker image defaults to production and will refuse to start without valid credentials. `start.py` is only for local development and loads `.env`; Docker/direct Uvicorn use host environment variables.
4. Terminate TLS at a trusted proxy and prevent direct public access to the application port. The container no longer trusts every forwarded IP address. Set Uvicorn's `FORWARDED_ALLOW_IPS` to the actual trusted proxy addresses/networks as required by your host; do not use `*` on a directly reachable service. Without this configuration requests may share the proxy's login-rate bucket. The configured HTTPS origin is accepted for login Origin checks even when the internal connection uses HTTP.

For compatibility, `ADMIN_PASSWORD` still works, but production requires at least 12 characters after trimming padding; empty and over-1024-byte passwords are rejected. It is converted to a salted PBKDF2-SHA256 verifier at startup and is not kept in application state. The original plaintext remains in the process environment if configured there; use `ADMIN_PASSWORD_HASH` and remove the plaintext value to avoid that. A nonempty hash takes precedence over the environment password. The helper enforces the minimum password length; an existing encoded hash cannot reveal whether its original password met a length policy.

Hashes use PBKDF2-HMAC-SHA256, 600,000 iterations, a random 16-byte salt, and a 32-byte derived key. Malformed hashes and iteration counts outside 600,000–2,000,000 fail startup. Do not lower the work factor for deployment.

## Session lifecycle

Login creates a random 32-byte session identifier. Its SHA-256 digest, credential tag, and eight-hour expiration are stored in a private SQLite `admin_sessions` table. The browser receives a signed HttpOnly cookie containing the session identifier and admin role. Cookies use SameSite=Lax and Secure in production. Every admin request checks both signature age and the database record. Legacy role-only cookies are rejected.

Logout requires a valid session and CSRF token, deletes the session record, and clears the browser cookie. A copied cookie can no longer be replayed. Other logged-in sessions remain active.

Restarting with the same credentials and signing key preserves valid sessions. Changing either configuration invalidates all old sessions when the updated app starts. Older running workers cannot authenticate or issue sessions against the new database credential tag. Restart all workers with consistent configuration; running incompatible configurations against one database is unsupported and can cause repeated invalidation. There is no refresh token or sliding extension.

The schema additions are additive: `admin_auth_config`, `admin_sessions`, and `admin_login_limits`. Existing order/menu tables and data are preserved. Back up the database before deployment. All workers must use the same SQLite database; separate replicas/databases do not share revocation or rate limits. The pilot remains intended for one container with a persistent SQLite volume.

## Login limits and CSRF

SQLite atomically counts login attempts across workers: at most 5 per client IP and 50 across the application per fixed five-minute window. Attempts include successful logins, so repeatedly signing in can temporarily hit the limit. Rejected attempts return HTTP 429 with Retry-After and do not extend the window. The global limit caps attempts across rotating client addresses, but can temporarily block legitimate logins during an attack. Existing authenticated sessions continue working. Expired buckets are pruned, and raw IP addresses are not stored. Use upstream limits and monitoring for public deployments too.

Cross-origin/opaque-Origin login requests and Sec-Fetch-Site: cross-site are rejected. Requests without these browser headers remain compatible with non-browser clients; there is no pre-login CSRF token. All authenticated state-changing admin forms continue to require a session-bound HMAC CSRF token. Invalid Unicode CSRF and tracking-token input is rejected without a server error.

## What remains outside this change

- Individual accounts, MFA, password recovery, role-specific permissions and audit-event logging.
- Order-tracking token expiry/hashing, query-string transmission, and idempotency-key ownership binding.
- Public order-spam prevention and centrally shared chat/voice budgets.
- Verification of the actual host's TLS, proxy filtering, secret configuration, backups and monitoring.
- Full dependency vulnerability scanning and live penetration testing.

`DI2.zip` is preserved as the original archive and does **not** contain these fixes. Deploy the current source files, not that ZIP. The original authentication review describes the extraction commit, not the hardened revision.
