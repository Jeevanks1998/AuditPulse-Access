"""
organisations.py

"Multiple organisations" doesn't need a separate cross-org super-admin
console to be real — every table already carries org_id (see schema.sql)
and every query in users.py/roles.py/teams.py/access_logs.py is scoped
by the caller's own org_id, so one deployment already serves many
isolated orgs. What each org's own admin needs is a way to see and
rename *their* org, which is what this router is.

New orgs are created via self-service signup (auth.py's /auth/signup),
not provisioned centrally — anyone can spin up an isolated org for their
own team, same as most multi-tenant SaaS onboarding.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from access_logs import log_action
from auth_utils import get_current_user, require_admin
from database import get_conn

router = APIRouter(prefix="/api/organisations", tags=["organisations"])


class OrgUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=120)


def _serialize(org: dict, counts: dict) -> dict:
    return {
        "id": org["id"],
        "name": org["name"],
        "slug": org["slug"],
        "created_at": org["created_at"],
        "user_count": counts.get("users", 0),
        "team_count": counts.get("teams", 0),
        "role_count": counts.get("roles", 0),
    }


@router.get("/me")
def my_organisation(user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        org = conn.execute("SELECT * FROM organisations WHERE id = ?", (user["org_id"],)).fetchone()
        counts = {
            "users": conn.execute("SELECT COUNT(*) AS c FROM users WHERE org_id = ?", (user["org_id"],)).fetchone()["c"],
            "teams": conn.execute("SELECT COUNT(*) AS c FROM teams WHERE org_id = ?", (user["org_id"],)).fetchone()["c"],
            "roles": conn.execute("SELECT COUNT(*) AS c FROM roles WHERE org_id = ?", (user["org_id"],)).fetchone()["c"],
        }
    return _serialize(org, counts)


@router.patch("/me")
def update_my_organisation(payload: OrgUpdate, admin: dict = Depends(require_admin)):
    with get_conn() as conn:
        conn.execute("UPDATE organisations SET name = ? WHERE id = ?", (payload.name, admin["org_id"]))
        org = conn.execute("SELECT * FROM organisations WHERE id = ?", (admin["org_id"],)).fetchone()
        counts = {
            "users": conn.execute("SELECT COUNT(*) AS c FROM users WHERE org_id = ?", (admin["org_id"],)).fetchone()["c"],
            "teams": conn.execute("SELECT COUNT(*) AS c FROM teams WHERE org_id = ?", (admin["org_id"],)).fetchone()["c"],
            "roles": conn.execute("SELECT COUNT(*) AS c FROM roles WHERE org_id = ?", (admin["org_id"],)).fetchone()["c"],
        }

    log_action(admin["org_id"], "organisation.renamed", actor=admin, target_type="organisation", target_id=admin["org_id"], detail=payload.name)
    return _serialize(org, counts)
