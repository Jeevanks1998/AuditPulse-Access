"""
teams.py

Group users into teams (e.g. by department or client) so access and
audit ownership can eventually be scoped to a team, not just an
individual or the whole org. This portal owns team membership; a team_id
on AuditPulse's own audits/websites (to actually scope by team there) is
a follow-up on AuditPulse's side, same shape as Phase 3's access-sync.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from access_logs import log_action
from auth_utils import get_current_user, require_admin
from database import get_conn

router = APIRouter(prefix="/api/teams", tags=["teams"])


class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = ""


class TeamUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class MemberAdd(BaseModel):
    user_id: int


def _members(conn, team_id: int) -> list:
    rows = conn.execute(
        """SELECT users.id, users.name, users.email FROM team_members
           JOIN users ON users.id = team_members.user_id
           WHERE team_members.team_id = ? ORDER BY users.name""",
        (team_id,),
    ).fetchall()
    return [{"id": r["id"], "name": r["name"], "email": r["email"]} for r in rows]


def _serialize(conn, team: dict) -> dict:
    return {
        "id": team["id"],
        "name": team["name"],
        "description": team["description"],
        "created_at": team["created_at"],
        "members": _members(conn, team["id"]),
    }


@router.get("")
def list_teams(user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        teams = conn.execute("SELECT * FROM teams WHERE org_id = ? ORDER BY name", (user["org_id"],)).fetchall()
        return [_serialize(conn, t) for t in teams]


@router.post("", status_code=201)
def create_team(payload: TeamCreate, admin: dict = Depends(require_admin)):
    with get_conn() as conn:
        if conn.execute(
            "SELECT id FROM teams WHERE org_id = ? AND name = ?", (admin["org_id"], payload.name)
        ).fetchone():
            raise HTTPException(status_code=409, detail="A team with that name already exists.")
        cur = conn.execute(
            "INSERT INTO teams (org_id, name, description) VALUES (?, ?, ?)",
            (admin["org_id"], payload.name, payload.description),
        )
        team = conn.execute("SELECT * FROM teams WHERE id = ?", (cur.lastrowid,)).fetchone()
        result = _serialize(conn, team)

    log_action(admin["org_id"], "team.created", actor=admin, target_type="team", target_id=team["id"], detail=payload.name)
    return result


@router.patch("/{team_id}")
def update_team(team_id: int, payload: TeamUpdate, admin: dict = Depends(require_admin)):
    with get_conn() as conn:
        team = conn.execute("SELECT * FROM teams WHERE id = ? AND org_id = ?", (team_id, admin["org_id"])).fetchone()
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")

        fields, values = [], []
        if payload.name is not None:
            fields.append("name = ?"); values.append(payload.name)
        if payload.description is not None:
            fields.append("description = ?"); values.append(payload.description)
        if fields:
            values.append(team_id)
            conn.execute(f"UPDATE teams SET {', '.join(fields)} WHERE id = ?", values)
        team = conn.execute("SELECT * FROM teams WHERE id = ?", (team_id,)).fetchone()
        result = _serialize(conn, team)

    log_action(admin["org_id"], "team.updated", actor=admin, target_type="team", target_id=team_id, detail=team["name"])
    return result


@router.delete("/{team_id}", status_code=204)
def delete_team(team_id: int, admin: dict = Depends(require_admin)):
    with get_conn() as conn:
        team = conn.execute("SELECT * FROM teams WHERE id = ? AND org_id = ?", (team_id, admin["org_id"])).fetchone()
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")
        conn.execute("DELETE FROM teams WHERE id = ?", (team_id,))

    log_action(admin["org_id"], "team.deleted", actor=admin, target_type="team", target_id=team_id, detail=team["name"])
    return None


@router.post("/{team_id}/members", status_code=201)
def add_member(team_id: int, payload: MemberAdd, admin: dict = Depends(require_admin)):
    with get_conn() as conn:
        team = conn.execute("SELECT * FROM teams WHERE id = ? AND org_id = ?", (team_id, admin["org_id"])).fetchone()
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")
        member = conn.execute(
            "SELECT * FROM users WHERE id = ? AND org_id = ?", (payload.user_id, admin["org_id"])
        ).fetchone()
        if not member:
            raise HTTPException(status_code=404, detail="User not found")
        conn.execute(
            "INSERT OR IGNORE INTO team_members (team_id, user_id) VALUES (?, ?)", (team_id, payload.user_id)
        )
        team = conn.execute("SELECT * FROM teams WHERE id = ?", (team_id,)).fetchone()
        result = _serialize(conn, team)

    log_action(admin["org_id"], "team.member_added", actor=admin, target_type="team", target_id=team_id, detail=member["email"])
    return result


@router.delete("/{team_id}/members/{user_id}")
def remove_member(team_id: int, user_id: int, admin: dict = Depends(require_admin)):
    with get_conn() as conn:
        team = conn.execute("SELECT * FROM teams WHERE id = ? AND org_id = ?", (team_id, admin["org_id"])).fetchone()
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")
        conn.execute("DELETE FROM team_members WHERE team_id = ? AND user_id = ?", (team_id, user_id))
        team = conn.execute("SELECT * FROM teams WHERE id = ?", (team_id,)).fetchone()
        result = _serialize(conn, team)

    log_action(admin["org_id"], "team.member_removed", actor=admin, target_type="team", target_id=team_id, detail=str(user_id))
    return result
