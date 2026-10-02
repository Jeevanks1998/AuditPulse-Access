/* ==========================================================================
   account.js — account.html: profile summary and Google Authenticator
   status. Sign-in is email -> Google Authenticator (no password), so
   there is nothing to change or disable here; a lost phone is handled by
   an admin's "Reset authenticator" on the Users page.
   Depends on window.Portal from app.js (loaded first).
   ========================================================================== */

(function () {
  var P = window.Portal;
  if (!P) return;

  function loadProfile() {
    P.Api.me().then(function (user) {
      P.qs('#acctAvatar').textContent = P.initials(user.name);
      P.qs('#acctName').textContent = user.name;
      P.qs('#acctEmail').textContent = user.email;
      var pill = P.qs('#acctRolePill');
      pill.textContent = user.role;
      pill.className = 'role-pill role-pill--' + P.roleClass(user.role);

      var badge = P.qs('#mfaStatusBadge');
      var text = P.qs('#mfaStatusText');
      if (user.sso) {
        badge.textContent = 'SSO';
        badge.className = 'badge badge--on';
        text.textContent = 'You signed in with your organisation’s single sign-on.';
      } else if (user.mfa_enabled && !user.auth_setup_required) {
        badge.textContent = 'Configured';
        badge.className = 'badge badge--on';
        text.textContent = 'Google Authenticator is set up and protecting this account.';
      } else {
        badge.textContent = 'Setup pending';
        badge.className = 'badge badge--neutral';
        text.textContent = 'You will be asked to scan a QR code at your next sign-in.';
      }
    }).catch(function () { /* requireAuth already redirects on 401 */ });
  }

  document.addEventListener('DOMContentLoaded', function () {
    if (document.body.dataset.page !== 'account') return;
    loadProfile();
  });
})();
