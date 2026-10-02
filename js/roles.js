/* ==========================================================================
   roles.js — Roles page: read-only role cards + permission matrix.
   Phase 1 has no permission builder — permissions are defined in the
   backend (see backend/roles.py PERMISSIONS) and just rendered here.
   ========================================================================== */

(function () {
  var P = window.Portal;
  if (!P) return;

  var ICONS = {
    admin: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2 4 6v6c0 5 3.4 8.7 8 10 4.6-1.3 8-5 8-10V6l-8-4Z"/></svg>',
    auditor: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>',
    reviewer: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg>',
    viewer: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6"/></svg>'
  };

  var MODULES = ['dashboard', 'audits', 'analytics', 'reports', 'scheduler', 'settings'];
  var MODULE_LABELS = { dashboard: 'Dashboard', audits: 'Audits', analytics: 'Analytics', reports: 'Reports', scheduler: 'Scheduler', settings: 'Settings' };

  function permIcon(allowed) {
    return allowed
      ? '<span class="perm-icon perm-icon--yes"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg></span>'
      : '<span class="perm-icon perm-icon--no"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12"/></svg></span>';
  }

  function renderCards(roles) {
    var grid = P.qs('#rolesGrid');
    grid.innerHTML = roles.map(function (r) {
      var key = P.roleClass(r.name);
      return '<div class="role-card" data-role="' + key + '">' +
        '<div class="role-card__icon">' + (ICONS[key] || ICONS.viewer) + '</div>' +
        '<div class="role-card__name">' + P.escapeHtml(r.name) + '</div>' +
        '<p class="role-card__desc">' + P.escapeHtml(r.description) + '</p>' +
        '<div class="role-card__count"><span class="mono">' + r.user_count + '</span> user' + (r.user_count === 1 ? '' : 's') + '</div>' +
      '</div>';
    }).join('');
  }

  function renderMatrix(roles) {
    var thead = P.qs('#permTableHead');
    var tbody = P.qs('#permTableBody');

    thead.innerHTML = '<tr><th>Module</th>' + roles.map(function (r) {
      return '<th>' + P.escapeHtml(r.name) + '</th>';
    }).join('') + '</tr>';

    tbody.innerHTML = MODULES.map(function (mod) {
      return '<tr><td>' + MODULE_LABELS[mod] + '</td>' + roles.map(function (r) {
        return '<td>' + permIcon(!!(r.permissions && r.permissions[mod])) + '</td>';
      }).join('') + '</tr>';
    }).join('');
  }

  function load() {
    P.Api.listRoles().then(function (roles) {
      renderCards(roles);
      renderMatrix(roles);
    }).catch(function (err) {
      P.toast('Could not load roles — ' + err.message, 'error');
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    if (document.body.dataset.page !== 'roles') return;
    load();
  });
})();
