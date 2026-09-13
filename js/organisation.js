/* ==========================================================================
   organisation.js — organisation.html: org name/stats (admin can rename)
   and OIDC SSO configuration (admin only). Depends on window.Portal.
   ========================================================================== */

(function () {
  var P = window.Portal;
  if (!P) return;

  var fieldOrgName = P.qs('#fieldOrgName');
  var fieldOrgSlug = P.qs('#fieldOrgSlug');
  var orgStatUsers = P.qs('#orgStatUsers');
  var orgStatTeams = P.qs('#orgStatTeams');
  var orgStatRoles = P.qs('#orgStatRoles');
  var orgForm = P.qs('#orgForm');
  var orgFormActions = P.qs('#orgFormActions');
  var orgFormSave = P.qs('#orgFormSave');

  var ssoCard = P.qs('#ssoCard');
  var ssoStatusBadge = P.qs('#ssoStatusBadge');
  var ssoForm = P.qs('#ssoForm');
  var fieldSsoLabel = P.qs('#fieldSsoLabel');
  var fieldSsoIssuer = P.qs('#fieldSsoIssuer');
  var fieldSsoClientId = P.qs('#fieldSsoClientId');
  var fieldSsoClientSecret = P.qs('#fieldSsoClientSecret');
  var fieldSsoEnabled = P.qs('#fieldSsoEnabled');
  var ssoSecretHint = P.qs('#ssoSecretHint');
  var ssoFormSave = P.qs('#ssoFormSave');
  var ssoDeleteBtn = P.qs('#ssoDeleteBtn');
  var orgAdminOnlyNotice = P.qs('#orgAdminOnlyNotice');

  function loadOrg() {
    P.Api.myOrganisation().then(function (org) {
      fieldOrgName.value = org.name;
      fieldOrgSlug.value = org.slug;
      orgStatUsers.textContent = org.user_count;
      orgStatTeams.textContent = org.team_count;
      orgStatRoles.textContent = org.role_count;
    }).catch(function (err) {
      P.toast('Could not load organisation — ' + err.message, 'error');
    });
  }

  function submitOrgForm(e) {
    e.preventDefault();
    var name = fieldOrgName.value.trim();
    if (!name) return;
    orgFormSave.disabled = true;
    P.Api.updateMyOrganisation({ name: name }).then(function () {
      P.toast('Organisation updated.', 'success');
      loadOrg();
    }).catch(function (err) {
      P.toast(err.message, 'error');
    }).finally(function () {
      orgFormSave.disabled = false;
    });
  }

  /* --------------------------------- SSO --------------------------------- */

  function renderSsoConfig(cfg) {
    if (cfg.configured) {
      ssoStatusBadge.textContent = cfg.enabled ? 'Enabled' : 'Disabled';
      ssoStatusBadge.className = 'badge' + (cfg.enabled ? ' badge--on' : ' badge--neutral');
      fieldSsoLabel.value = cfg.label || '';
      fieldSsoIssuer.value = cfg.issuer || '';
      fieldSsoClientId.value = cfg.client_id || '';
      fieldSsoEnabled.checked = !!cfg.enabled;
      ssoSecretHint.textContent = cfg.client_secret_set
        ? "A client secret is saved. The backend doesn't return it, so you'll need to re-enter it here any time you change other SSO settings."
        : 'No client secret saved yet.';
      ssoDeleteBtn.hidden = false;
    } else {
      ssoStatusBadge.textContent = 'Not configured';
      ssoStatusBadge.className = 'badge badge--neutral';
      ssoForm.reset();
      fieldSsoEnabled.checked = true;
      ssoSecretHint.textContent = 'No client secret saved yet.';
      ssoDeleteBtn.hidden = true;
    }
  }

  function loadSso() {
    P.Api.ssoGetConfig().then(renderSsoConfig).catch(function (err) {
      P.toast('Could not load SSO configuration — ' + err.message, 'error');
    });
  }

  function submitSsoForm(e) {
    e.preventDefault();
    var issuer = fieldSsoIssuer.value.trim();
    var clientId = fieldSsoClientId.value.trim();
    var clientSecret = fieldSsoClientSecret.value;

    if (!issuer || !clientId) {
      P.toast('Issuer URL and client ID are both required.', 'error');
      return;
    }

    var payload = {
      label: fieldSsoLabel.value.trim() || 'Single Sign-On',
      issuer: issuer,
      client_id: clientId,
      client_secret: clientSecret,
      enabled: fieldSsoEnabled.checked
    };

    if (!payload.client_secret) {
      P.toast('Enter the client secret to save this configuration.', 'error');
      return;
    }

    ssoFormSave.disabled = true;
    P.Api.ssoSetConfig(payload).then(function (cfg) {
      P.toast('SSO configuration saved.', 'success');
      fieldSsoClientSecret.value = '';
      renderSsoConfig(cfg);
    }).catch(function (err) {
      P.toast(err.message, 'error');
    }).finally(function () {
      ssoFormSave.disabled = false;
    });
  }

  function onDeleteSso() {
    if (!window.confirm('Remove SSO for this organisation? Members will sign in with email and password only.')) return;
    ssoDeleteBtn.disabled = true;
    P.Api.ssoDeleteConfig().then(function () {
      P.toast('SSO removed.', 'success');
      loadSso();
    }).catch(function (err) {
      P.toast(err.message, 'error');
    }).finally(function () {
      ssoDeleteBtn.disabled = false;
    });
  }

  /* --------------------------------- wiring --------------------------------- */

  document.addEventListener('DOMContentLoaded', function () {
    if (document.body.dataset.page !== 'organisation') return;

    loadOrg();

    P.Api.me().then(function (user) {
      if (user.is_admin) {
        fieldOrgName.disabled = false;
        orgFormActions.hidden = false;
        ssoCard.hidden = false;
        loadSso();
      } else {
        orgAdminOnlyNotice.hidden = false;
      }
    }).catch(function () { /* requireAuth already redirects on 401 */ });

    P.on(orgForm, 'submit', submitOrgForm);
    P.on(ssoForm, 'submit', submitSsoForm);
    P.on(ssoDeleteBtn, 'click', onDeleteSso);
  });
})();
