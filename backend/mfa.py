"""
mfa.py

Google Authenticator (TOTP) for portal sign-in. Plain RFC 6238 via pyotp,
so any authenticator app works (Google Authenticator, Microsoft
Authenticator, Authy, 1Password). No Google API key is involved.

Sign-in is email -> authenticator (no password). This module holds the
TOTP pieces; auth.py's /login and /mfa/verify call them:

    First login (auth_setup_required = 1):
        start_setup()  -> new secret + QR code shown on the login page
        verify_code()  -> correct code -> complete_setup()
                          (mfa_enabled = 1, auth_setup_required = 0)

    Later logins:
        verify_code()  -> correct code -> session

    Admin "Reset Authenticator" (users.py):
        reset_authenticator()
                       -> mfa_enabled = 0, auth_setup_required = 1,
                          mfa_secret = NULL; next login shows a new QR

There is no self-service "disable" any more: the authenticator *is* the
sign-in, so turning it off would lock the person out. Lost phone -> an
admin resets it.
"""

import time
from typing import Dict, Tuple

import pyotp
import segno
from fastapi import APIRouter, Depends, HTTPException

from auth_utils import get_current_user

router = APIRouter(prefix="/api/auth/mfa", tags=["mfa"])

# Name shown above the 6-digit code in Google Authenticator.
TOTP_ISSUER = "AuditPulse Access"

# Brute-force guard on the 6-digit code: after MAX_CODE_FAILURES wrong
# codes, code entry is locked for CODE_LOCKOUT_SECONDS. In-process memory
# is enough for a single Railway instance.
MAX_CODE_FAILURES = 5
CODE_LOCKOUT_SECONDS = 5 * 60
_code_failures: Dict[int, Tuple[int, float]] = {}


# ------------------------------- TOTP helpers ------------------------------- #

def needs_setup(row: dict) -> bool:
    return bool(row["auth_setup_required"]) or not row["mfa_enabled"] or not row["mfa_secret"]


def start_setup(conn, row: dict) -> dict:
    """Issue a fresh secret for first-time setup (or after a reset).

    The secret is saved now but mfa_enabled stays 0 until the person
    proves they scanned it with a correct code (complete_setup). Calling
    this again simply replaces an unfinished secret.
    """
    secret = pyotp.random_base32()
    conn.execute(
        "UPDATE users SET mfa_secret = ?, mfa_enabled = 0, auth_setup_required = 1 WHERE id = ?",
        (secret, row["id"]),
    )
    uri = pyotp.TOTP(secret).provisioning_uri(name=row["email"], issuer_name=TOTP_ISSUER)
    return {
        "secret": secret,
        "otpauth_uri": uri,
        "qr_code": segno.make(uri, error="m").svg_data_uri(scale=5, border=2),
    }


def complete_setup(conn, user_id: int) -> None:
    conn.execute(
        "UPDATE users SET mfa_enabled = 1, auth_setup_required = 0 WHERE id = ?", (user_id,)
    )


def reset_authenticator(conn, user_id: int) -> None:
    conn.execute(
        "UPDATE users SET mfa_secret = NULL, mfa_enabled = 0, auth_setup_required = 1 WHERE id = ?",
        (user_id,),
    )


def verify_code(user_id: int, secret: str, code: str) -> None:
    """Raise HTTPException unless `code` is the current TOTP for `secret`."""
    failures, locked_until = _code_failures.get(user_id, (0, 0.0))
    if locked_until and time.time() < locked_until:
        raise HTTPException(
            status_code=429,
            detail="Too many incorrect codes. Please wait a few minutes and try again.",
        )

    digits = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(digits) == 6 and pyotp.TOTP(secret).verify(digits, valid_window=1):
        _code_failures.pop(user_id, None)
        return

    if locked_until and time.time() >= locked_until:
        failures = 0
    failures += 1
    _code_failures[user_id] = (
        failures,
        time.time() + CODE_LOCKOUT_SECONDS if failures >= MAX_CODE_FAILURES else 0.0,
    )
    raise HTTPException(
        status_code=400,
        detail="That code didn't match. Check the 6-digit code in Google Authenticator and try again.",
    )


# ---------------------------------- routes ---------------------------------- #

@router.get("/status")
def status(user: dict = Depends(get_current_user)):
    """Shown on account.html."""
    return {
        "mfa_enabled": bool(user["mfa_enabled"]),
        "auth_setup_required": bool(user["auth_setup_required"]),
        "issuer": TOTP_ISSUER,
    }
