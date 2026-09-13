/* config.js — one place to point the frontend at the backend.
   Change API_BASE if you run the FastAPI backend on a different host/port. */
window.PORTAL_CONFIG = {
  // Deployed FastAPI backend for this portal (Railway service
  // "AuditPulse-Access" — see PORTAL_BASE_URL in its Railway variables).
  API_BASE: 'https://auditpulse-access-production.up.railway.app/api',

  // Where AuditPulse's own frontend is hosted (its dashboard.html etc.),
  // for the sidebar's "Back to AuditPulse" link and each row's "Open in
  // AuditPulse" action. This is AuditPulse's Vercel deployment, taken
  // from that service's own CORS_ORIGINS_RAW value in Railway.
  AUDITPULSE_URL: 'https://auditpulse-ala6.vercel.app',

  // This frontend's own base URL (no trailing slash) — sso.py's
  // callback redirects the browser to `${FRONTEND_BASE_URL}/sso-callback.html`
  // once SSO sign-in completes at the IdP, so this only matters if you've
  // deployed the frontend somewhere other than what the backend's own
  // FRONTEND_BASE_URL env var already assumes. Leave as-is for local dev
  // (`python -m http.server 5500` from /frontend).
  FRONTEND_BASE_URL: window.location.origin
};
