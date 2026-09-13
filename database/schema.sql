-- ============================================================================
-- AuditPulse Access Portal — Phase 5 schema
-- Grew from Phase 1's two tables (roles, users) into a proper multi-tenant
-- shape: every table below carries org_id (directly, or via a parent that
-- does), so one deployment safely serves many isolated organisations.
-- Applied via backend/database.py's PGConnection.executescript() against
-- Postgres (e.g. Supabase) — plain SQL, no ORM, no migration tool — see
-- backend/database.py's docstring for why that's still fine at this size.
--
-- (Previously written in SQLite syntax — INTEGER PRIMARY KEY AUTOINCREMENT,
-- datetime('now') — left over from before database.py switched to
-- psycopg2/Postgres. That syntax is invalid in Postgres and made
-- init_db() throw a syntax error on every startup. Converted below to
-- SERIAL / TIMESTAMPTZ DEFAULT NOW(), which Postgres actually accepts.)
-- ============================================================================

CREATE TABLE IF NOT EXISTS organisations (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    slug        TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Roles are per-organisation now (Phase 1 had one shared, global set).
-- The four original roles (Admin/Auditor/Reviewer/Viewer) are seeded as
-- is_system=1 for every org; an org's admin can still edit their
-- permissions, just not delete them or rename them out from under the
-- product's own defaults. Anything else an admin creates is a custom role.
CREATE TABLE IF NOT EXISTS roles (
    id          SERIAL PRIMARY KEY,
    org_id      INTEGER NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    is_system   INTEGER NOT NULL DEFAULT 0 CHECK (is_system IN (0, 1)),
    is_admin    INTEGER NOT NULL DEFAULT 0 CHECK (is_admin IN (0, 1)),
    UNIQUE (org_id, name)
);

CREATE INDEX IF NOT EXISTS idx_roles_org_id ON roles(org_id);

-- Replaces roles.py's old hardcoded PERMISSIONS dict — one row per
-- (role, module). A module missing a row is treated as not allowed.
CREATE TABLE IF NOT EXISTS permissions (
    id       SERIAL PRIMARY KEY,
    role_id  INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    module   TEXT NOT NULL,
    allowed  INTEGER NOT NULL DEFAULT 0 CHECK (allowed IN (0, 1)),
    UNIQUE (role_id, module)
);

CREATE INDEX IF NOT EXISTS idx_permissions_role_id ON permissions(role_id);

-- ---- SSO (Phase 5) ----
-- One row per org (at most) — a single configured OIDC provider. The
-- client is deliberately generic (issuer + client_id/secret, discovered
-- via /.well-known/openid-configuration) so it works unmodified against
-- Okta, Google Workspace, Azure AD/Entra, Auth0, or anything else that
-- speaks standard OIDC — see backend/sso.py. Declared before `users`
-- since users.sso_provider_id references it.
CREATE TABLE IF NOT EXISTS sso_providers (
    id             SERIAL PRIMARY KEY,
    org_id         INTEGER NOT NULL UNIQUE REFERENCES organisations(id) ON DELETE CASCADE,
    label          TEXT NOT NULL DEFAULT 'Single Sign-On',
    issuer         TEXT NOT NULL,
    client_id      TEXT NOT NULL,
    client_secret  TEXT NOT NULL,
    enabled        INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS users (
    id                     SERIAL PRIMARY KEY,
    org_id                 INTEGER NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    name                   TEXT NOT NULL,
    email                  TEXT NOT NULL,
    role_id                INTEGER NOT NULL REFERENCES roles(id),
    status                 TEXT NOT NULL DEFAULT 'Pending' CHECK (status IN ('Active', 'Pending', 'Disabled')),
    auditpulse_access      INTEGER NOT NULL DEFAULT 0 CHECK (auditpulse_access IN (0, 1)),
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- ---- Portal auth (Phase 5) ----
    password_hash          TEXT,
    must_change_password   INTEGER NOT NULL DEFAULT 0 CHECK (must_change_password IN (0, 1)),

    -- ---- MFA (Phase 5) ----
    mfa_enabled            INTEGER NOT NULL DEFAULT 0 CHECK (mfa_enabled IN (0, 1)),
    mfa_secret             TEXT,

    -- ---- SSO (Phase 5) ----
    -- Set once a user has ever signed in via an org's SSO provider (either
    -- JIT-provisioned there, or an existing account that later linked it).
    -- NULL means "portal credentials only".
    sso_provider_id        INTEGER REFERENCES sso_providers(id) ON DELETE SET NULL,

    -- Two users in *different* orgs are allowed to share an email — the
    -- org slug is what disambiguates them at login — but not within the
    -- same org.
    UNIQUE (org_id, email)
);

CREATE INDEX IF NOT EXISTS idx_users_org_id ON users(org_id);
CREATE INDEX IF NOT EXISTS idx_users_role_id ON users(role_id);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

-- ---- Teams (Phase 5) ----
CREATE TABLE IF NOT EXISTS teams (
    id          SERIAL PRIMARY KEY,
    org_id      INTEGER NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (org_id, name)
);

CREATE INDEX IF NOT EXISTS idx_teams_org_id ON teams(org_id);

CREATE TABLE IF NOT EXISTS team_members (
    team_id  INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (team_id, user_id)
);

-- ---- Access logs (Phase 5) ----
-- Who did what to access/permissions — distinct from AuditPulse's own
-- product-activity History log. Never raises on write failure; see
-- backend/access_logs.py's log_action().
CREATE TABLE IF NOT EXISTS access_logs (
    id             SERIAL PRIMARY KEY,
    org_id         INTEGER NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    actor_user_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    actor_label    TEXT NOT NULL DEFAULT 'system',
    action         TEXT NOT NULL,
    target_type    TEXT,
    target_id      INTEGER,
    detail         TEXT NOT NULL DEFAULT '',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_access_logs_org_id ON access_logs(org_id);
CREATE INDEX IF NOT EXISTS idx_access_logs_created_at ON access_logs(created_at);
