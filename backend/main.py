"""
main.py

FastAPI entry point for the AuditPulse Access Portal backend (Phase 5).

Run locally:
    cd backend
    pip install -r requirements.txt
    uvicorn main:app --reload --port 8010

The frontend (frontend/js/config.js) defaults to http://localhost:8010/api,
so running on port 8010 means no config changes are needed for local dev.
"""

import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import init_db
from roles import router as roles_router
from users import router as users_router
from auditpulse import router as auditpulse_router
from roadmap import router as roadmap_router
from auth import router as auth_router
from mfa import router as mfa_router
from sso import router as sso_router
from teams import router as teams_router
from organisations import router as organisations_router
from access_logs import router as access_logs_router

load_dotenv()

# Comma-separated list of allowed frontend origins, e.g.
#   CORS_ORIGINS_RAW=http://localhost:5500,https://auditpulse-access.example.vercel.app
# Stored as a raw string (not JSON) so it's a plain env var to set on
# Railway/etc., same pattern as AuditPulse/backend's CORS_ORIGINS_RAW.
# Defaults to the frontend's local-dev origin (see js/config.js's
# FRONTEND_BASE_URL / this file's own PORTAL_BASE_URL default) so local
# dev keeps working out of the box; set the real var before deploying
# anywhere shared — do NOT leave this on "*" once the frontend and API
# are both reachable over the network.
CORS_ORIGINS_RAW = os.getenv("CORS_ORIGINS_RAW", "http://localhost:5500")
CORS_ORIGINS = [origin.strip() for origin in CORS_ORIGINS_RAW.split(",") if origin.strip()]

app = FastAPI(
    title="AuditPulse Access Portal",
    description="Phase 5: users, roles/permissions, teams, orgs, SSO, MFA, and access logs.",
    version="0.5.0",
)

# The frontend is static HTML/JS served separately (e.g. `python -m http.server`
# from /frontend, or opened directly as a file, or its own Vercel deploy in
# production), so it's a different origin from this API and needs CORS
# headers. Origins come from CORS_ORIGINS_RAW (see above) rather than "*" —
# this API sits behind auth but still shouldn't accept cross-origin
# requests from arbitrary sites, since it handles users/roles/orgs/SSO/MFA.
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    # The frontend sends its token via an `Authorization: Bearer ...` header
    # (js/app.js, localStorage-backed) rather than a cookie, so requests
    # aren't "credentialed" in the fetch/XHR sense and this can stay False.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/api/health")
def health():
    return {"status": "ok"}


app.include_router(users_router)
app.include_router(roles_router)
app.include_router(auditpulse_router)
app.include_router(roadmap_router)
app.include_router(auth_router)
app.include_router(mfa_router)
app.include_router(sso_router)
app.include_router(teams_router)
app.include_router(organisations_router)
app.include_router(access_logs_router)
