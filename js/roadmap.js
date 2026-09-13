/* ==========================================================================
   roadmap.js — Roadmap page: read-only cards for the Phase 5 items
   (backend/roadmap.py). Nothing here is interactive on purpose — every
   card just explains what the feature would do and what has to be built
   first, per the same list in README.md's "Roadmap (not built yet, on
   purpose)" section.
   ========================================================================== */

(function () {
  var P = window.Portal;
  if (!P) return;

  var ICONS = {
    permissions: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="10" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>',
    teams: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
    sso: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><path d="M10 17l5-5-5-5"/><path d="M15 12H3"/></svg>',
    mfa: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="2" width="14" height="20" rx="2"/><path d="M12 18h.01"/><path d="M9 6h6"/></svg>',
    'access-logs': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 3v6h6M12 7v5l4 2"/></svg>',
    'multi-org': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></svg>'
  };

  var LINKS = {
    permissions: 'roles.html', teams: 'teams.html', sso: 'organisation.html',
    mfa: 'account.html', 'access-logs': 'access-logs.html', 'multi-org': 'organisation.html'
  };

  function renderCards(items) {
    var grid = P.qs('#roadmapGrid');
    grid.innerHTML = items.map(function (item) {
      var href = LINKS[item.id] || 'index.html';
      return '<a class="roadmap-card" href="' + href + '">' +
        '<div class="roadmap-card__top">' +
          '<div class="roadmap-card__icon">' + (ICONS[item.id] || ICONS.permissions) + '</div>' +
          '<span class="badge badge--success">Shipped</span>' +
        '</div>' +
        '<div class="roadmap-card__name">' + P.escapeHtml(item.name) + '</div>' +
        '<p class="roadmap-card__desc">' + P.escapeHtml(item.summary) + '</p>' +
        '<p class="roadmap-card__unlocks"><strong>Where:</strong> ' + P.escapeHtml(item.where) + '</p>' +
      '</a>';
    }).join('');
  }

  function load() {
    P.Api.listRoadmap().then(renderCards).catch(function (err) {
      P.toast('Could not load the roadmap — ' + err.message, 'error');
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    if (document.body.dataset.page !== 'roadmap') return;
    load();
  });
})();
