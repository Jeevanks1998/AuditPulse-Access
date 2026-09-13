/* ==========================================================================
   access-logs.js — access-logs.html. GET /api/access-logs is admin-only
   on the backend, so this whole page gates itself on Api.me().is_admin
   rather than letting non-admins hit a 403 on load.
   Depends on window.Portal from app.js (loaded first).
   ========================================================================== */

(function () {
  var P = window.Portal;
  if (!P) return;

  var PAGE_SIZE = 50;
  var state = { q: '', action: '', offset: 0, total: 0 };
  var searchTimer = null;

  var toolbar = document.querySelector('.logs-toolbar');
  var cardEl = document.querySelector('.card');
  var pagerEl = P.qs('#logsPager');
  var adminOnlyNotice = P.qs('#logsAdminOnlyNotice');

  var tbody = P.qs('#logsTbody');
  var emptyState = P.qs('#logsEmpty');
  var searchInput = P.qs('#logSearch');
  var actionFilter = P.qs('#logActionFilter');
  var prevBtn = P.qs('#logsPrevBtn');
  var nextBtn = P.qs('#logsNextBtn');
  var pagerLabel = P.qs('#logsPagerLabel');

  function formatWhen(iso) {
    if (!iso) return '—';
    var d = new Date(iso.indexOf('Z') >= 0 || iso.indexOf('+') >= 0 ? iso : iso + 'Z');
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleString(undefined, {
      year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
    });
  }

  function renderRows(items) {
    tbody.innerHTML = '';
    emptyState.hidden = items.length > 0;
    items.forEach(function (row) {
      var tr = document.createElement('tr');
      var target = row.target_type
        ? P.escapeHtml(row.target_type) + (row.target_id != null ? ' #' + row.target_id : '')
        : '—';
      tr.innerHTML =
        '<td class="mono text-sm">' + P.escapeHtml(formatWhen(row.created_at)) + '</td>' +
        '<td>' + P.escapeHtml(row.actor || 'system') + '</td>' +
        '<td><span class="log-action-tag">' + P.escapeHtml(row.action) + '</span></td>' +
        '<td>' + target + '</td>' +
        '<td class="text-sm text-tertiary">' + P.escapeHtml(row.detail || '') + '</td>';
      tbody.appendChild(tr);
    });
  }

  function updatePager() {
    var hasAny = state.total > 0;
    pagerEl.hidden = !hasAny || state.total <= PAGE_SIZE;
    prevBtn.disabled = state.offset <= 0;
    nextBtn.disabled = state.offset + PAGE_SIZE >= state.total;
    var from = state.total === 0 ? 0 : state.offset + 1;
    var to = Math.min(state.offset + PAGE_SIZE, state.total);
    pagerLabel.textContent = from + '–' + to + ' of ' + state.total;
  }

  function load() {
    P.Api.listAccessLogs({
      q: state.q || undefined,
      action: state.action || undefined,
      limit: PAGE_SIZE,
      offset: state.offset
    }).then(function (res) {
      state.total = res.total;
      renderRows(res.items);
      updatePager();
    }).catch(function (err) {
      tbody.innerHTML = '';
      emptyState.hidden = false;
      emptyState.querySelector('p').textContent = 'Could not load access logs — ' + err.message;
    });
  }

  function loadActions() {
    P.Api.listAccessLogActions().then(function (actions) {
      actionFilter.innerHTML = '<option value="">All actions</option>' + actions.map(function (a) {
        return '<option value="' + P.escapeHtml(a) + '">' + P.escapeHtml(a) + '</option>';
      }).join('');
    }).catch(function () { /* filter just stays at "All actions" */ });
  }

  function showAdminOnly() {
    if (toolbar) toolbar.hidden = true;
    if (cardEl) cardEl.hidden = true;
    pagerEl.hidden = true;
    adminOnlyNotice.hidden = false;
  }

  document.addEventListener('DOMContentLoaded', function () {
    if (document.body.dataset.page !== 'access-logs') return;

    P.Api.me().then(function (user) {
      if (!user.is_admin) { showAdminOnly(); return; }
      loadActions();
      load();
    }).catch(function () { /* requireAuth already redirects on 401 */ });

    P.on(searchInput, 'input', function () {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(function () {
        state.q = searchInput.value.trim();
        state.offset = 0;
        load();
      }, 300);
    });

    P.on(actionFilter, 'change', function () {
      state.action = actionFilter.value;
      state.offset = 0;
      load();
    });

    P.on(prevBtn, 'click', function () {
      state.offset = Math.max(0, state.offset - PAGE_SIZE);
      load();
    });

    P.on(nextBtn, 'click', function () {
      state.offset = state.offset + PAGE_SIZE;
      load();
    });
  });
})();
