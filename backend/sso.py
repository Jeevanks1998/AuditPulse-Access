"""
sso.py

A generic OpenID Connect client — not "an Okta integration" and "a Google
integration" side by side, but one client that works against anything
speaking standard OIDC (Okta, Google Workspace, Azure AD/Entra, Auth0,
Ping, ...), since they all expose the same discovery document, the same
authorization-code flow, and the same ID-token/userinfo shape. An org's
admin points this at their IdP's issuer URL; everything else (endpoint
URLs, signing keys) is fetched from `{issuer}/.well-known/openid-configuration`
rather than hardcoded per-provider.

Flow:
  1. organisation.html (admin) configures a provider: issuer, client_id,
     client_secret, a display label. Stored in sso_providers, one row
     per org. The secret is never returned by GET — only whether one is
     already set.
  2. login.html reads GET /api/sso/{org_slug}/config (public — no auth
     required, since this happens *before* login) to decide whether to
     show a "Sign in with {label}" button at all.
  3. Clicking that button hits GET /api/sso/{org_slug}/authorize, which
     redirects the browser to the IdP with a signed `state` (org_id +
     nonce, same JWT machinery as auth_utils, typ="sso_state") and a
     redirect_uri pointing back at *this* backend (not the frontend —
     the code exchange needs the client_secret, which never reaches the
     browser).
  4. The IdP redirects back to GET /api/sso/callback. This backend
     exchanges the code for tokens, calls the userinfo endpoint, and
     either finds a matching user (by email, within that org) or
     JIT-provisions one with the org's default Viewer role. Either way
     it lands on create_access_token — a session looks identical
     whether it came from a password, MFA, or SSO.
  5. The browser is redirected to `{FRONTEND_BASE_URL}/sso-callback.html
     #token=...`, which auth.js reads, stores, and forwards to
     index.html — see that file.

PORTAL_BASE_URL and FRONTEND_BASE_URL need setting in backend/.env for
step 3/5 to build correct URLs outside of the localhost defaults — see
.env.example.
"""

import os
import time
from typing import Optional
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from access_logs import log_action
from auth_utils import SECRET_KEY, ALGORITHM, create_access_token, require_admin
from database import get_conn, seed_default_roles

router = APIRouter(prefix="/api/sso", tags=["sso"])

PORTAL_BASE_URL = os.getenv("PORTAL_BASE_URL", "http://localhost:8010").rstrip("/")
FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:5500").rstrip("/")
STATE_TTL_SECONDS = 10 * 60

# {issuer: discovery_document} — discovery documents don't change at
# runtime, so refetching one on every login would just be latency for
# nothing. Cleared by restarting the process if an IdP ever rotates its
# endpoints, same trade-off as auditpulse.py's in-memory sync status.
_discovery_cache: dict[str, dict] = {}


def _discover(issuer: str) -> dict:
    if issuer not in _discovery_cache:
        url = issuer.rstrip("/") + "/.well-known/openid-configuration"
        try:
            resp = httpx.get(url, timeout=6.0)
            resp.raise_for_status()
            _discovery_cache[issuer] = resp.json()
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Could not read OIDC discovery document from {issuer}: {exc}")
    return _discovery_cache[issuer]


def _make_state(org_id: int) -> str:
    payload = {"org_id": org_id, "typ": "sso_state", "iat": int(time.time()), "exp": int(time.time()) + STATE_TTL_SECONDS}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def _read_state(state: str) -> int:
    try:
        decoded = jwt.decode(state, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(status_code=400, detail="Invalid or expired SSO state.")
    if decoded.get("typ") != "sso_state":
        raise HTTPException(status_code=400, detail="Invalid SSO state.")
    return decoded["org_id"]


# ------------------------------- admin config ------------------------------ #

class SsoConfigIn(BaseModel):
    label: str = Field(default="Single Sign-On", max_length=80)
    issuer: str = Field(min_length=1, max_length=300)
    client_id: str = Field(min_length=1, max_length=300)
    client_secret: str = Field(min_length=1, max_length=300)
    enabled: bool = True


def _config_out(row: Optional[dict]) -> dict:
    if not row:
        return {"configured": False}
    return {
        "configured": True,
        "label": row["label"],
        "issuer": row["issuer"],
        "client_id": row["client_id"],
        "client_secret_set": bool(row["client_secret"]),
        "enabled": bool(row["enabled"]),
    }


@router.get("/config")
def get_admin_sso_config(admin: dict = Depends(require_admin)):
    """The caller's own org's SSO config, for organisation.html. Never
    returns the raw secret — only whether one is set."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM sso_providers WHERE org_id = ?", (admin["org_id"],)).fetchone()
    return _config_out(row)


@router.put("/config")
def set_admin_sso_config(payload: SsoConfigIn, admin: dict = Depends(require_admin)):
    with get_conn() as conn:
        existing = conn.execute("SELECT id FROM sso_providers WHERE org_id = ?", (admin["org_id"],)).fetchone()
        if existing:
            conn.execute(
                """UPDATE sso_providers SET label = ?, issuer = ?, client_id = ?, client_secret = ?, enabled = ?
                   WHERE org_id = ?""",
                (payload.label, payload.issuer, payload.client_id, payload.client_secret, int(payload.enabled), admin["org_id"]),
            )
        else:
            conn.execute(
                """INSERT INTO sso_providers (org_id, label, issuer, client_id, client_secret, enabled)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (admin["org_id"], payload.label, payload.issuer, payload.client_id, payload.client_secret, int(payload.enabled)),
            )
        row = conn.execute("SELECT * FROM sso_providers WHERE org_id = ?", (admin["org_id"],)).fetchone()

    log_action(admin["org_id"], "sso.configured", actor=admin, target_type="organisation", target_id=admin["org_id"], detail=payload.issuer)
    return _config_out(row)


@router.delete("/config", status_code=204)
def delete_admin_sso_config(admin: dict = Depends(require_admin)):
    with get_conn() as conn:
        conn.execute("DELETE FROM sso_providers WHERE org_id = ?", (admin["org_id"],))
    log_action(admin["org_id"], "sso.disabled", actor=admin, target_type="organisation", target_id=admin["org_id"])
    return None


# --------------------------------- public flow ------------------------------ #

@router.get("/{org_slug}/config")
def public_sso_config(org_slug: str):
    """Unauthenticated — login.html calls this before anyone has signed
    in, to decide whether a 'Sign in with {label}' button should even
    appear for this org."""
    with get_conn() as conn:
        org = conn.execute("SELECT id FROM organisations WHERE slug = ?", (org_slug,)).fetchone()
        if not org:
            return {"enabled": False}
        row = conn.execute(
            "SELECT * FROM sso_providers WHERE org_id = ? AND enabled = 1", (org["id"],)
        ).fetchone()
    if not row:
        return {"enabled": False}
    return {"enabled": True, "label": row["label"]}


@router.get("/{org_slug}/authorize")
def authorize(org_slug: str):
    with get_conn() as conn:
        org = conn.execute("SELECT id FROM organisations WHERE slug = ?", (org_slug,)).fetchone()
        if not org:
            raise HTTPException(status_code=404, detail="No such organisation.")
        provider = conn.execute(
            "SELECT * FROM sso_providers WHERE org_id = ? AND enabled = 1", (org["id"],)
        ).fetchone()
    if not provider:
        raise HTTPException(status_code=404, detail="SSO isn't configured for this organisation.")

    discovery = _discover(provider["issuer"])
    params = {
        "response_type": "code",
        "client_id": provider["client_id"],
        "redirect_uri": f"{PORTAL_BASE_URL}/api/sso/callback",
        "scope": "openid email profile",
        "state": _make_state(org["id"]),
    }
    return RedirectResponse(url=f"{discovery['authorization_endpoint']}?{urlencode(params)}")


@router.get("/callback")
def callback(code: str = Query(...), state: str = Query(...)):
    org_id = _read_state(state)

    with get_conn() as conn:
        provider = conn.execute("SELECT * FROM sso_providers WHERE org_id = ? AND enabled = 1", (org_id,)).fetchone()
    if not provider:
        raise HTTPException(status_code=404, detail="SSO isn't configured for this organisation.")

    discovery = _discover(provider["issuer"])

    try:
        token_resp = httpx.post(
            discovery["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": f"{PORTAL_BASE_URL}/api/sso/callback",
                "client_id": provider["client_id"],
                "client_secret": provider["client_secret"],
            },
            timeout=8.0,
        )
        token_resp.raise_for_status()
        tokens = token_resp.json()

        userinfo_resp = httpx.get(
            discovery["userinfo_endpoint"],
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
            timeout=8.0,
        )
        userinfo_resp.raise_for_status()
        userinfo = userinfo_resp.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"SSO provider didn't complete sign-in: {exc}")

    email = userinfo.get("email")
    name = userinfo.get("name") or (email.split("@")[0] if email else "SSO user")
    if not email:
        raise HTTPException(status_code=400, detail="SSO provider didn't return an email address.")

    with get_conn() as conn:
        user = conn.execute("SELECT * FROM users WHERE org_id = ? AND email = ?", (org_id, email)).fetchone()
        if user:
            conn.execute(
                "UPDATE users SET sso_provider_id = ?, status = CASE WHEN status = 'Pending' THEN 'Active' ELSE status END WHERE id = ?",
                (provider["id"], user["id"]),
            )
            user_id = user["id"]
            action = "login.sso"
        else:
            roles = {r["name"]: r["id"] for r in conn.execute(
                "SELECT id, name FROM roles WHERE org_id = ?", (org_id,)
            ).fetchall()}
            role_id = roles.get("Viewer") or next(iter(roles.values()), None)
            if role_id is None:
                role_id = seed_default_roles(conn, org_id)["Viewer"]
            cur = conn.execute(
                """INSERT INTO users (org_id, name, email, role_id, status, auditpulse_access, sso_provider_id)
                   VALUES (?, ?, ?, ?, 'Active', 1, ?)""",
                (org_id, name, email, role_id, provider["id"]),
            )
            user_id = cur.lastrowid
            action = "user.sso_provisioned"

    log_action(org_id, action, target_type="user", target_id=user_id, detail=email)

    token = create_access_token(user_id, org_id)
    return RedirectResponse(url=f"{FRONTEND_BASE_URL}/sso-callback.html#token={token}")
