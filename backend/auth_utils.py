"""
auth_utils.py

Shared plumbing for every Phase 5 auth-aware router (auth.py, mfa.py,
sso.py, users.py, roles.py, teams.py, organisations.py, access_logs.py).
Nothing in here is a route itself — it's the password hashing, JWT
issuing/decoding, and the two FastAPI dependencies (get_current_user,
require_admin) everything else builds on.

Two token types share one JWT shape ({sub, org_id, typ, exp}):
  - "access" — a normal session, returned by /auth/login, /auth/signup,
    /auth/mfa/verify, and sso.py's callback. get_current_user only
    accepts this type, so an mfa_token can't be replayed as a session.
  - "mfa"    — a short-lived, single-purpose token proving "this login
    attempt matched a password", exchanged by /auth/mfa/verify for a
    real access token once the caller also proves they hold the
    authenticator. See auth.py's login()/verify_login_mfa().

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
from passlib.context import CryptContext

from database import get_conn

SECRET_KEY = os.getenv("PORTAL_JWT_SECRET", "dev-only-insecure-secret-change-me")
ALGORITHM = "HS256"
ACCESS_TOKEN_TTL_SECONDS = int(os.getenv("PORTAL_ACCESS_TOKEN_TTL", str(60 * 60 * 24 * 7)))  # 7 days
MFA_TOKEN_TTL_SECONDS = 5 * 60  # long enough to type a 6-digit code, no longer

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer(auto_error=False)


# ------------------------------- passwords -------------------------------- #

def hash_password(raw: str) -> str:
    return pwd_context.hash(raw)


def verify_password(raw: str, hashed: Optional[str]) -> bool:
    if not hashed:
        return False
    try:
        return pwd_context.verify(raw, hashed)
    except Exception:
        return False


# --------------------------------- tokens ---------------------------------- #

def _issue(user_id: int, org_id: int, typ: str, ttl_seconds: int) -> str:
    payload = {
        "sub": str(user_id),
        "org_id": org_id,
        "typ": typ,
        "iat": int(time.time()),
        "exp": int(time.time()) + ttl_seconds,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_access_token(user_id: int, org_id: int) -> str:
    return _issue(user_id, org_id, "access", ACCESS_TOKEN_TTL_SECONDS)


def create_mfa_token(user_id: int, org_id: int) -> str:
    return _issue(user_id, org_id, "mfa", MFA_TOKEN_TTL_SECONDS)


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
    return row


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if not user["role_is_admin"]:
        raise HTTPException(status_code=403, detail="Admin permissions are required for this action.")
    return user


def role_permissions(role_id: int) -> dict:
    with get_conn() as conn:
        rows = conn.execute("SELECT module, allowed FROM permissions WHERE role_id = ?", (role_id,)).fetchall()
    return {r["module"]: bool(r["allowed"]) for r in rows}
