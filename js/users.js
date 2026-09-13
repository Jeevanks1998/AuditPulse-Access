/* ==========================================================================
   users.js — Users page: list, search, create, edit, disable, delete.
   Depends on window.Portal from app.js (loaded first).
   ========================================================================== */

(function () {
  var P = window.Portal;
  if (!P) return;

  var state = { users: [], roles: [], query: '' };

  var tbody = P.qs('#usersTbody');
  var searchInput = P.qs('#userSearch');
  var emptyState = P.qs('#usersEmpty');
  var createBtn = P.qs('#openCreateUser');

  var form = P.qs('#userForm');
  var modalTitle = P.qs('#userModalTitle');
  var modalSubtitle = P.qs('#userModalSubtitle');
  var fieldName = P.qs('#fieldName');
  var fieldEmail = P.qs('#fieldEmail');
  var fieldPassword = P.qs('#fieldPassword');
  var fieldConfirmPassword = P.qs('#fieldConfirmPassword');
  var fieldRole = P.qs('#fieldRole');
  var fieldAccess = P.qs('#fieldAccess');
  var fieldStatus = P.qs('#fieldStatus');
  var saveBtn = P.qs('#userFormSave');
  var editingId = null;

  var confirmDeleteBtn = P.qs('#confirmDeleteBtn');
  var deleteTargetId = null;
  var deleteTargetName = P.qs('#deleteTargetName');

  /* ------------------------------ rendering ------------------------------ */

  function renderSkeleton() {
    tbody.innerHTML = '';
    for (var i = 0; i < 4; i++) {
      var tr = document.createElement('tr');
      tr.className = 'skeleton-row';
      tr.innerHTML = '<td colspan="5"><div class="skeleton-bar" style="width:100%;height:36px;"></div></td>';
      tbody.appendChild(tr);
    }
  }

  function matchesQuery(u, q) {
    if (!q) return true;
    q = q.toLowerCase();
    return u.name.toLowerCase().indexOf(q) >= 0 || u.email.toLowerCase().indexOf(q) >= 0 || u.role.toLowerCase().indexOf(q) >= 0;
  }

  function render() {
    var rows = state.users.filter(function (u) { return matchesQuery(u, state.query); });
    tbody.innerHTML = '';
    emptyState.hidden = rows.length > 0;

    rows.forEach(function (u) {
      var tr = document.createElement('tr');
      tr.dataset.id = u.id;
      tr.innerHTML =
        '<td>' +
          '<div class="user-cell">' +
            '<div class="user-cell__avatar">' + P.escapeHtml(P.initials(u.name)) + '</div>' +
            '<div><div class="user-cell__name">' + P.escapeHtml(u.name) + '</div>' +
            '<div class="user-cell__email">' + P.escapeHtml(u.email) + '</div></div>' +
          '</div>' +
        '</td>' +
        '<td><span class="role-pill role-pill--' + P.roleClass(u.role) + '">' + P.escapeHtml(u.role) + '</span></td>' +
        '<td>' + P.statusBadge(u.status) + '</td>' +
        '<td>' +
          '<div class="access-cell">' +
            '<label class="toggle">' +
              '<input type="checkbox" class="access-toggle" ' + (u.auditpulse_access ? 'checked' : '') + '>' +
              '<span class="toggle__track"></span>' +
            '</label>' +
            P.syncIndicator(u.auditpulse_sync) +
          '</div>' +
        '</td>' +
        '<td style="text-align:right;">' +
          '<div class="menu-wrap">' +
            '<button class="menu-trigger" aria-label="Row actions">' +
              '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="5" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="12" cy="19" r="1.2"/></svg>' +
            '</button>' +
            '<div class="menu">' +
              '<button class="menu__item js-edit"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>Edit user</button>' +
              '<button class="menu__item js-role"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-6 8-6s8 2 8 6"/></svg>Change role</button>' +
              '<div class="menu__divider"></div>' +
              '<button class="menu__item js-delete menu__item--danger"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>Delete user</button>' +
            '</div>' +
          '</div>' +
        '</td>';
      tbody.appendChild(tr);
    });
  }

  /* ------------------------------- data load ------------------------------ */

  function load() {
    renderSkeleton();
    return Promise.all([P.Api.listUsers(), P.Api.listRoles()]).then(function (res) {
      state.users = res[0];
      state.roles = res[1];
      populateRoleOptions();
      render();
    }).catch(function (err) {
      tbody.innerHTML = '';
      emptyState.hidden = false;
      emptyState.querySelector('p').textContent = 'Could not load users — ' + err.message;
    });
  }

  function populateRoleOptions() {
    fieldRole.innerHTML = state.roles.map(function (r) {
      return '<option value="' + P.escapeHtml(r.name) + '">' + P.escapeHtml(r.name) + '</option>';
    }).join('');
  }

  /* -------------------------------- create/edit form ------------------------------- */

  function resetForm() {
    editingId = null;
    form.reset();
    fieldAccess.checked = true;
    fieldStatus.value = 'Active';
    fieldPassword.placeholder = '••••••••';
    fieldConfirmPassword.placeholder = '••••••••';
    modalTitle.textContent = 'Create user';
    modalSubtitle.textContent = 'Add a person and grant them AuditPulse access.';
    saveBtn.textContent = 'Create user';
    P.qsa('.field__error', form).forEach(function (e) { e.classList.remove('is-visible'); });
    P.qsa('input, select', form).forEach(function (e) { e.classList.remove('is-invalid'); });
  }

  function openCreate() {
    resetForm();
    P.openModal('userModal');
    fieldName.focus();
  }

  function openEdit(user) {
    resetForm();
    editingId = user.id;
    modalTitle.textContent = 'Edit user';
    modalSubtitle.textContent = 'Update details, role, status, or AuditPulse access. Leave the password fields blank to keep the current password.';
    saveBtn.textContent = 'Save changes';
    fieldName.value = user.name;
    fieldEmail.value = user.email;
    fieldRole.value = user.role;
    fieldAccess.checked = !!user.auditpulse_access;
    fieldStatus.value = user.status;
    fieldPassword.placeholder = 'Leave blank to keep current password';
    fieldConfirmPassword.placeholder = 'Leave blank to keep current password';
    P.openModal('userModal');
  }

  function validate() {
    var ok = true;
    var isCreate = !editingId;

    if (!fieldName.value.trim()) { markInvalid(fieldName, 'nameError'); ok = false; } else clearInvalid(fieldName, 'nameError');

    var emailOk = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(fieldEmail.value.trim());
    if (!emailOk) { markInvalid(fieldEmail, 'emailError'); ok = false; } else clearInvalid(fieldEmail, 'emailError');

    // Password is required when creating a user. When editing, it's
    // optional — an admin only fills it in to reset the password, and
    // blank fields leave the existing one untouched.
    var pw = fieldPassword.value;
    var confirmPw = fieldConfirmPassword.value;
    var touchedPassword = isCreate || pw || confirmPw;

    if (touchedPassword) {
      if (pw.length < 8) { markInvalid(fieldPassword, 'passwordError'); ok = false; } else clearInvalid(fieldPassword, 'passwordError');
      if (pw !== confirmPw) { markInvalid(fieldConfirmPassword, 'confirmPasswordError'); ok = false; } else clearInvalid(fieldConfirmPassword, 'confirmPasswordError');
    } else {
      clearInvalid(fieldPassword, 'passwordError');
      clearInvalid(fieldConfirmPassword, 'confirmPasswordError');
    }

    return ok;
  }
  function markInvalid(field, errId) { field.classList.add('is-invalid'); var e = P.qs('#' + errId); if (e) e.classList.add('is-visible'); }
  function clearInvalid(field, errId) { field.classList.remove('is-invalid'); var e = P.qs('#' + errId); if (e) e.classList.remove('is-visible'); }

  function submitForm(e) {
    e.preventDefault();
    if (!validate()) return;
    var payload = {
      name: fieldName.value.trim(),
      email: fieldEmail.value.trim(),
      role: fieldRole.value,
      auditpulse_access: fieldAccess.checked,
      status: fieldStatus.value
    };
    // Only send a password when the admin actually typed one — required
    // on create, optional on edit (a reset). confirm_password rides along
    // so the backend can re-check the match server-side too.
    if (fieldPassword.value) {
      payload.password = fieldPassword.value;
      payload.confirm_password = fieldConfirmPassword.value;
    }
    var wasCreate = !editingId;
    saveBtn.disabled = true;
    var op = editingId ? P.Api.updateUser(editingId, payload) : P.Api.createUser(payload);
    op.then(function () {
      P.closeModal('userModal');
      P.toast(wasCreate ? 'User created.' : 'User updated.', 'success');
      return load();
    }).catch(function (err) {
      P.toast(err.message, 'error');
    }).finally(function () {
      saveBtn.disabled = false;
    });
  }

  /* -------------------------------- row actions ------------------------------- */

  function findUser(id) {
    return state.users.filter(function (u) { return String(u.id) === String(id); })[0];
  }

  function onTableClick(e) {
    var menuTrigger = e.target.closest('.menu-trigger');
    if (menuTrigger) {
      var menu = menuTrigger.nextElementSibling;
      P.qsa('.menu.is-open').forEach(function (m) { if (m !== menu) m.classList.remove('is-open'); });
      menu.classList.toggle('is-open');
      return;
    }
    var row = e.target.closest('tr');
    if (!row) return;
    var user = findUser(row.dataset.id);
    if (!user) return;

    if (e.target.closest('.js-edit') || e.target.closest('.js-role')) {
      openEdit(user);
    } else if (e.target.closest('.js-delete')) {
      deleteTargetId = user.id;
      deleteTargetName.textContent = user.name;
      P.openModal('deleteModal');
    }
  }

  function onTableChange(e) {
    if (!e.target.classList.contains('access-toggle')) return;
    var row = e.target.closest('tr');
    var user = findUser(row.dataset.id);
    if (!user) return;
    var checked = e.target.checked;
    e.target.disabled = true;
    P.Api.updateUser(user.id, { auditpulse_access: checked }).then(function (updated) {
      user.auditpulse_access = updated.auditpulse_access;
      P.toast('AuditPulse access ' + (checked ? 'enabled' : 'revoked') + ' for ' + user.name + '.', 'success');
    }).catch(function (err) {
      e.target.checked = !checked;
      P.toast(err.message, 'error');
    }).finally(function () {
      e.target.disabled = false;
    });
  }

  function onConfirmDelete() {
    if (!deleteTargetId) return;
    confirmDeleteBtn.disabled = true;
    P.Api.deleteUser(deleteTargetId).then(function () {
      P.closeModal('deleteModal');
      P.toast('User deleted.', 'success');
      return load();
    }).catch(function (err) {
      P.toast(err.message, 'error');
    }).finally(function () {
      confirmDeleteBtn.disabled = false;
      deleteTargetId = null;
    });
  }

  /* --------------------------------- wiring --------------------------------- */

  document.addEventListener('DOMContentLoaded', function () {
    if (document.body.dataset.page !== 'users') return;
    load();
    P.on(createBtn, 'click', openCreate);
    P.on(form, 'submit', submitForm);
    P.on(tbody, 'click', onTableClick);
    P.on(tbody, 'change', onTableChange);
    P.on(confirmDeleteBtn, 'click', onConfirmDelete);
    P.on(searchInput, 'input', function () {
      state.query = searchInput.value.trim();
      render();
    });
  });
})();
