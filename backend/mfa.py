"""
mfa.py

TOTP-based MFA (Google Authenticator / Authy / 1Password, etc. — any app
that reads a standard otpauth:// URI). Two-step enable so a user can't
lock themselves out: /enroll generates a secret and shows it, /enable
only turns MFA on once they've proven they can generate a matching code.

This — plus auth.py's login/mfa-verify split — is the "portal auth" the
old roadmap said had to exist before MFA meant anything.
"""

import pyotp
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from access_logs import log_action
from auth_utils import get_current_user, verify_password
from database import get_conn

router = APIRouter(prefix="/api/auth/mfa", tags=["mfa"])


class MfaCodeRequest(BaseModel):
    code: str


class MfaDisableRequest(BaseModel):
    password: str


@router.post("/enroll")
def enroll(user: dict = Depends(get_current_user)):
    if user["mfa_enabled"]:
        raise HTTPException(status_code=409, detail="MFA is already enabled on this account.")

    secret = pyotp.random_base32()
    with get_conn() as conn:
        conn.execute("UPDATE users SET mfa_secret = ? WHERE id = ?", (secret, user["id"]))

    uri = pyotp.TOTP(secret).provisioning_uri(name=user["email"], issuer_name="AuditPulse Access")
    return {"secret": secret, "otpauth_uri": uri}


@router.post("/enable")
def enable(payload: MfaCodeRequest, user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        row = conn.execute("SELECT mfa_secret FROM users WHERE id = ?", (user["id"],)).fetchone()

    if not row or not row["mfa_secret"]:
        raise HTTPException(status_code=400, detail="Call /enroll first to generate a secret.")
    if not pyotp.TOTP(row["mfa_secret"]).verify(payload.code, valid_window=1):
        raise HTTPException(status_code=400, detail="That code didn't match — check your authenticator app's time sync and try again.")

    with get_conn() as conn:
        conn.execute("UPDATE users SET mfa_enabled = 1 WHERE id = ?", (user["id"],))
    log_action(user["org_id"], "mfa.enabled", actor=user, target_type="user", target_id=user["id"])
    return {"ok": True}


@router.post("/disable")
def disable(payload: MfaDisableRequest, user: dict = Depends(get_current_user)):
    if not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Password is incorrect.")
    with get_conn() as conn:
        conn.execute("UPDATE users SET mfa_enabled = 0, mfa_secret = NULL WHERE id = ?", (user["id"],))
    log_action(user["org_id"], "mfa.disabled", actor=user, target_type="user", target_id=user["id"])
    return {"ok": True}
