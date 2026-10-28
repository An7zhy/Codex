"""Fail-closed, single-organization access boundary; no client tenant selection.

Provision accounts offline with scripts.manage_access. Opaque sessions are stored
hashed, expire after eight hours and are invalidated by account changes/logout.
The workspace and history databases must belong to the same provisioned instance.
"""

from contextlib import contextmanager
import hashlib
import hmac
import os
from pathlib import Path
import secrets
import sqlite3
import time
import uuid

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
COOKIE = "logistics_session"
ROLES = {"viewer": 0, "operator": 1, "admin": 2}


def paths():
    return (Path(os.environ.get("LOGISTICS_WEB_DB_PATH", ROOT / "data/local/web_workspace.sqlite3")),
            Path(os.environ.get("LOGISTICS_DB_PATH", ROOT / "data/local/exception_history.sqlite3")))


def password_hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=32768, r=8, p=1,
                          maxmem=64 * 1024 * 1024).hex()


class AccessStore:
    def __init__(self):
        self.path, self.history_path = paths()
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS instance_identity (id INTEGER PRIMARY KEY CHECK(id=1),
                    instance_id TEXT NOT NULL, organization TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS access_users (username TEXT PRIMARY KEY, salt TEXT NOT NULL,
                    password_hash TEXT NOT NULL, role TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS access_sessions (token_hash TEXT PRIMARY KEY,
                    username TEXT NOT NULL, expires_at REAL NOT NULL, instance_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS access_rates (bucket TEXT PRIMARY KEY, start REAL NOT NULL, count INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS access_events (event_id INTEGER PRIMARY KEY, occurred_at REAL NOT NULL,
                    actor TEXT NOT NULL, operation TEXT NOT NULL, target TEXT NOT NULL, status INTEGER NOT NULL);
            """)
        os.chmod(self.path, 0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def identity(self):
        with self.connect() as db:
            row = db.execute("SELECT * FROM instance_identity WHERE id=1").fetchone()
        if not row:
            raise HTTPException(503, "Instance not provisioned. Ask the administrator to run scripts.manage_access.")
        return dict(row)

    def check_binding(self):
        identity = self.identity()
        with sqlite3.connect(self.history_path, timeout=5) as db:
            row = db.execute("SELECT instance_id FROM instance_binding WHERE id=1").fetchone()
        if not row or row[0] != identity["instance_id"]:
            raise HTTPException(503, "Database instance identity mismatch. Administrator action required.")
        return identity

    def provision(self, organization):
        if not organization.strip() or len(organization) > 120:
            raise ValueError("Provide a nonblank organization name, at most 120 characters.")
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db, sqlite3.connect(self.history_path) as history:
            history.execute("CREATE TABLE IF NOT EXISTS instance_binding (id INTEGER PRIMARY KEY CHECK(id=1), instance_id TEXT NOT NULL)")
            prior = db.execute("SELECT * FROM instance_identity WHERE id=1").fetchone()
            bound = history.execute("SELECT instance_id FROM instance_binding WHERE id=1").fetchone()
            if prior and prior["organization"] != organization.strip():
                raise ValueError("This database already belongs to another organization. Use separate directories/instances.")
            instance_id = prior["instance_id"] if prior else uuid.uuid4().hex
            if bound and bound[0] != instance_id:
                raise ValueError("History database belongs to a different instance; refusing to rebind.")
            db.execute("INSERT OR IGNORE INTO instance_identity VALUES (1,?,?)", (instance_id, organization.strip()))
            history.execute("INSERT OR IGNORE INTO instance_binding VALUES (1,?)", (instance_id,))
        os.chmod(self.history_path, 0o600)
        return self.check_binding()

    def set_user(self, username, password, role):
        self.check_binding()
        if role not in ROLES or not username or len(username) > 100 or not username.isascii() or not all(c.isalnum() or c in "._-" for c in username):
            raise ValueError("Use an ASCII account name and viewer/operator/admin role.")
        if not 12 <= len(password) <= 256:
            raise ValueError("Passwords must contain 12–256 characters.")
        salt = secrets.token_hex(16)
        digest = password_hash(password, salt)
        with self.connect() as db:
            db.execute("INSERT INTO access_users VALUES (?,?,?,?,1) ON CONFLICT(username) DO UPDATE SET salt=excluded.salt,password_hash=excluded.password_hash,role=excluded.role,enabled=1", (username, salt, digest, role))
            db.execute("DELETE FROM access_sessions WHERE username=?", (username,))

    def disable_user(self, username):
        with self.connect() as db:
            db.execute("UPDATE access_users SET enabled=0 WHERE username=?", (username,))
            db.execute("DELETE FROM access_sessions WHERE username=?", (username,))

    def rate(self, bucket, maximum, window=60):
        now = time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM access_rates WHERE start<?", (now - max(window, 3600),))
            row = db.execute("SELECT * FROM access_rates WHERE bucket=?", (bucket,)).fetchone()
            count = row["count"] if row and row["start"] > now - window else 0
            if count >= maximum:
                raise HTTPException(429, "Request budget exceeded. Retry after the rate window.", headers={"Retry-After": str(window)})
            db.execute("INSERT INTO access_rates VALUES (?,?,?) ON CONFLICT(bucket) DO UPDATE SET start=excluded.start,count=excluded.count", (bucket, row["start"] if count else now, count + 1))

    def login(self, username, password):
        identity = self.check_binding()
        self.rate("login-global", 30)
        self.rate("login:" + hashlib.sha256(username.encode()).hexdigest(), 5, 300)
        with self.connect() as db:
            row = db.execute("SELECT * FROM access_users WHERE username=?", (username,)).fetchone()
        # Same expensive work and response for unknown/disabled users.
        digest = password_hash(password, row["salt"] if row else "00" * 16)
        if not row or not hmac.compare_digest(digest, row["password_hash"]) or not row["enabled"]:
            raise HTTPException(401, "Invalid account or password.")
        token = secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute("DELETE FROM access_sessions WHERE expires_at<=?", (time.time(),))
            db.execute("INSERT INTO access_sessions VALUES (?,?,?,?)", (self.digest(token), username, time.time() + 8 * 3600, identity["instance_id"]))
        return token

    @staticmethod
    def digest(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def authenticate(self, token):
        if not token:
            raise HTTPException(401, "Sign in to access this organization workspace.")
        with self.connect() as db:
            row = db.execute("SELECT u.username,u.role,s.instance_id FROM access_sessions s JOIN access_users u ON s.username=u.username WHERE token_hash=? AND expires_at>? AND enabled=1", (self.digest(token), time.time())).fetchone()
        if not row:
            raise HTTPException(401, "Session expired or invalid. Sign in again.")
        identity = self.check_binding()
        if row["instance_id"] != identity["instance_id"]:
            raise HTTPException(401, "Session does not belong to this instance.")
        return {"username": row["username"], "role": row["role"], "organization": identity["organization"], "instance_id": identity["instance_id"]}

    def logout(self, token):
        with self.connect() as db:
            db.execute("DELETE FROM access_sessions WHERE token_hash=?", (self.digest(token or ""),))

    def event(self, actor, operation, target, status):
        # Metadata only: never passwords, tokens, body/query contents or raw uploads.
        with self.connect() as db:
            db.execute("INSERT INTO access_events VALUES (NULL,?,?,?,?,?)", (time.time(), actor, operation, target[:300], status))
            db.execute("DELETE FROM access_events WHERE occurred_at<? OR event_id NOT IN (SELECT event_id FROM access_events ORDER BY event_id DESC LIMIT 10000)", (time.time() - 90 * 86400,))


def required_role(method, path):
    if method in {"GET", "HEAD", "OPTIONS"} or path in {"/api/auth/logout", "/api/decisions/compare"}:
        return "viewer"
    if path.startswith("/api/settings") or method == "DELETE" or path.startswith("/api/maintenance"):
        return "admin"
    return "operator"
