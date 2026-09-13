"""
database.py

Talks to a Postgres database (e.g. Supabase) via psycopg2. Originally this
was stdlib sqlite3 with a single on-disk file; it's now a thin compatibility
layer over psycopg2 so the rest of the codebase — which was written against
sqlite3's `?` placeholders, `cur.lastrowid`, and dict-style rows — keeps
working unmodified. See PGConnection below for how that translation works.

Set DATABASE_URL to your Postgres connection string (Supabase: Project
Settings > Database > Connection string > URI — use the "Transaction"
pooler URI on port 6543 for serverless-style connections, or the direct
5432 URI). Example:
  postgresql://postgres.xxxxxxxx:[email protected]:6543/postgres

Exposes:
  - get_conn()            a connection wrapper with sqlite3-like row access
  - init_db()             creates tables from schema.sql, and on a totally
                           empty database seeds one demo organisation so
                           local dev isn't staring at an empty login page
  - seed_default_roles()  creates the four system roles (+ their
                           permission rows) for a *new* org — used here
                           for the demo org, and by auth.py's /auth/signup
                           for every org a real user creates afterwards
"""

import os
import re
from contextlib import contextmanager
from pathlib import Path

import psycopg2
import psycopg2.extras

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. Point it at your Supabase Postgres "
        "connection string (Project Settings > Database > Connection string)."
    )

SCHEMA_PATH = Path(__file__).parent / "database" / "schema.sql"

MODULES = ("dashboard", "audits", "analytics", "reports", "scheduler", "settings")

# (name, description, is_admin, permissions) — the four fixed Phase 1
# roles, now seeded per-organisation instead of once globally.
DEFAULT_ROLES = [
    ("Admin", "Full AuditPulse access", 1, {m: True for m in MODULES}),
    ("Auditor", "Create and perform audits", 0, {
        "dashboard": True, "audits": True, "analytics": True,
        "reports": True, "scheduler": True, "settings": False,
    }),
    ("Reviewer", "Review audit results", 0, {
        "dashboard": True, "audits": True, "analytics": True,
        "reports": True, "scheduler": False, "settings": False,
    }),
    ("Viewer", "View reports and dashboards", 0, {
        "dashboard": True, "audits": False, "analytics": True,
        "reports": True, "scheduler": False, "settings": False,
    }),
]


class _Cursor:
    """Wraps a psycopg2 cursor so callers can keep using sqlite3-style
    `cur.lastrowid` after an INSERT."""

    def __init__(self, pg_cursor):
        self._cur = pg_cursor
        self.lastrowid = None

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()


class PGConnection:
    """Translates the sqlite3-flavoured calls used throughout this codebase
    (`?` placeholders, `executescript`, `cur.lastrowid`) into psycopg2 calls,
    so users.py/roles.py/teams.py/etc. didn't need to be rewritten."""

    def __init__(self, pg_conn):
        self._conn = pg_conn

    def execute(self, sql, params=()):
        pg_sql = sql.replace("?", "%s")
        upper = pg_sql.strip().upper()
        add_returning = False

        if upper.startswith("INSERT OR IGNORE"):
            # sqlite3's "insert, skip if it already exists" — team_members
            # has no `id` column, so no RETURNING here.
            pg_sql = re.sub(r"(?i)^\s*INSERT OR IGNORE INTO", "INSERT INTO", pg_sql)
            pg_sql = pg_sql.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
        elif upper.startswith("INSERT") and "RETURNING" not in upper:
            # Every other INSERT target in this schema has an `id` primary
            # key, and callers expect cur.lastrowid to be set afterwards.
            pg_sql = pg_sql.rstrip().rstrip(";") + " RETURNING id"
            add_returning = True

        cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(pg_sql, params)
        wrapped = _Cursor(cur)
        if add_returning:
            row = cur.fetchone()
            wrapped.lastrowid = row["id"] if row else None
        return wrapped

    def executemany(self, sql, seq_of_params):
        pg_sql = sql.replace("?", "%s")
        cur = self._conn.cursor()
        cur.executemany(pg_sql, list(seq_of_params))
        return _Cursor(cur)

    def executescript(self, sql):
        cur = self._conn.cursor()
        cur.execute(sql)
        cur.close()

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


@contextmanager
def get_conn():
    """Request-scoped Postgres connection. Commits on clean exit, rolls back
    on any exception, always closes."""
    pg_conn = psycopg2.connect(DATABASE_URL)
    conn = PGConnection(pg_conn)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def seed_default_roles(conn, org_id: int) -> dict:
    """Creates the four system roles + their permission rows for `org_id`.
    Returns {role_name: role_id}. Shared by the dev bootstrap below and
    by auth.py's /auth/signup, so every org — demo or real — starts from
    the exact same baseline permissions."""
    role_ids = {}
    for name, description, is_admin, perms in DEFAULT_ROLES:
        cur = conn.execute(
            "INSERT INTO roles (org_id, name, description, is_system, is_admin) VALUES (?, ?, ?, 1, ?)",
            (org_id, name, description, is_admin),
        )
        role_id = cur.lastrowid
        role_ids[name] = role_id
        conn.executemany(
            "INSERT INTO permissions (role_id, module, allowed) VALUES (?, ?, ?)",
            [(role_id, m, int(v)) for m, v in perms.items()],
        )
    return role_ids


def init_db() -> None:
    """Create tables if they don't exist yet, then — only on a totally
    fresh database — seed one demo organisation with the four roles and
    five demo users, so local dev has something to look at immediately.
    Safe to call every startup; the seed only fires when organisations
    is empty."""
    with get_conn() as conn:
        conn.executescript(SCHEMA_PATH.read_text())

        org_count = conn.execute("SELECT COUNT(*) AS c FROM organisations").fetchone()["c"]
        if org_count > 0:
            return

        # Local import to avoid a database.py <-> auth_utils.py import
        # cycle (auth_utils imports get_conn from here).
        from auth_utils import hash_password

        cur = conn.execute(
            "INSERT INTO organisations (name, slug) VALUES (?, ?)", ("Demo Organisation", "demo")
        )
        org_id = cur.lastrowid
        role_ids = seed_default_roles(conn, org_id)

        demo_password = "ChangeMe123!"
        demo_users = [
            ("John Smith", "john@abc.com", role_ids["Admin"], "Active", 1),
            ("Sarah Lee", "sarah@abc.com", role_ids["Auditor"], "Active", 1),
            ("Mike Jones", "mike@abc.com", role_ids["Viewer"], "Pending", 0),
            ("Priya Nair", "priya@abc.com", role_ids["Reviewer"], "Active", 1),
            ("Alex Chen", "alex@abc.com", role_ids["Auditor"], "Active", 1),
        ]
        conn.executemany(
            """INSERT INTO users (org_id, name, email, role_id, status, auditpulse_access, password_hash, must_change_password)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
            [(org_id, name, email, role_id, status, access, hash_password(demo_password))
             for name, email, role_id, status, access in demo_users],
        )

    print("=" * 72)
    print("Seeded a fresh demo organisation:")
    print("  Organisation URL slug : demo")
    print("  Sign in as            : john@abc.com (Admin)")
    print(f"  Temporary password    : {demo_password}  (change on first login)")
    print("=" * 72)
