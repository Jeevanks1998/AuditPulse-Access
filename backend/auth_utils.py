"""
auth_utils.py

Shared plumbing for every Phase 5 auth-aware router (auth.py, mfa.py,
sso.py, users.py, roles.py, teams.py, organisations.py, access_logs.py).
Nothing in here is a route itself — it's JWT issuing/decoding and the
two FastAPI dependencies (get_current_user, require_admin) everything
else builds on. There are no passwords any more: sign-in is email ->
Google Authenticator (see auth.py / mfa.py).

Token types share one JWT shape ({sub, org_id, typ, exp, amr}):
  - "access"    — a real session, returned by /auth/mfa/verify (after a
    correct authenticator code) and sso.py's callback. get_current_user
    only accepts this type.
  - "mfa"       — short-lived challenge from /auth/login for a user whose
    authenticator is already set up; exchanged by /auth/mfa/verify.
  - "mfa_setup" — same, for first-time setup (or after an admin reset);
    a correct code also marks the authenticator as configured.

`amr` records how an access token was obtained ("totp" or "sso"). A
"totp" session stops working as soon as an admin resets that person's
authenticator.

PORTAL_JWT_SECRET should be set in backend/.env for anything beyond a
laptop demo — see .env.example. Falling back to a fixed dev string (like
below) rather than refusing to start keeps `uvicorn main:app --reload`
working out of the box; it is not a production default.
"""

import os
import time
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from database import get_conn

SECRET_KEY = os.getenv("PORTAL_JWT_SECRET", "dev-only-insecure-secret-change-me")
ALGORITHM = "HS256"
ACCESS_TOKEN_TTL_SECONDS = int(os.getenv("PORTAL_ACCESS_TOKEN_TTL", str(60 * 60 * 24 * 7)))  # 7 days
# Challenge lifetimes: long enough to type a code (or, for setup, to
# install the app and scan the QR code), no longer.
CHALLENGE_TTL_SECONDS = {"mfa": 5 * 60, "mfa_setup": 15 * 60}

bearer_scheme = HTTPBearer(auto_error=False)


# --------------------------------- tokens ---------------------------------- #

def _issue(user_id: int, org_id: int, typ: str, ttl_seconds: int, amr: Optional[str] = None) -> str:
    payload = {
        "sub": str(user_id),
        "org_id": org_id,
        "typ": typ,
        "iat": int(time.time()),
        "exp": int(time.time()) + ttl_seconds,
    }
    if amr:
        payload["amr"] = amr
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_access_token(user_id: int, org_id: int, amr: str = "sso") -> str:
    return _issue(user_id, org_id, "access", ACCESS_TOKEN_TTL_SECONDS, amr=amr)


def create_challenge_token(user_id: int, org_id: int, typ: str) -> str:
    """typ = "mfa" (code only) or "mfa_setup" (QR setup + code)."""
    return _issue(user_id, org_id, typ, CHALLENGE_TTL_SECONDS[typ])


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired — please sign in again.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid session token.")


# ----------------------------- FastAPI dependencies ------------------------ #

USER_WITH_ROLE_SELECT = """
    SELECT users.*, roles.name AS role_name, roles.is_admin AS role_is_admin
    FROM users JOIN roles ON roles.id = users.role_id
"""


def get_current_user(creds: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme)) -> dict:
    if not creds or not creds.credentials:
        raise HTTPException(status_code=401, detail="Sign in required.")

    decoded = decode_token(creds.credentials)
    if decoded.get("typ") != "access":
        raise HTTPException(status_code=401, detail="Invalid session token.")

    user_id = int(decoded["sub"])
    with get_conn() as conn:
        row = conn.execute(USER_WITH_ROLE_SELECT + " WHERE users.id = ?", (user_id,)).fetchone()

    if not row:
        raise HTTPException(status_code=401, detail="Account no longer exists.")
    if row["status"] == "Disabled":
        raise HTTPException(status_code=403, detail="This account's access has been disabled.")
    if decoded.get("amr") != "sso" and (row["auth_setup_required"] or not row["mfa_enabled"]):
        # An admin reset this person's authenticator after the session was
        # issued (or it's a pre-authenticator session) — sign in again.
        raise HTTPException(status_code=401, detail="Your authenticator was reset. Please sign in again.")
    return row


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if not user["role_is_admin"]:
        raise HTTPException(status_code=403, detail="Admin permissions are required for this action.")
    return user


def role_permissions(role_id: int) -> dict:
    with get_conn() as conn:
        rows = conn.execute("SELECT module, allowed FROM permissions WHERE role_id = ?", (role_id,)).fetchall()
    return {r["module"]: bool(r["allowed"]) for r in rows}
