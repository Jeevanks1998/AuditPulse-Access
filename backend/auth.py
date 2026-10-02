"""
auth.py

Portal auth. Sign-in is email -> Google Authenticator; there are no
passwords.

  1. POST /api/auth/signup — bootstraps a brand new organisation with its
     four default roles and one Admin user (no password). The new admin
     then goes through the normal login below, which shows the QR setup.
  2. POST /api/auth/login  — org slug + email. The org slug disambiguates
     two orgs that reuse the same email. Returns which screen to show:
        step "setup"  first login / admin reset -> QR code + manual key
        step "verify" authenticator already paired -> ask for the code
     plus a short-lived mfa_token (a challenge, NOT a session).
  3. POST /api/auth/mfa/verify — mfa_token + 6-digit code -> session.
     For a setup challenge, a correct code also marks the authenticator
     as configured (mfa_enabled = 1, auth_setup_required = 0).

SSO (sso.py) is another way in and lands on the same create_access_token
helper, so a session looks identical regardless of how it was obtained.
"""

import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field, field_validator

from access_logs import log_action
import mfa
from auth_utils import (
    create_access_token,
    create_challenge_token,
    decode_token,
    get_current_user,
    role_permissions,
)
from database import get_conn, seed_default_roles

router = APIRouter(prefix="/api/auth", tags=["auth"])

_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _slugify(raw: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    return slug or "org"


class SignupRequest(BaseModel):
    org_name: str = Field(min_length=2, max_length=120)
    org_slug: str = Field(min_length=2, max_length=60)
    admin_name: str = Field(min_length=1, max_length=120)
    admin_email: EmailStr

    @field_validator("org_slug")
    @classmethod
    def _valid_slug(cls, v: str) -> str:
        v = v.lower()
        if not _SLUG_RE.match(v):
            raise ValueError("Slug can only contain lowercase letters, numbers, and hyphens.")
        return v


class LoginRequest(BaseModel):
    org_slug: str
    email: EmailStr


class MfaVerifyRequest(BaseModel):
    mfa_token: str
    code: str


def _user_payload(row: dict) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "email": row["email"],
        "role": row["role_name"],
        "is_admin": bool(row["role_is_admin"]),
        "permissions": role_permissions(row["role_id"]),
        "org_id": row["org_id"],
        "mfa_enabled": bool(row["mfa_enabled"]),
        "auth_setup_required": bool(row["auth_setup_required"]),
        "sso": row["sso_provider_id"] is not None,
    }


@router.post("/signup", status_code=201)
def signup(payload: SignupRequest):
    with get_conn() as conn:
        if conn.execute("SELECT id FROM organisations WHERE slug = ?", (payload.org_slug,)).fetchone():
            raise HTTPException(status_code=409, detail="That organisation URL is already taken.")

        cur = conn.execute(
            "INSERT INTO organisations (name, slug) VALUES (?, ?)", (payload.org_name, payload.org_slug)
        )
        org_id = cur.lastrowid
        role_ids = seed_default_roles(conn, org_id)

        # No password: the admin sets up Google Authenticator on their first
        # login (auth_setup_required defaults to 1).
        cur = conn.execute(
            """INSERT INTO users (org_id, name, email, role_id, status, auditpulse_access, mfa_enabled, auth_setup_required)
               VALUES (?, ?, ?, ?, 'Active', 1, 0, 1)""",
            (org_id, payload.admin_name, payload.admin_email, role_ids["Admin"]),
        )
        user_id = cur.lastrowid

    log_action(org_id, "organisation.created", target_type="organisation", target_id=org_id, detail=payload.org_name)
    log_action(org_id, "user.signed_up", target_type="user", target_id=user_id, detail=payload.admin_email)

    # No session yet — the frontend continues straight into login, which
    # shows the Google Authenticator QR setup for this new admin.
    return {"ok": True, "org_slug": payload.org_slug, "email": payload.admin_email}


@router.post("/login")
def login(payload: LoginRequest):
    """Step 1 — org + email. No password."""
    slug = payload.org_slug.strip().lower()
    email = payload.email.strip().lower()
    with get_conn() as conn:
        org = conn.execute("SELECT id FROM organisations WHERE slug = ?", (slug,)).fetchone()
        if not org:
            raise HTTPException(status_code=401, detail="No such organisation, or no account with that email.")

        row = conn.execute(
            """SELECT users.*, roles.name AS role_name FROM users
               JOIN roles ON roles.id = users.role_id
               WHERE users.org_id = ? AND LOWER(users.email) = ?""",
            (org["id"], email),
        ).fetchone()

        if not row:
            log_action(org["id"], "login.failed", detail=payload.email)
            raise HTTPException(status_code=401, detail="No such organisation, or no account with that email.")

        if row["status"] == "Disabled":
            log_action(org["id"], "login.blocked", target_type="user", target_id=row["id"], detail="account disabled")
            raise HTTPException(status_code=403, detail="This account's access has been disabled.")

        if mfa.needs_setup(row):
            setup = mfa.start_setup(conn, row)
            return {
                "step": "setup",
                "mfa_token": create_challenge_token(row["id"], org["id"], "mfa_setup"),
                "email": row["email"],
                **setup,
            }

    return {
        "step": "verify",
        "mfa_token": create_challenge_token(row["id"], org["id"], "mfa"),
        "email": row["email"],
    }


@router.post("/mfa/verify")
def verify_login_mfa(payload: MfaVerifyRequest):
    """Step 2 — the 6-digit Google Authenticator code -> session."""
    decoded = decode_token(payload.mfa_token)
    typ = decoded.get("typ")
    if typ not in ("mfa", "mfa_setup"):
        raise HTTPException(status_code=401, detail="Your sign-in attempt expired. Please enter your email again.")

    user_id, org_id = int(decoded["sub"]), decoded["org_id"]
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

    if not row:
        raise HTTPException(status_code=401, detail="Account no longer exists.")
    if row["status"] == "Disabled":
        raise HTTPException(status_code=403, detail="This account's access has been disabled.")
    if not row["mfa_secret"] or (typ == "mfa" and mfa.needs_setup(row)):
        # The admin reset the authenticator between step 1 and step 2.
        raise HTTPException(status_code=401, detail="Your authenticator was reset. Please enter your email again.")

    try:
        mfa.verify_code(user_id, row["mfa_secret"], payload.code)
    except HTTPException:
        log_action(org_id, "login.mfa_failed", target_type="user", target_id=user_id)
        raise

    if typ == "mfa_setup":
        with get_conn() as conn:
            mfa.complete_setup(conn, user_id)
        log_action(org_id, "mfa.setup_completed", target_type="user", target_id=user_id, detail=row["email"])

    log_action(org_id, "login", target_type="user", target_id=user_id, detail=f"{row['email']} (authenticator)")
    return {"access_token": create_access_token(user_id, org_id, amr="totp"), "token_type": "bearer"}


@router.get("/me")
def me(user: dict = Depends(get_current_user)):
    return _user_payload(user)
