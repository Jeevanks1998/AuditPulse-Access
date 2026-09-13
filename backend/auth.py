"""
auth.py

Portal auth. Two entry points to get a session:

  1. POST /api/auth/signup — bootstraps a brand new organisation with its
     four default roles and one Admin user (self-service; this is how
     "Multiple organisations" actually gets used day to day — anyone can
     spin up an isolated org instead of a super-admin provisioning one).
  2. POST /api/auth/login  — email + password + org slug (the org slug
     disambiguates two orgs that happen to reuse the same email). If the
     account has MFA enabled this returns a short-lived mfa_token instead
     of a session, which POST /api/auth/mfa/verify exchanges for one
     once the caller proves they also have the authenticator.

SSO (sso.py) is a third way in, and lands on the same create_access_token
helper so a session looks identical regardless of how it was obtained.
"""

import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field, field_validator

from access_logs import log_action
from auth_utils import (
    create_access_token,
    create_mfa_token,
    decode_token,
    get_current_user,
    hash_password,
    role_permissions,
    verify_password,
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
    admin_password: str = Field(min_length=8, max_length=128)

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
    password: str


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
        "must_change_password": bool(row["must_change_password"]),
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

        cur = conn.execute(
            """INSERT INTO users (org_id, name, email, role_id, status, auditpulse_access, password_hash)
               VALUES (?, ?, ?, ?, 'Active', 1, ?)""",
            (org_id, payload.admin_name, payload.admin_email, role_ids["Admin"], hash_password(payload.admin_password)),
        )
        user_id = cur.lastrowid

    log_action(org_id, "organisation.created", target_type="organisation", target_id=org_id, detail=payload.org_name)
    log_action(org_id, "user.signed_up", target_type="user", target_id=user_id, detail=payload.admin_email)

    return {"access_token": create_access_token(user_id, org_id), "token_type": "bearer"}


@router.post("/login")
def login(payload: LoginRequest, request: Request):
    with get_conn() as conn:
        org = conn.execute("SELECT id FROM organisations WHERE slug = ?", (payload.org_slug,)).fetchone()
        if not org:
            raise HTTPException(status_code=401, detail="No such organisation, or wrong email/password.")

        row = conn.execute(
            """SELECT users.*, roles.name AS role_name FROM users
               JOIN roles ON roles.id = users.role_id
               WHERE users.org_id = ? AND users.email = ?""",
            (org["id"], payload.email),
        ).fetchone()

    if not row or not verify_password(payload.password, row["password_hash"]):
        log_action(org["id"], "login.failed", detail=payload.email)
        raise HTTPException(status_code=401, detail="No such organisation, or wrong email/password.")

    if row["status"] == "Disabled":
        log_action(org["id"], "login.blocked", target_type="user", target_id=row["id"], detail="account disabled")
        raise HTTPException(status_code=403, detail="This account's access has been disabled.")

    if row["mfa_enabled"]:
        return {"mfa_required": True, "mfa_token": create_mfa_token(row["id"], org["id"])}

    log_action(org["id"], "login", target_type="user", target_id=row["id"], detail=payload.email)
    return {"access_token": create_access_token(row["id"], org["id"]), "token_type": "bearer"}


@router.post("/mfa/verify")
def verify_login_mfa(payload: MfaVerifyRequest):
    import pyotp

    decoded = decode_token(payload.mfa_token)
    if decoded.get("typ") != "mfa":
        raise HTTPException(status_code=401, detail="Invalid or expired MFA challenge.")

    user_id, org_id = int(decoded["sub"]), decoded["org_id"]
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

    if not row or not row["mfa_enabled"] or not row["mfa_secret"]:
        raise HTTPException(status_code=401, detail="MFA is not set up on this account.")

    if not pyotp.TOTP(row["mfa_secret"]).verify(payload.code, valid_window=1):
        log_action(org_id, "login.mfa_failed", target_type="user", target_id=user_id)
        raise HTTPException(status_code=401, detail="Incorrect authentication code.")

    log_action(org_id, "login", target_type="user", target_id=user_id, detail=f"{row['email']} (MFA)")
    return {"access_token": create_access_token(user_id, org_id), "token_type": "bearer"}


@router.get("/me")
def me(user: dict = Depends(get_current_user)):
    return _user_payload(user)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


@router.post("/change-password")
def change_password(payload: ChangePasswordRequest, user: dict = Depends(get_current_user)):
    if not verify_password(payload.current_password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Current password is incorrect.")
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?",
            (hash_password(payload.new_password), user["id"]),
        )
    log_action(user["org_id"], "user.password_changed", actor=user, target_type="user", target_id=user["id"])
    return {"ok": True}
