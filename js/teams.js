/* ==========================================================================
   teams.js — Teams page: list teams as cards, create/edit/delete a team,
   add/remove members. Listing works for any signed-in user; mutations
   (create/edit/delete/add-member/remove-member) require an admin role,
   so those controls hide themselves for non-admins rather than 403-ing.
   Depends on window.Portal from app.js (loaded first).
   ========================================================================== */

(function () {
  var P = window.Portal;
  if (!P) return;

  var state = { teams: [], users: [], isAdmin: false };

  var grid = P.qs('#teamsGrid');
  var emptyState = P.qs('#teamsEmpty');
  var createBtn = P.qs('#openCreateTeam');

  var teamForm = P.qs('#teamForm');
  var teamModalTitle = P.qs('#teamModalTitle');
  var fieldTeamName = P.qs('#fieldTeamName');
  var fieldTeamDescription = P.qs('#fieldTeamDescription');
  var teamFormSave = P.qs('#teamFormSave');
  var editingTeamId = null;

  var memberForm = P.qs('#memberForm');
  var memberModalTeamName = P.qs('#memberModalTeamName');
  var fieldMemberUser = P.qs('#fieldMemberUser');
  var memberFormSave = P.qs('#memberFormSave');
  var addMemberTeamId = null;

  var confirmDeleteTeamBtn = P.qs('#confirmDeleteTeamBtn');
  var deleteTeamTargetName = P.qs('#deleteTeamTargetName');
  var deleteTeamTargetId = null;

  /* ------------------------------ rendering ------------------------------ */

  function renderSkeleton() {
    grid.innerHTML = '';
    for (var i = 0; i < 3; i++) {
      var card = document.createElement('div');
      card.className = 'team-card';
      card.innerHTML = '<div class="skeleton-bar" style="width:60%;height:20px;"></div>' +
        '<div class="skeleton-bar" style="width:100%;height:14px;margin-top:8px;"></div>';
      grid.appendChild(card);
    }
  }

  function findUserById(id) {
    return state.users.filter(function (u) { return String(u.id) === String(id); })[0];
  }

  function memberRow(teamId, member) {
    var removeBtn = state.isAdmin
      ? '<button class="team-member__remove js-remove-member" data-user="' + member.id + '" title="Remove from team">' +
          '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12"/></svg>' +
        '</button>'
      : '';
    return '<div class="team-member" data-user="' + member.id + '">' +
      '<div class="team-member__avatar">' + P.escapeHtml(P.initials(member.name)) + '</div>' +
      '<div class="team-member__body">' +
        '<div class="team-member__name">' + P.escapeHtml(member.name) + '</div>' +
        '<div class="team-member__email">' + P.escapeHtml(member.email) + '</div>' +
      '</div>' +
      removeBtn +
    '</div>';
  }

  function teamCard(team) {
    var membersHtml = team.members.length
      ? team.members.map(function (m) { return memberRow(team.id, m); }).join('')
      : '<div class="team-card__empty-members">No members yet.</div>';

    var menuHtml = state.isAdmin
      ? '<div class="menu-wrap">' +
          '<button class="menu-trigger" aria-label="Team actions">' +
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="5" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="12" cy="19" r="1.2"/></svg>' +
          '</button>' +
          '<div class="menu">' +
            '<button class="menu__item js-edit-team"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>Edit team</button>' +
            '<div class="menu__divider"></div>' +
            '<button class="menu__item js-delete-team menu__item--danger"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>Delete team</button>' +
          '</div>' +
        '</div>'
      : '';

    var addMemberBtn = state.isAdmin
      ? '<div class="team-card__actions"><button class="btn btn--secondary btn--sm js-add-member">Add member</button></div>'
      : '';

    var card = document.createElement('div');
    card.className = 'team-card';
    card.dataset.id = team.id;
    card.innerHTML =
      '<div class="team-card__head">' +
        '<div>' +
          '<div class="team-card__name">' + P.escapeHtml(team.name) + '</div>' +
          (team.description ? '<div class="team-card__desc">' + P.escapeHtml(team.description) + '</div>' : '') +
        '</div>' +
        menuHtml +
      '</div>' +
      '<div class="team-card__members">' + membersHtml + '</div>' +
      addMemberBtn;
    return card;
  }

  function render() {
    grid.innerHTML = '';
    emptyState.hidden = state.teams.length > 0;
    createBtn.hidden = !state.isAdmin;
    state.teams.forEach(function (team) { grid.appendChild(teamCard(team)); });
  }

  /* ------------------------------- data load ------------------------------ */

  function load() {
    renderSkeleton();
    var calls = [P.Api.listTeams(), P.Api.listUsers()];
    return Promise.all(calls).then(function (res) {
      state.teams = res[0];
      state.users = res[1];
      populateMemberOptions();
      render();
    }).catch(function (err) {
      grid.innerHTML = '';
      emptyState.hidden = false;
      emptyState.querySelector('p').textContent = 'Could not load teams — ' + err.message;
    });
  }

  function populateMemberOptions() {
    fieldMemberUser.innerHTML = state.users.map(function (u) {
      return '<option value="' + u.id + '">' + P.escapeHtml(u.name) + ' — ' + P.escapeHtml(u.email) + '</option>';
    }).join('');
  }

  /* -------------------------------- create/edit team form ------------------------------- */

  function resetTeamForm() {
    editingTeamId = null;
    teamForm.reset();
    teamModalTitle.textContent = 'Create team';
    teamFormSave.textContent = 'Create team';
    P.qsa('.field__error', teamForm).forEach(function (e) { e.classList.remove('is-visible'); });
    P.qsa('input, select', teamForm).forEach(function (e) { e.classList.remove('is-invalid'); });
  }

  function openCreateTeam() {
    resetTeamForm();
    P.openModal('teamModal');
    fieldTeamName.focus();
  }

  function openEditTeam(team) {
    resetTeamForm();
    editingTeamId = team.id;
    teamModalTitle.textContent = 'Edit team';
    teamFormSave.textContent = 'Save changes';
    fieldTeamName.value = team.name;
    fieldTeamDescription.value = team.description || '';
    P.openModal('teamModal');
  }

  function submitTeamForm(e) {
    e.preventDefault();
    var name = fieldTeamName.value.trim();
    if (!name) {
      fieldTeamName.classList.add('is-invalid');
      var err = P.qs('#teamNameError');
      if (err) err.classList.add('is-visible');
      return;
    }
    fieldTeamName.classList.remove('is-invalid');
    var errEl = P.qs('#teamNameError');
    if (errEl) errEl.classList.remove('is-visible');

    var payload = { name: name, description: fieldTeamDescription.value.trim() };
    teamFormSave.disabled = true;
    var op = editingTeamId ? P.Api.updateTeam(editingTeamId, payload) : P.Api.createTeam(payload);
    op.then(function () {
      P.closeModal('teamModal');
      P.toast(editingTeamId ? 'Team updated.' : 'Team created.', 'success');
      return load();
    }).catch(function (err) {
      P.toast(err.message, 'error');
    }).finally(function () {
      teamFormSave.disabled = false;
    });
  }

  /* -------------------------------- member add/remove ------------------------------- */

  function openAddMember(team) {
    addMemberTeamId = team.id;
    memberModalTeamName.textContent = team.name;
    memberForm.reset();
    P.openModal('memberModal');
  }

  function submitMemberForm(e) {
    e.preventDefault();
    var userId = fieldMemberUser.value;
    if (!userId) return;
    memberFormSave.disabled = true;
    P.Api.addTeamMember(addMemberTeamId, Number(userId)).then(function () {
      P.closeModal('memberModal');
      P.toast('Member added.', 'success');
      return load();
    }).catch(function (err) {
      P.toast(err.message, 'error');
    }).finally(function () {
      memberFormSave.disabled = false;
    });
  }

  function removeMember(teamId, userId) {
    P.Api.removeTeamMember(teamId, userId).then(function () {
      P.toast('Member removed.', 'success');
      return load();
    }).catch(function (err) {
      P.toast(err.message, 'error');
    });
  }

  /* -------------------------------- card actions ------------------------------- */

  function findTeam(id) {
    return state.teams.filter(function (t) { return String(t.id) === String(id); })[0];
  }

  function onGridClick(e) {
    var menuTrigger = e.target.closest('.menu-trigger');
    if (menuTrigger) {
      var menu = menuTrigger.nextElementSibling;
      P.qsa('.menu.is-open').forEach(function (m) { if (m !== menu) m.classList.remove('is-open'); });
      menu.classList.toggle('is-open');
      return;
    }

    var card = e.target.closest('.team-card');
    if (!card) return;
    var team = findTeam(card.dataset.id);
    if (!team) return;

    if (e.target.closest('.js-edit-team')) {
      openEditTeam(team);
    } else if (e.target.closest('.js-delete-team')) {
      deleteTeamTargetId = team.id;
      deleteTeamTargetName.textContent = team.name;
      P.openModal('deleteTeamModal');
    } else if (e.target.closest('.js-add-member')) {
      openAddMember(team);
    } else if (e.target.closest('.js-remove-member')) {
      var btn = e.target.closest('.js-remove-member');
      removeMember(team.id, Number(btn.dataset.user));
    }
  }

  function onConfirmDeleteTeam() {
    if (!deleteTeamTargetId) return;
    confirmDeleteTeamBtn.disabled = true;
    P.Api.deleteTeam(deleteTeamTargetId).then(function () {
      P.closeModal('deleteTeamModal');
      P.toast('Team deleted.', 'success');
      return load();
    }).catch(function (err) {
      P.toast(err.message, 'error');
    }).finally(function () {
      confirmDeleteTeamBtn.disabled = false;
      deleteTeamTargetId = null;
    });
  }

  /* --------------------------------- wiring --------------------------------- */

  document.addEventListener('DOMContentLoaded', function () {
    if (document.body.dataset.page !== 'teams') return;

    P.Api.me().then(function (user) {
      state.isAdmin = !!user.is_admin;
    }).catch(function () {
      state.isAdmin = false;
    }).then(load);

    P.on(createBtn, 'click', openCreateTeam);
    P.on(teamForm, 'submit', submitTeamForm);
    P.on(memberForm, 'submit', submitMemberForm);
    P.on(grid, 'click', onGridClick);
    P.on(confirmDeleteTeamBtn, 'click', onConfirmDeleteTeam);
  });
})();
