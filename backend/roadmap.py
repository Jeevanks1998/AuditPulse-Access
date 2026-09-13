"""
roadmap.py

Used to be six 501-Not-Implemented stubs for "everything on the later
list". Phase 5 built all six, so this file's job now is just to say so —
GET /api/roadmap reports each item as shipped and where it lives, so
roadmap.html can retire the "not built yet" framing without every caller
of the old endpoint breaking.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/roadmap", tags=["roadmap (Phase 5 — shipped)"])

ITEMS = [
    {
        "id": "permissions",
        "name": "Custom Permissions",
        "status": "shipped",
        "summary": "A per-role, per-module permission matrix, editable from Roles — backed by the `permissions` table instead of a hardcoded dict.",
        "where": "roles.html — edit any role's permission matrix; create custom roles beyond the original four.",
    },
    {
        "id": "teams",
        "name": "Teams",
        "status": "shipped",
        "summary": "Group users into teams so access/ownership can be scoped to a team, not just an individual or the whole org.",
        "where": "teams.html — create teams and add/remove members.",
    },
    {
        "id": "sso",
        "name": "SSO",
        "status": "shipped",
        "summary": "Sign in via any OIDC-compliant identity provider (Okta, Google Workspace, Azure AD/Entra, Auth0, ...), configured per organisation.",
        "where": "organisation.html — configure a provider; login.html — \"Sign in with…\" buttons appear once one's configured.",
    },
    {
        "id": "mfa",
        "name": "MFA",
        "status": "shipped",
        "summary": "TOTP-based second factor at sign-in, on top of a password.",
        "where": "account.html — enroll/disable; enforced automatically at login once enabled.",
    },
    {
        "id": "access-logs",
        "name": "Access Logs",
        "status": "shipped",
        "summary": "A searchable trail of every access-affecting action — who created/updated/deleted a user, changed a role, or signed in — distinct from AuditPulse's own product History log.",
        "where": "access-logs.html — search and filter by action.",
    },
    {
        "id": "multi-org",
        "name": "Multiple Organisations",
        "status": "shipped",
        "summary": "Every table is scoped by org_id; anyone can self-serve a new, fully isolated organisation via signup instead of one implicit org per deployment.",
        "where": "signup.html creates a new org; organisation.html manages the caller's own.",
    },
]


@router.get("")
def list_roadmap_items():
    return ITEMS
