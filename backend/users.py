"""
users.py

Users are the core object of this portal: create a person, set their
password, assign a role, flip AuditPulse access on/off. Every
create/update that touches role or access calls auditpulse.sync_user()
so AuditPulse's side stays in step. Phase 5 adds: org scoping (every
query filtered to the caller's org_id), admin-only gating on mutations,
an admin-chosen password on invite (the admin types it directly into
the Create User form and hands it to the person themselves — this
portal has no emailer), and an access_logs entry for every
create/update/delete/role-change/access-toggle/password-reset.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field, model_validator

import auditpulse
from access_logs import log_action
from auth_utils import get_current_user, hash_password, require_admin
from database import get_conn

router = APIRouter(prefix="/api/users", tags=["users"])

VALID_STATUSES = ("Active", "Pending", "Disabled")


class UserCreate(BaseModel):
    name: str
    email: EmailStr
    # The admin types this directly on the Create User form (with
    # confirm_password as a same-request client- and server-side check)
    # rather than the portal generating one — see the module docstring.
    password: str = Field(min_length=8, max_length=128)
    confirm_password: str
    role: str
    auditpulse_access: bool = True
    status: str = "Active"

    @model_validator(mode="after")
    def _passwords_match(self):
        if self.password != self.confirm_password:
            raise ValueError("Password and confirm password don't match.")
        if self.status not in VALID_STATUSES:
            raise ValueError(f"Invalid status '{self.status}'")
        return self


class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    role: Optional[str] = None
    status: Optional[str] = None
    auditpulse_access: Optional[bool] = None
    # Optional password reset — an admin editing a user only fills these
    # in to change the password; leaving both blank keeps the current one.
    password: Optional[str] = Field(default=None, min_length=8, max_length=128)
    confirm_password: Optional[str] = None

    @model_validator(mode="after")
    def _passwords_match(self):
        if self.password is not None and self.password != self.confirm_password:
            raise ValueError("Password and confirm password don't match.")
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
        password_hash = hash_password(payload.password)

        # must_change_password stays 0 here: the admin set this password
        # deliberately (rather than the portal generating a throwaway
        # one), so there's no "temporary" credential to force a reset on.
        cur = conn.execute(
            """INSERT INTO users (org_id, name, email, role_id, status, auditpulse_access, password_hash, must_change_password)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
            (admin["org_id"], payload.name, payload.email, role_id, payload.status, int(payload.auditpulse_access), password_hash),
        )
        row = conn.execute(USER_SELECT + " WHERE users.id = ?", (cur.lastrowid,)).fetchone()

    user = _row_to_user(row)
    # Forward the same hash to AuditPulse so the password the admin just
    # set actually works on AuditPulse's own internal login page — see
    # auditpulse.sync_user()'s docstring for why this is safe to share.
    user["auditpulse_sync"] = auditpulse.sync_user(user, password_hash=password_hash)

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
        new_password_hash: Optional[str] = None

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
        if payload.password:
            # An admin resetting the password from the Edit User form —
            # distinct from the person's own self-service change-password
            # flow in auth.py. must_change_password is left as-is (0):
            # the admin chose this password on purpose, it isn't a
            # throwaway the person still needs to replace.
            new_password_hash = hash_password(payload.password)
            fields.append("password_hash = ?"); values.append(new_password_hash)
            log_details.append("password reset by admin")

        if fields:
            values.append(user_id)
            conn.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", values)

        row = conn.execute(USER_SELECT + " WHERE users.id = ?", (user_id,)).fetchone()

    user = _row_to_user(row)
    # Only forward the hash to AuditPulse when it actually changed here —
    # see auditpulse.sync_user()'s docstring on why a plain role/status/
    # access update must leave password_hash out (None) so it doesn't
    # clobber a password the person may have since changed on that side.
    user["auditpulse_sync"] = auditpulse.sync_user(user, password_hash=new_password_hash)

    if log_details:
        log_action(admin["org_id"], "user.updated", actor=admin, target_type="user", target_id=user_id, detail="; ".join(log_details))
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
