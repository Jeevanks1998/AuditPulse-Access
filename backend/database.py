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
  - init_db()             creates tables from schema.sql (no demo data)
  - seed_default_roles()  creates the four system roles (+ their
                           permission rows) for a *new* org — used by
                           auth.py's /auth/signup
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
# roles, seeded per-organisation at signup.
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
    Returns {role_name: role_id}. Used by auth.py's /auth/signup, so
    every org starts from the same baseline permissions."""
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
    """Create tables if they don't exist yet (and apply the idempotent
    upgrades at the end of schema.sql). Safe to call every startup.

    Nothing is seeded: no demo organisation and no demo admin. The first
    organisation and its admin are created through signup.html
    (POST /api/auth/signup); that admin then sets up Google Authenticator
    on their first login.
    """
    with get_conn() as conn:
        conn.executescript(SCHEMA_PATH.read_text())
