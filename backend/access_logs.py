"""
access_logs.py

A searchable trail of every access-affecting action (role changed, access
revoked, user created, someone signed in) — distinct from AuditPulse's
own product-activity History log, since this one tracks *who gave whom
access*, not what they did once they had it.

log_action() is the shared helper every other router calls right after a
mutation commits. It never raises — a logging failure should never take
down the action it's describing — and it writes on its own connection so
a caller mid-transaction doesn't need to thread one through.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query

from auth_utils import require_admin
from database import get_conn

router = APIRouter(prefix="/api/access-logs", tags=["access logs"])


def log_action(
    org_id: int,
    action: str,
    actor: Optional[dict] = None,
    target_type: Optional[str] = None,
    target_id: Optional[int] = None,
    detail: str = "",
) -> None:
    actor_user_id = actor["id"] if actor else None
    actor_label = actor["email"] if actor else "system"
    try:
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO access_logs
                       (org_id, actor_user_id, actor_label, action, target_type, target_id, detail)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (org_id, actor_user_id, actor_label, action, target_type, target_id, detail),
            )
    except Exception:
        # Never let a logging failure break the action it's recording.
        pass


def _serialize(row: dict) -> dict:
    return {
        "id": row["id"],
        "actor": row["actor_label"],
        "action": row["action"],
        "target_type": row["target_type"],
        "target_id": row["target_id"],
        "detail": row["detail"],
        "created_at": row["created_at"],
    }


@router.get("")
def list_access_logs(
    q: Optional[str] = Query(None, description="Search actor/action/detail"),
    action: Optional[str] = Query(None, description="Filter to an exact action, e.g. 'user.role_changed'"),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    admin: dict = Depends(require_admin),
):
    sql = "SELECT * FROM access_logs WHERE org_id = ?"
    params: list = [admin["org_id"]]

    if action:
        sql += " AND action = ?"
        params.append(action)
    if q:
        sql += " AND (actor_label LIKE ? OR action LIKE ? OR detail LIKE ?)"
        like = f"%{q}%"
        params += [like, like, like]

    sql += " ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?"
    params += [limit, offset]

    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) AS c FROM access_logs WHERE org_id = ?", (admin["org_id"],)
        ).fetchone()["c"]

    return {"items": [_serialize(r) for r in rows], "total": total}


@router.get("/actions")
def list_distinct_actions(admin: dict = Depends(require_admin)):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT action FROM access_logs WHERE org_id = ? ORDER BY action", (admin["org_id"],)
        ).fetchall()
    return [r["action"] for r in rows]
