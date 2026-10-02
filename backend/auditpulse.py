"""
auditpulse.py

The connection between this portal and the existing AuditPulse product.

    Access Portal
          |
          v
    auditpulse.py  --  User ID, Role, Status, Access  -->  AuditPulse
          ^
          |
    (Phase 3: real HTTP call to AuditPulse/backend/api/access_management.py.
     Phase 5 on AuditPulse's side split the single "Access" boolean this
     sent into two — `active` (this portal's `status`) and
     `auditpulse_access` — see sync_user()'s docstring below.)

sync_user()/revoke_user() are the two functions users.py already calls —
that never changed between phases, so wiring this up for real was a
one-file change; nothing in users.py needed to move.

Talking to AuditPulse never blocks or breaks a portal action: this is a
side effect of a user create/update/delete, not the operation itself. If
AuditPulse is unreachable, slow, or rejects the call, the failure is
logged and recorded (see `_record`/`last_sync_for`) so the UI can show
it, but the portal's own database change already committed and the
HTTP request to *this* API still returns success. The alternative —
failing the user's create/update because a downstream system hiccupped —
would make the portal only as reliable as AuditPulse's uptime, for a
sync that's meant to be eventually-consistent, not transactional.

To enable this for real:
  1. Set AUDITPULSE_BASE_URL (e.g. http://localhost:8000/api/v1) and
     AUDITPULSE_API_KEY as environment variables for this backend.
  2. Set the *same* key as ACCESS_PORTAL_API_KEY in AuditPulse's own
     backend/.env — see that repo's .env.example.
  3. Restart both backends. GET /api/auditpulse/status (added below)
     confirms both sides agree before you rely on it.
"""

import os
from datetime import datetime, timezone
from typing import Optional

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter

# This portal otherwise has no .env loading (database.py/roles.py/users.py
# only ever needed hardcoded/sqlite config) — load it here, once, at import
# time, so backend/.env (see backend/.env.example) is picked up the same
# way AuditPulse's own pydantic-settings reads its .env automatically.
load_dotenv()

AUDITPULSE_BASE_URL = os.getenv("AUDITPULSE_BASE_URL", "").rstrip("/")
AUDITPULSE_API_KEY = os.getenv("AUDITPULSE_API_KEY", "")
AUDITPULSE_TIMEOUT_SECONDS = float(os.getenv("AUDITPULSE_TIMEOUT_SECONDS", "5"))

# Per-user record of the last sync attempt, keyed by email. Powers
# GET /api/auditpulse/status[/​{email}] and the sync badge users.js shows
# next to the AuditPulse-access toggle. In-memory only — a restart clears
# it, which just means the badge goes back to "not synced yet" until the
# next create/update, not a data-loss concern (the portal's own users
# table is the source of truth; this is a status display only).
_last_sync: dict[str, dict] = {}


def _configured() -> bool:
    return bool(AUDITPULSE_BASE_URL and AUDITPULSE_API_KEY)


def _record(email: str, *, ok: bool, detail: str) -> dict:
    entry = {
        "ok": ok,
        "detail": detail,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    _last_sync[email] = entry
    return entry


def sync_user(user: dict, reset_authenticator: bool = False) -> dict:
    """Push a user's current status/role/access to AuditPulse.

    `user` is the same shape users.py returns to the frontend:
    {id, name, email, role, status, auditpulse_access, created_at}.

    No password is sent: sign-in on both sides is email -> Google
    Authenticator. A user AuditPulse hasn't seen before is created there
    with auth_setup_required = True, so they scan a QR code on their
    first AuditPulse login.

    `reset_authenticator=True` is sent by users.py's "Reset
    Authenticator" action; AuditPulse then clears that person's
    authenticator so their next AuditPulse login shows a new QR code.

    Sends `active` and `auditpulse_access` as two separate booleans —
    matching AuditPulse's schemas.access.AccessSyncIn (Phase 5 on that
    side) — rather than collapsing them into one `access` flag:

      active              this portal's `status` field is more than a
                          two-state toggle ("Active"/"Pending"/"Disabled"),
                          so `active` here means specifically "Active",
                          not merely "not Disabled". A user who hasn't
                          completed invite/activation (status="Pending")
                          isn't active yet either.
      auditpulse_access    this portal's `auditpulse_access` column,
                          unchanged — whether this person's role/
                          assignment grants them AuditPulse specifically,
                          independent of their broader portal status.

    A user can therefore be `active: true` with `auditpulse_access:
    false` (Active in the portal, e.g. still using other portal-managed
    apps, but explicitly toggled off from AuditPulse on users.html) —
    AuditPulse's own login route rejects that case with a message
    distinct from an inactive account.

    Always returns a status dict (see _record) — never raises. Callers in
    users.py don't need a try/except around this.
    """
    payload = {
        "user_id": user["id"],
        "email": user["email"],
        "name": user["name"],
        "role": user["role"],
        "active": user["status"] == "Active",
        "auditpulse_access": bool(user["auditpulse_access"]),
    }
    if reset_authenticator:
        payload["reset_authenticator"] = True

    if not _configured():
        return _record(user["email"], ok=False, detail="AuditPulse integration not configured")

    try:
        resp = httpx.post(
            f"{AUDITPULSE_BASE_URL}/internal/access",
            json=payload,
            headers={"Authorization": f"Bearer {AUDITPULSE_API_KEY}"},
            timeout=AUDITPULSE_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        forget_status_cache()
        return _record(user["email"], ok=True, detail="Synced")
    except httpx.HTTPStatusError as exc:
        detail = f"AuditPulse rejected the sync ({exc.response.status_code})"
        try:
            detail = f"{detail}: {exc.response.json().get('error', '')}"
        except Exception:
            pass
        return _record(user["email"], ok=False, detail=detail)
    except httpx.RequestError as exc:
        return _record(user["email"], ok=False, detail=f"Could not reach AuditPulse: {exc}")


def revoke_user(email: str) -> dict:
    """Tell AuditPulse a user no longer exists in the portal at all
    (as opposed to sync_user with access=False, which keeps the account
    but turns off access).

    Also never raises, for the same reason as sync_user.
    """
    if not _configured():
        _last_sync.pop(email, None)
        return {"ok": False, "detail": "AuditPulse integration not configured"}

    try:
        resp = httpx.post(
            f"{AUDITPULSE_BASE_URL}/internal/access/revoke",
            json={"email": email},
            headers={"Authorization": f"Bearer {AUDITPULSE_API_KEY}"},
            timeout=AUDITPULSE_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        result = {"ok": True, "detail": "Revoked"}
    except httpx.HTTPStatusError as exc:
        result = {"ok": False, "detail": f"AuditPulse rejected the revoke ({exc.response.status_code})"}
    except httpx.RequestError as exc:
        result = {"ok": False, "detail": f"Could not reach AuditPulse: {exc}"}

    _last_sync.pop(email, None)
    return result


def last_sync_for(email: str) -> Optional[dict]:
    return _last_sync.get(email)


# --------------------------------------------------------------------------
# AuditPulse sign-in status (Users page "Authenticator" column)
#
# The portal and AuditPulse each have their own Google Authenticator. The
# portal only knows its own; this asks AuditPulse for the AuditPulse side so
# the Users page can show both. Cached briefly so loading the page doesn't
# call AuditPulse on every refresh; never raises.
# --------------------------------------------------------------------------
STATUS_CACHE_SECONDS = 30
_status_cache: dict = {"at": 0.0, "key": None, "data": None}


def auditpulse_statuses(emails: list) -> Optional[dict]:
    """{email_lower: {exists, mfa_enabled, auth_setup_required, ...}} or None
    when AuditPulse isn't configured / can't be reached right now."""
    import time

    if not _configured() or not emails:
        return None
    key = tuple(sorted({e.lower() for e in emails}))
    now = time.monotonic()
    if _status_cache["key"] == key and now - _status_cache["at"] < STATUS_CACHE_SECONDS:
        return _status_cache["data"]
    try:
        resp = httpx.post(
            f"{AUDITPULSE_BASE_URL}/internal/access/status",
            json={"emails": list(key)},
            headers={"Authorization": f"Bearer {AUDITPULSE_API_KEY}"},
            timeout=AUDITPULSE_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = (resp.json() or {}).get("users") or {}
    except Exception:  # noqa: BLE001 — an unreachable AuditPulse never breaks the Users page
        return None
    _status_cache.update(at=now, key=key, data=data)
    return data


def forget_status_cache() -> None:
    """Called after a sync/reset so the next page load shows fresh state."""
    _status_cache.update(at=0.0, key=None, data=None)


# --------------------------------------------------------------------------
# Status router — mounted by main.py. Separate from users.py/roles.py
# because it's about the *connection*, not a portal resource of its own.
# --------------------------------------------------------------------------
router = APIRouter(prefix="/api/auditpulse", tags=["auditpulse"])


@router.get("/status")
def connection_status():
    """Overall integration health: is it configured, and can this backend
    actually reach AuditPulse right now? Used by index.html's dashboard.
    """
    if not _configured():
        return {"configured": False, "reachable": False, "detail": "AUDITPULSE_BASE_URL/AUDITPULSE_API_KEY not set"}

    try:
        resp = httpx.get(f"{AUDITPULSE_BASE_URL}/internal/access/health", timeout=AUDITPULSE_TIMEOUT_SECONDS)
        resp.raise_for_status()
        remote = resp.json()
        return {
            "configured": True,
            "reachable": True,
            "detail": "Connected" if remote.get("configured") else "Connected, but AuditPulse's ACCESS_PORTAL_API_KEY isn't set",
        }
    except httpx.RequestError as exc:
        return {"configured": True, "reachable": False, "detail": f"Could not reach AuditPulse: {exc}"}
    except httpx.HTTPStatusError as exc:
        return {"configured": True, "reachable": False, "detail": f"AuditPulse returned {exc.response.status_code}"}


@router.get("/status/{email}")
def user_sync_status(email: str):
    """Last sync result for one user, for the badge next to their
    AuditPulse-access toggle on users.html."""
    return last_sync_for(email) or {"ok": None, "detail": "Not synced yet", "at": None}
