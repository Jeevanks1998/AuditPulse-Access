"""
roles.py

Phase 1 had exactly four fixed roles, defined as a Python dict this
module just read from. Phase 5 replaces that with a real `permissions`
table (role_id, module, allowed) so a role's module access is editable
from roles.html, and an org's admin can create roles beyond the
original four — a "custom permission set" is no longer a roadmap item.

The four original roles (Admin/Auditor/Reviewer/Viewer) are still
seeded per-org (see database.py's seed_default_roles, called from
signup/init_db) and marked is_system=1: still deletable-proof and
rename-proof, but their *permissions* are just as editable as any
custom role's — "system" only protects the identity of the role, not
what it can do.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from access_logs import log_action
from auth_utils import get_current_user, require_admin
from database import MODULES, get_conn

router = APIRouter(prefix="/api/roles", tags=["roles"])


class RoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = ""
    is_admin: bool = False
    permissions: dict = Field(default_factory=dict)


class RoleUpdate(BaseModel):
    description: Optional[str] = None
    is_admin: Optional[bool] = None
    permissions: Optional[dict] = None


def _permissions(conn, role_id: int) -> dict:
    rows = conn.execute("SELECT module, allowed FROM permissions WHERE role_id = ?", (role_id,)).fetchall()
    by_module = {r["module"]: bool(r["allowed"]) for r in rows}
    return {m: by_module.get(m, False) for m in MODULES}


def _serialize(conn, role: dict, user_count: int) -> dict:
    return {
        "id": role["id"],
        "name": role["name"],
        "description": role["description"],
        "is_system": bool(role["is_system"]),
        "is_admin": bool(role["is_admin"]),
        "user_count": user_count,
        "permissions": _permissions(conn, role["id"]),
    }


def _user_counts(conn, org_id: int) -> dict:
    return {
        r["role_id"]: r["c"]
        for r in conn.execute(
            "SELECT role_id, COUNT(*) AS c FROM users WHERE org_id = ? GROUP BY role_id", (org_id,)
        ).fetchall()
    }


def _set_permissions(conn, role_id: int, permissions: dict) -> None:
    conn.execute("DELETE FROM permissions WHERE role_id = ?", (role_id,))
    conn.executemany(
        "INSERT INTO permissions (role_id, module, allowed) VALUES (?, ?, ?)",
        [(role_id, m, int(bool(permissions.get(m, False)))) for m in MODULES],
    )


@router.get("/modules")
def list_modules():
    """The fixed set of modules a role can be granted — mirrors
    AuditPulse's own sidebar. Lets roles.html render matrix columns
    without hardcoding a second copy of this list."""
    return list(MODULES)


@router.get("")
def list_roles(user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        roles = conn.execute(
            "SELECT * FROM roles WHERE org_id = ? ORDER BY is_system DESC, id", (user["org_id"],)
        ).fetchall()
        counts = _user_counts(conn, user["org_id"])
        return [_serialize(conn, r, counts.get(r["id"], 0)) for r in roles]


@router.get("/{role_id}")
def get_role(role_id: int, user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        role = conn.execute("SELECT * FROM roles WHERE id = ? AND org_id = ?", (role_id, user["org_id"])).fetchone()
        if not role:
            raise HTTPException(status_code=404, detail="Role not found")
        counts = _user_counts(conn, user["org_id"])
        return _serialize(conn, role, counts.get(role_id, 0))


@router.post("", status_code=201)
def create_role(payload: RoleCreate, admin: dict = Depends(require_admin)):
    with get_conn() as conn:
        if conn.execute(
            "SELECT id FROM roles WHERE org_id = ? AND name = ?", (admin["org_id"], payload.name)
        ).fetchone():
            raise HTTPException(status_code=409, detail="A role with that name already exists.")

        cur = conn.execute(
            "INSERT INTO roles (org_id, name, description, is_system, is_admin) VALUES (?, ?, ?, 0, ?)",
            (admin["org_id"], payload.name, payload.description, int(payload.is_admin)),
        )
        role_id = cur.lastrowid
        _set_permissions(conn, role_id, payload.permissions)
        role = conn.execute("SELECT * FROM roles WHERE id = ?", (role_id,)).fetchone()
        result = _serialize(conn, role, 0)

    log_action(admin["org_id"], "role.created", actor=admin, target_type="role", target_id=role_id, detail=payload.name)
    return result


@router.patch("/{role_id}")
def update_role(role_id: int, payload: RoleUpdate, admin: dict = Depends(require_admin)):
    with get_conn() as conn:
        role = conn.execute("SELECT * FROM roles WHERE id = ? AND org_id = ?", (role_id, admin["org_id"])).fetchone()
        if not role:
            raise HTTPException(status_code=404, detail="Role not found")

        log_details = []
        fields, values = [], []
        if payload.description is not None:
            fields.append("description = ?"); values.append(payload.description)
        if payload.is_admin is not None and bool(payload.is_admin) != bool(role["is_admin"]):
            fields.append("is_admin = ?"); values.append(int(payload.is_admin))
            log_details.append("admin: " + ("on" if payload.is_admin else "off"))

        if fields:
            values.append(role_id)
            conn.execute(f"UPDATE roles SET {', '.join(fields)} WHERE id = ?", values)

        if payload.permissions is not None:
            _set_permissions(conn, role_id, payload.permissions)
            log_details.append("permissions updated")

        role = conn.execute("SELECT * FROM roles WHERE id = ?", (role_id,)).fetchone()
        counts = _user_counts(conn, admin["org_id"])
        result = _serialize(conn, role, counts.get(role_id, 0))

    if log_details:
        log_action(admin["org_id"], "role.updated", actor=admin, target_type="role", target_id=role_id, detail="; ".join(log_details))
    return result


@router.delete("/{role_id}", status_code=204)
def delete_role(role_id: int, admin: dict = Depends(require_admin)):
    with get_conn() as conn:
        role = conn.execute("SELECT * FROM roles WHERE id = ? AND org_id = ?", (role_id, admin["org_id"])).fetchone()
        if not role:
            raise HTTPException(status_code=404, detail="Role not found")
        if role["is_system"]:
            raise HTTPException(status_code=400, detail="System roles can't be deleted.")
        in_use = conn.execute("SELECT COUNT(*) AS c FROM users WHERE role_id = ?", (role_id,)).fetchone()["c"]
        if in_use:
            raise HTTPException(status_code=400, detail=f"{in_use} user(s) still have this role — reassign them first.")
        conn.execute("DELETE FROM roles WHERE id = ?", (role_id,))

    log_action(admin["org_id"], "role.deleted", actor=admin, target_type="role", target_id=role_id, detail=role["name"])
    return None
