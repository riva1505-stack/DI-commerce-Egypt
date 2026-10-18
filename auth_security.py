"""Password verification and revocable admin sessions for the SQLite pilot."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

SESSION_SECONDS = 8 * 60 * 60
LOGIN_WINDOW = 5 * 60
IP_LOGIN_LIMIT = 5
GLOBAL_LOGIN_LIMIT = 50
PASSWORD_ITERATIONS = 600_000
PREVIEW_SECRET = "local-preview-secret-change-before-deploy"


def hash_password(password: str) -> str:
    if not password or len(password.encode()) > 1024:
        raise ValueError("Password must contain 1 to 1024 UTF-8 bytes")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def parse_password_hash(encoded: str) -> tuple[int, bytes, bytes]:
    try:
        algorithm, iterations, salt, digest = encoded.split("$")
        if algorithm != "pbkdf2_sha256" or not iterations.isascii() or not iterations.isdigit():
            raise ValueError
        count = int(iterations)
        if not PASSWORD_ITERATIONS <= count <= 2_000_000:
            raise ValueError
        if not re.fullmatch(r"[0-9a-f]{32}", salt) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError
        return count, bytes.fromhex(salt), bytes.fromhex(digest)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("Invalid ADMIN_PASSWORD_HASH; generate it with python hash_admin_password.py") from exc


class AdminAuth:
    def __init__(self, db_path: Path, password_hash: str, credential_tag: str):
        self.db_path = db_path
        self.password_parameters = parse_password_hash(password_hash)
        self.credential_tag = credential_tag
        with self.database() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS admin_auth_config (
                    id INTEGER PRIMARY KEY CHECK(id=1), credential_tag TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS admin_sessions (
                    token_hash TEXT PRIMARY KEY, credential_tag TEXT NOT NULL,
                    expires_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_admin_sessions_expiry ON admin_sessions(expires_at);
                CREATE TABLE IF NOT EXISTS admin_login_limits (
                    bucket TEXT PRIMARY KEY, started_at INTEGER NOT NULL, attempts INTEGER NOT NULL
                );
            """)
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT credential_tag FROM admin_auth_config WHERE id=1").fetchone()
            if current is None or not hmac.compare_digest(current[0], credential_tag):
                db.execute("DELETE FROM admin_sessions")
                db.execute("INSERT OR REPLACE INTO admin_auth_config VALUES (1, ?)", (credential_tag,))
            db.commit()

    @contextmanager
    def database(self):
        db = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
        try:
            yield db
        finally:
            db.close()

    def password_matches(self, password: str) -> bool:
        if not password or len(password.encode()) > 1024:
            return False
        iterations, salt, expected = self.password_parameters
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
        return hmac.compare_digest(actual, expected)

    def reserve_login_attempt(self, ip: str) -> int:
        """Atomically count attempts across workers; return Retry-After or zero."""
        now = int(time.time())
        # Store no raw client addresses. A global bucket also caps IP rotation.
        ip_bucket = hmac.new(self.credential_tag.encode(), ip.encode(), hashlib.sha256).hexdigest()
        with self.database() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM admin_login_limits WHERE started_at<=?", (now - LOGIN_WINDOW,))
            buckets = (("global", GLOBAL_LOGIN_LIMIT), (ip_bucket, IP_LOGIN_LIMIT))
            retry = 0
            for bucket, limit in buckets:
                row = db.execute("SELECT started_at,attempts FROM admin_login_limits WHERE bucket=?", (bucket,)).fetchone()
                if row and row[1] >= limit:
                    retry = max(retry, row[0] + LOGIN_WINDOW - now)
            if not retry:
                for bucket, _ in buckets:
                    db.execute("""INSERT INTO admin_login_limits VALUES (?, ?, 1)
                        ON CONFLICT(bucket) DO UPDATE SET attempts=attempts+1""", (bucket, now))
            db.commit()
        return retry

    def create_session(self, previous_token: str | None = None) -> str | None:
        token = secrets.token_urlsafe(32)
        now = int(time.time())
        with self.database() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT credential_tag FROM admin_auth_config WHERE id=1").fetchone()
            if not current or not hmac.compare_digest(current[0], self.credential_tag):
                db.rollback()
                return None  # A worker with stale credentials may not issue new sessions.
            db.execute("DELETE FROM admin_sessions WHERE expires_at<=?", (now,))
            if isinstance(previous_token, str) and re.fullmatch(r"[A-Za-z0-9_-]{43}", previous_token):
                db.execute("DELETE FROM admin_sessions WHERE token_hash=? AND credential_tag=?",
                           (hashlib.sha256(previous_token.encode()).hexdigest(), self.credential_tag))
            db.execute("INSERT INTO admin_sessions VALUES (?, ?, ?)",
                       (hashlib.sha256(token.encode()).hexdigest(), self.credential_tag, now + SESSION_SECONDS))
            db.commit()
        return token

    def session_valid(self, token: str) -> bool:
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            return False
        with self.database() as db:
            row = db.execute("""SELECT 1 FROM admin_sessions s JOIN admin_auth_config c
                ON c.id=1 AND c.credential_tag=s.credential_tag
                WHERE s.token_hash=? AND s.credential_tag=? AND s.expires_at>?""",
                (hashlib.sha256(token.encode()).hexdigest(), self.credential_tag, int(time.time()))).fetchone()
        return row is not None

    def revoke_session(self, token: str):
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            return
        with self.database() as db:
            db.execute("DELETE FROM admin_sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))

