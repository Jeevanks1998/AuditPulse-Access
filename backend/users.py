"""
users.py

Users are the core object of this portal: create a person (name, email,
role, AuditPulse access, status — no password), change their role,
activate/disable them, flip AuditPulse access on/off, and reset their
Google Authenticator. Every create/update calls auditpulse.sync_user()
so AuditPulse's side stays in step.

Sign-in is email -> Google Authenticator. A new user has
auth_setup_required = 1, so the first time they sign in (here or in
AuditPulse) they scan a QR code. Tell them their organisation URL and
the email you used; that is all they need.

POST /api/users/{id}/reset-authenticator clears their authenticator in
this portal *and* in AuditPulse, so their next login shows a new QR code
(lost or replaced phone).

Org-scoped, admin-only for mutations, and every action is written to
access_logs.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, model_validator

import auditpulse
from access_logs import log_action
import mfa
from auth_utils import get_current_user, require_admin
from database import get_conn

router = APIRouter(prefix="/api/users", tags=["users"])

VALID_STATUSES = ("Active", "Pending", "Disabled")


class UserCreate(BaseModel):
    name: str
    email: EmailStr
    role: str
    auditpulse_access: bool = True
    status: str = "Active"

    @model_validator(mode="after")
    def _valid_status(self):
        if self.status not in VALID_STATUSES:
            raise ValueError(f"Invalid status '{self.status}'")
        return self


class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    role: Optional[str] = None
    status: Optional[str] = None
    auditpulse_access: Optional[bool] = None

    @model_validator(mode="after")
    def _valid_status(self):
        if self.status is not None and self.status not in VALID_STATUSES:
            raise ValueError(f"Invalid status '{self.status}'")
        return self


def _row_to_user(row: dict) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "email": row["email"],
        "role": row["role_name"],
        "status": row["status"],
        "auditpulse_access": bool(row["auditpulse_access"]),
        "created_at": row["created_at"],
        "mfa_enabled": bool(row["mfa_enabled"]),
        "auth_setup_required": bool(row["auth_setup_required"]),
        "sso": row["sso_provider_id"] is not None,
        # Last sync attempt to AuditPulse for this email, if any — see
        # auditpulse.py. None until the first create/update after this
        # process started (in-memory only, see that module's docstring).
        "auditpulse_sync": auditpulse.last_sync_for(row["email"]),
    }


USER_SELECT = """
    SELECT users.*, roles.name AS role_name
    FROM users JOIN roles ON roles.id = users.role_id
"""


def _get_role_id(conn, org_id: int, role_name: str) -> int:
    role = conn.execute(
        "SELECT id FROM roles WHERE org_id = ? AND name = ?", (org_id, role_name)
    ).fetchone()
    if not role:
        raise HTTPException(status_code=400, detail=f"Unknown role '{role_name}'")
    return role["id"]


@router.get("")
def list_users(q: Optional[str] = Query(None, description="Search name/email/role"), user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        rows = conn.execute(
            USER_SELECT + " WHERE users.org_id = ? ORDER BY users.created_at DESC", (user["org_id"],)
        ).fetchall()
    users = [_row_to_user(r) for r in rows]
    if q:
        q_lower = q.lower()
        users = [
            u for u in users
            if q_lower in u["name"].lower() or q_lower in u["email"].lower() or q_lower in u["role"].lower()
        ]
    return users


@router.get("/stats")
def user_stats(user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        org_id = user["org_id"]
        total = conn.execute("SELECT COUNT(*) AS c FROM users WHERE org_id = ?", (org_id,)).fetchone()["c"]
        active = conn.execute(
            "SELECT COUNT(*) AS c FROM users WHERE org_id = ? AND status = 'Active'", (org_id,)
        ).fetchone()["c"]
        pending = conn.execute(
            "SELECT COUNT(*) AS c FROM users WHERE org_id = ? AND status = 'Pending'", (org_id,)
        ).fetchone()["c"]
        with_access = conn.execute(
            "SELECT COUNT(*) AS c FROM users WHERE org_id = ? AND auditpulse_access = 1", (org_id,)
        ).fetchone()["c"]
    return {"total": total, "active": active, "pending": pending, "with_access": with_access}


@router.post("", status_code=201)
def create_user(payload: UserCreate, admin: dict = Depends(require_admin)):
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE org_id = ? AND email = ?", (admin["org_id"], payload.email)
        ).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="A user with that email already exists")

        role_id = _get_role_id(conn, admin["org_id"], payload.role)

        # No password. auth_setup_required = 1: the person scans a Google
        # Authenticator QR code the first time they sign in.
        cur = conn.execute(
            """INSERT INTO users (org_id, name, email, role_id, status, auditpulse_access, mfa_enabled, auth_setup_required)
               VALUES (?, ?, ?, ?, ?, ?, 0, 1)""",
            (admin["org_id"], payload.name, payload.email, role_id, payload.status, int(payload.auditpulse_access)),
        )
        row = conn.execute(USER_SELECT + " WHERE users.id = ?", (cur.lastrowid,)).fetchone()

    user = _row_to_user(row)
    user["auditpulse_sync"] = auditpulse.sync_user(user)

    log_action(admin["org_id"], "user.created", actor=admin, target_type="user", target_id=row["id"], detail=payload.email)
    return user


@router.patch("/{user_id}")
def update_user(user_id: int, payload: UserUpdate, admin: dict = Depends(require_admin)):
    with get_conn() as conn:
        row = conn.execute(USER_SELECT + " WHERE users.id = ? AND users.org_id = ?", (user_id, admin["org_id"])).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found")

        fields, values = [], []
        log_details = []

        if payload.name is not None:
            fields.append("name = ?"); values.append(payload.name)
        if payload.email is not None:
            fields.append("email = ?"); values.append(payload.email)
        if payload.role is not None and payload.role != row["role_name"]:
            fields.append("role_id = ?"); values.append(_get_role_id(conn, admin["org_id"], payload.role))
            log_details.append(f"role: {row['role_name']} -> {payload.role}")
        if payload.status is not None:
            fields.append("status = ?"); values.append(payload.status)
        if payload.auditpulse_access is not None and bool(payload.auditpulse_access) != bool(row["auditpulse_access"]):
            fields.append("auditpulse_access = ?"); values.append(int(payload.auditpulse_access))
            log_details.append("access granted" if payload.auditpulse_access else "access revoked")
            # Toggling access off also parks the account as Disabled, unless
            # the caller explicitly set a status in the same request.
            if payload.status is None:
                fields.append("status = ?")
                values.append("Active" if payload.auditpulse_access else "Disabled")
        if payload.status is not None and payload.status != row["status"] and payload.auditpulse_access is None:
            log_details.append(f"status: {row['status']} -> {payload.status}")

        if fields:
            values.append(user_id)
            conn.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", values)

        row = conn.execute(USER_SELECT + " WHERE users.id = ?", (user_id,)).fetchone()

    user = _row_to_user(row)
    user["auditpulse_sync"] = auditpulse.sync_user(user)

    if log_details:
        log_action(admin["org_id"], "user.updated", actor=admin, target_type="user", target_id=user_id, detail="; ".join(log_details))
    return user


@router.post("/{user_id}/reset-authenticator")
def reset_user_authenticator(user_id: int, admin: dict = Depends(require_admin)):
    """Admin "Reset Authenticator": the person's next login (portal and
    AuditPulse) shows a new Google Authenticator QR code. Use when they
    lost or replaced their phone. Also ends their current portal sessions
    (auth_utils.get_current_user rejects them once this is set)."""
    with get_conn() as conn:
        row = conn.execute(USER_SELECT + " WHERE users.id = ? AND users.org_id = ?", (user_id, admin["org_id"])).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found")
        mfa.reset_authenticator(conn, user_id)
        row = conn.execute(USER_SELECT + " WHERE users.id = ?", (user_id,)).fetchone()

    user = _row_to_user(row)
    user["auditpulse_sync"] = auditpulse.sync_user(user, reset_authenticator=True)

    log_action(admin["org_id"], "user.authenticator_reset", actor=admin, target_type="user", target_id=user_id, detail=row["email"])
    return user


@router.delete("/{user_id}", status_code=204)
def delete_user(user_id: int, admin: dict = Depends(require_admin)):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ? AND org_id = ?", (user_id, admin["org_id"])).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found")
        if row["id"] == admin["id"]:
            raise HTTPException(status_code=400, detail="You can't delete your own account.")
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))

    auditpulse.revoke_user(row["email"])
    log_action(admin["org_id"], "user.deleted", actor=admin, target_type="user", target_id=user_id, detail=row["email"])
    return None
