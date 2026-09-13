/* ==========================================================================
   app.js — shared shell logic (sidebar, nav highlighting, toasts, modal
   helpers, tiny fetch wrapper) plus the Dashboard page's own rendering,
   since index.html doesn't get a dedicated script file.

   Exposes window.Portal for users.js / roles.js to reuse.
   ========================================================================== */

window.Portal = (function () {
  var API_BASE = window.PORTAL_CONFIG ? window.PORTAL_CONFIG.API_BASE : 'http://localhost:8010/api';
  var TOKEN_KEY = 'auditpulse_access_token';
  var USER_CACHE_KEY = 'auditpulse_access_user';

  /* ------------------------------ session ------------------------------ */
  function getToken() { return localStorage.getItem(TOKEN_KEY); }
  function setToken(token) { localStorage.setItem(TOKEN_KEY, token); }
  function clearSession() { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(USER_CACHE_KEY); }
  function getCachedUser() {
    try { return JSON.parse(localStorage.getItem(USER_CACHE_KEY) || 'null'); } catch (e) { return null; }
  }
  function setCachedUser(user) { localStorage.setItem(USER_CACHE_KEY, JSON.stringify(user)); }

  // Pages that don't require a session — everything else redirects to
  // login.html when there's no token, or when a request comes back 401.
  var PUBLIC_PAGES = ['login.html', 'signup.html', 'sso-callback.html'];

  function currentPage() { return (window.location.pathname.split('/').pop() || 'index.html'); }

  function goToLogin() {
    clearSession();
    if (PUBLIC_PAGES.indexOf(currentPage()) === -1) {
      window.location.href = 'login.html';
    }
  }

  function requireAuth() {
    if (PUBLIC_PAGES.indexOf(currentPage()) >= 0) return;
    if (!getToken()) { window.location.href = 'login.html'; }
  }

  /* ------------------------------ DOM ------------------------------ */
  function qs(sel, root) { return (root || document).querySelector(sel); }
  function qsa(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function on(el, ev, fn) { if (el) el.addEventListener(ev, fn); }

  function escapeHtml(str) {
    if (str == null) return '';
    return String(str)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function initials(name) {
    if (!name) return '?';
    var parts = name.trim().split(/\s+/);
    var first = parts[0] ? parts[0][0] : '';
    var last = parts.length > 1 ? parts[parts.length - 1][0] : '';
    return (first + last).toUpperCase();
  }

  function timeAgo(iso) {
    if (!iso) return '—';
    var diff = (Date.now() - new Date(iso).getTime()) / 1000;
    if (diff < 60) return 'just now';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    return Math.floor(diff / 86400) + 'd ago';
  }

  /* ---------------------------- fetch wrapper ---------------------------- */
  function request(path, options) {
    options = options || {};
    var headers = Object.assign({ 'Content-Type': 'application/json' }, options.headers || {});
    var token = getToken();
    if (token && !options.noAuth) headers['Authorization'] = 'Bearer ' + token;
    return fetch(API_BASE + path, {
      method: options.method || 'GET',
      headers: headers,
      body: options.body ? JSON.stringify(options.body) : undefined
    }).then(function (res) {
      if (res.status === 204) return {};
      return res.json().catch(function () { return {}; }).then(function (data) {
        if (!res.ok) {
          if (res.status === 401 && !options.noAuth) { goToLogin(); }
          var msg = (data && (data.detail || data.message)) || ('Request failed (' + res.status + ')');
          throw new Error(msg);
        }
        return data;
      });
    });
  }

  var Api = {
    // ---- auth ----
    signup: function (payload) { return request('/auth/signup', { method: 'POST', body: payload, noAuth: true }); },
    login: function (payload) { return request('/auth/login', { method: 'POST', body: payload, noAuth: true }); },
    verifyMfaLogin: function (payload) { return request('/auth/mfa/verify', { method: 'POST', body: payload, noAuth: true }); },
    me: function () { return request('/auth/me'); },
    changePassword: function (payload) { return request('/auth/change-password', { method: 'POST', body: payload }); },
    // ---- mfa ----
    mfaEnroll: function () { return request('/auth/mfa/enroll', { method: 'POST' }); },
    mfaEnable: function (payload) { return request('/auth/mfa/enable', { method: 'POST', body: payload }); },
    mfaDisable: function (payload) { return request('/auth/mfa/disable', { method: 'POST', body: payload }); },
    // ---- sso ----
    ssoPublicConfig: function (orgSlug) { return request('/sso/' + encodeURIComponent(orgSlug) + '/config', { noAuth: true }); },
    ssoAuthorizeUrl: function (orgSlug) { return API_BASE + '/sso/' + encodeURIComponent(orgSlug) + '/authorize'; },
    ssoGetConfig: function () { return request('/sso/config'); },
    ssoSetConfig: function (payload) { return request('/sso/config', { method: 'PUT', body: payload }); },
    ssoDeleteConfig: function () { return request('/sso/config', { method: 'DELETE' }); },
    // ---- users ----
    listUsers: function (query) { return request('/users' + (query ? '?q=' + encodeURIComponent(query) : '')); },
    userStats: function () { return request('/users/stats'); },
    createUser: function (payload) { return request('/users', { method: 'POST', body: payload }); },
    updateUser: function (id, payload) { return request('/users/' + id, { method: 'PATCH', body: payload }); },
    deleteUser: function (id) { return request('/users/' + id, { method: 'DELETE' }); },
    // ---- roles ----
    listRoles: function () { return request('/roles'); },
    getRole: function (id) { return request('/roles/' + id); },
    listModules: function () { return request('/roles/modules'); },
    createRole: function (payload) { return request('/roles', { method: 'POST', body: payload }); },
    updateRole: function (id, payload) { return request('/roles/' + id, { method: 'PATCH', body: payload }); },
    deleteRole: function (id) { return request('/roles/' + id, { method: 'DELETE' }); },
    // ---- teams ----
    listTeams: function () { return request('/teams'); },
    createTeam: function (payload) { return request('/teams', { method: 'POST', body: payload }); },
    updateTeam: function (id, payload) { return request('/teams/' + id, { method: 'PATCH', body: payload }); },
    deleteTeam: function (id) { return request('/teams/' + id, { method: 'DELETE' }); },
    addTeamMember: function (teamId, userId) { return request('/teams/' + teamId + '/members', { method: 'POST', body: { user_id: userId } }); },
    removeTeamMember: function (teamId, userId) { return request('/teams/' + teamId + '/members/' + userId, { method: 'DELETE' }); },
    // ---- access logs ----
    listAccessLogs: function (params) {
      params = params || {};
      var qp = [];
      if (params.q) qp.push('q=' + encodeURIComponent(params.q));
      if (params.action) qp.push('action=' + encodeURIComponent(params.action));
      if (params.limit) qp.push('limit=' + params.limit);
      if (params.offset) qp.push('offset=' + params.offset);
      return request('/access-logs' + (qp.length ? '?' + qp.join('&') : ''));
    },
    listAccessLogActions: function () { return request('/access-logs/actions'); },
    // ---- organisations ----
    myOrganisation: function () { return request('/organisations/me'); },
    updateMyOrganisation: function (payload) { return request('/organisations/me', { method: 'PATCH', body: payload }); },
    // ---- misc ----
    auditpulseStatus: function () { return request('/auditpulse/status'); },
    listRoadmap: function () { return request('/roadmap'); }
  };

  /* ------------------------------- toasts ------------------------------- */
  function toast(message, type) {
    var stack = qs('.toast-stack');
    if (!stack) {
      stack = document.createElement('div');
      stack.className = 'toast-stack';
      document.body.appendChild(stack);
    }
    var el = document.createElement('div');
    el.className = 'toast' + (type ? ' toast--' + type : '');
    el.textContent = message;
    stack.appendChild(el);
    setTimeout(function () {
      el.style.opacity = '0';
      el.style.transition = 'opacity 200ms ease-out';
      setTimeout(function () { el.remove(); }, 220);
    }, 2600);
  }

  /* -------------------------------- modal -------------------------------- */
  function openModal(id) { var m = qs('#' + id); if (m) m.classList.add('is-open'); }
  function closeModal(id) { var m = qs('#' + id); if (m) m.classList.remove('is-open'); }

  function wireModalDismiss() {
    qsa('[data-modal-close]').forEach(function (btn) {
      on(btn, 'click', function () { closeModal(btn.getAttribute('data-modal-close')); });
    });
    qsa('.modal-overlay').forEach(function (overlay) {
      on(overlay, 'click', function (e) { if (e.target === overlay) overlay.classList.remove('is-open'); });
    });
    on(document, 'keydown', function (e) {
      if (e.key === 'Escape') qsa('.modal-overlay.is-open').forEach(function (m) { m.classList.remove('is-open'); });
    });
  }

  /* ------------------------------- sidebar -------------------------------- */
  function initSidebar() {
    var sidebar = qs('#sidebar');
    var backdrop = qs('#sidebarBackdrop');
    var toggle = qs('#sidebarToggle');
    if (!sidebar) return;
    function openSidebar() { sidebar.classList.add('is-open'); backdrop && backdrop.classList.add('is-open'); }
    function closeSidebar() { sidebar.classList.remove('is-open'); backdrop && backdrop.classList.remove('is-open'); }
    on(toggle, 'click', function () { sidebar.classList.contains('is-open') ? closeSidebar() : openSidebar(); });
    on(backdrop, 'click', closeSidebar);
    qsa('.sidebar__link', sidebar).forEach(function (link) { on(link, 'click', closeSidebar); });
  }

  function highlightActiveNav() {
    var path = window.location.pathname.split('/').pop() || 'index.html';
    qsa('.sidebar__link').forEach(function (link) {
      var href = (link.getAttribute('href') || '').split('/').pop();
      link.classList.toggle('is-active', href === path);
    });
  }

  /* ---- close any open row-menu when clicking elsewhere (shared by users.js) ---- */
  function initGlobalMenuDismiss() {
    on(document, 'click', function (e) {
      qsa('.menu.is-open').forEach(function (menu) {
        if (!menu.parentElement.contains(e.target)) menu.classList.remove('is-open');
      });
    });
  }

  /* ---- "Back to AuditPulse" link — inert until AUDITPULSE_URL is set ---- */
  function wireAuditPulseLink() {
    var link = qs('.sidebar__link--external');
    if (!link) return;
    var url = window.PORTAL_CONFIG && window.PORTAL_CONFIG.AUDITPULSE_URL;
    if (url) {
      link.href = url;
      link.target = '_blank';
      link.rel = 'noopener';
      link.removeAttribute('title');
    } else {
      link.title = 'Set AUDITPULSE_URL in js/config.js to enable this link';
      link.setAttribute('aria-disabled', 'true');
    }
  }

  /* ---- profile chip: real signed-in user, "Account settings" + "Log out" ---- */
  function initProfileMenu() {
    var wrap = qs('#profileMenuWrap');
    var trigger = qs('#profileMenuTrigger');
    if (!wrap || !trigger) return;
    var menu = qs('.menu', wrap);
    on(trigger, 'click', function (e) {
      e.stopPropagation();
      qsa('.menu.is-open').forEach(function (m) { if (m !== menu) m.classList.remove('is-open'); });
      menu.classList.toggle('is-open');
    });
    on(qs('#profileAccountLink'), 'click', function () { window.location.href = 'account.html'; });
    on(qs('#profileLogoutBtn'), 'click', function () { clearSession(); window.location.href = 'login.html'; });
  }

  function renderProfile() {
    var avatar = qs('#profileAvatar');
    var nameEl = qs('#profileName');
    if (!avatar || !nameEl) return;
    var cached = getCachedUser();
    if (cached) { avatar.textContent = initials(cached.name); nameEl.textContent = cached.name; }
    Api.me().then(function (user) {
      setCachedUser(user);
      avatar.textContent = initials(user.name);
      nameEl.textContent = user.name;
    }).catch(function () { /* a 401 here already redirects via request()'s goToLogin */ });
  }

  document.addEventListener('DOMContentLoaded', function () {
    requireAuth();
    initSidebar();
    highlightActiveNav();
    wireModalDismiss();
    initGlobalMenuDismiss();
    wireAuditPulseLink();
    initProfileMenu();
    renderProfile();
    if (document.body.dataset.page === 'dashboard') initDashboard();
  });

  /* ============================ Dashboard page ============================ */
  function roleClass(roleName) {
    var key = (roleName || '').toLowerCase();
    return ['admin', 'auditor', 'reviewer', 'viewer'].indexOf(key) >= 0 ? key : 'viewer';
  }

  function statusBadge(status) {
    if (status === 'Active') return '<span class="badge badge--success">Active</span>';
    if (status === 'Pending') return '<span class="badge badge--warning">Pending</span>';
    return '<span class="badge badge--neutral">Disabled</span>';
  }

  /* AuditPulse sync indicator — u.auditpulse_sync is {ok, detail, at} | null
     (see backend/auditpulse.py). null means "not synced yet this session",
     distinct from ok:false, which means a sync was attempted and failed. */
  function syncIndicator(sync) {
    if (!sync || sync.ok == null) {
      return '<span class="sync-dot sync-dot--none" title="Not synced yet">·</span>';
    }
    if (sync.ok) {
      return '<span class="sync-dot sync-dot--ok" title="' + escapeHtml(sync.detail) + '">&#10003;</span>';
    }
    return '<span class="sync-dot sync-dot--error" title="' + escapeHtml(sync.detail) + '">&#33;</span>';
  }

  function initDashboard() {
    var statUsers = qs('#statTotalUsers');
    var statActive = qs('#statActiveUsers');
    var statPending = qs('#statPendingUsers');
    var accessLine = qs('#accessSummaryLine');
    var recentList = qs('#recentUsersList');
    var connectionLine = qs('#connectionStatusLine');
    var orgLine = qs('#orgSummaryLine');

    if (orgLine) {
      Api.myOrganisation().then(function (org) {
        orgLine.textContent = org.name + ' — ' + org.user_count + ' user' + (org.user_count === 1 ? '' : 's') +
          ', ' + org.team_count + ' team' + (org.team_count === 1 ? '' : 's') + ', ' + org.role_count + ' role' + (org.role_count === 1 ? '' : 's') + '.';
      }).catch(function (err) {
        orgLine.textContent = 'Could not load organisation — ' + err.message;
      });
    }

    if (connectionLine) {
      Api.auditpulseStatus().then(function (status) {
        if (!status.configured) {
          connectionLine.textContent = 'Not connected to AuditPulse — set AUDITPULSE_BASE_URL / AUDITPULSE_API_KEY in backend/.env.';
          connectionLine.className = 'connection-status connection-status--off';
        } else if (status.reachable) {
          connectionLine.textContent = 'Connected to AuditPulse.';
          connectionLine.className = 'connection-status connection-status--ok';
        } else {
          connectionLine.textContent = status.detail || 'Could not reach AuditPulse.';
          connectionLine.className = 'connection-status connection-status--error';
        }
      }).catch(function () {
        connectionLine.textContent = 'Could not check AuditPulse connection.';
        connectionLine.className = 'connection-status connection-status--error';
      });
    }

    Api.userStats().then(function (stats) {
      statUsers.textContent = stats.total;
      statActive.textContent = stats.active;
      statPending.textContent = stats.pending;
      accessLine.textContent = stats.total + ' user' + (stats.total === 1 ? '' : 's') +
        ' currently have access to AuditPulse.';
    }).catch(function (err) {
      toast('Could not load stats — ' + err.message, 'error');
    });

    Api.listUsers().then(function (users) {
      recentList.innerHTML = '';
      if (!users.length) {
        recentList.innerHTML = '<li class="empty-state">No users yet.</li>';
        return;
      }
      users.slice(0, 5).forEach(function (u) {
        var li = document.createElement('li');
        li.className = 'row-item';
        li.innerHTML =
          '<div class="row-item__avatar">' + escapeHtml(initials(u.name)) + '</div>' +
          '<div class="row-item__body">' +
            '<div class="row-item__title">' + escapeHtml(u.name) + '</div>' +
            '<div class="row-item__meta"><span class="role-pill role-pill--' + roleClass(u.role) + '">' + escapeHtml(u.role) + '</span></div>' +
          '</div>' +
          statusBadge(u.status);
        recentList.appendChild(li);
      });
    }).catch(function (err) {
      toast('Could not load users — ' + err.message, 'error');
    });
  }

  return {
    qs: qs, qsa: qsa, on: on,
    escapeHtml: escapeHtml, initials: initials, timeAgo: timeAgo,
    Api: Api, toast: toast,
    openModal: openModal, closeModal: closeModal,
    roleClass: roleClass, statusBadge: statusBadge, syncIndicator: syncIndicator,
    getToken: getToken, setToken: setToken, clearSession: clearSession,
    getCachedUser: getCachedUser, setCachedUser: setCachedUser,
    requireAuth: requireAuth, goToLogin: goToLogin
  };
})();
