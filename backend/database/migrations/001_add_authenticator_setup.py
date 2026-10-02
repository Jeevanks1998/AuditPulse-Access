"""
001_add_authenticator_setup.py

Moves sign-in from email + password to email -> Google Authenticator.

  users.auth_setup_required   1 = next login shows the QR setup screen

You normally do NOT need to run this by hand: backend/database/schema.sql
contains the same idempotent ALTER/UPDATE and runs on every startup
(database.init_db()), so a Railway deploy upgrades the database by itself.
This script exists for running the change manually ahead of a deploy:

    cd backend
    DATABASE_URL=postgresql://... python database/migrations/001_add_authenticator_setup.py

Safe to run more than once.
"""

import os
import sys

import psycopg2

STATEMENTS = [
    # New column. Every existing user must set up the authenticator...
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_setup_required INTEGER NOT NULL DEFAULT 1",
    # ...except anyone who already enabled MFA under the old flow.
    """UPDATE users SET auth_setup_required = 0
        WHERE mfa_enabled = 1 AND mfa_secret IS NOT NULL AND auth_setup_required = 1""",
    # Passwords are no longer used; make sure the column can be empty.
    "ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL",
]


def main() -> int:
    url = os.getenv("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set.", file=sys.stderr)
        return 1
    conn = psycopg2.connect(url)
    try:
        with conn, conn.cursor() as cur:
            for sql in STATEMENTS:
                cur.execute(sql)
            cur.execute("SELECT COUNT(*) FROM users WHERE auth_setup_required = 1")
            pending = cur.fetchone()[0]
        print(f"Done. {pending} user(s) will set up Google Authenticator at their next login.")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
