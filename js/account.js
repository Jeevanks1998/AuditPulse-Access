/* ==========================================================================
   account.js — account.html: profile summary, password change, and TOTP
   MFA enroll/enable/disable against auth.py / mfa.py.
   Depends on window.Portal from app.js (loaded first).
   ========================================================================== */

(function () {
  var P = window.Portal;
  if (!P) return;

  var acctAvatar = P.qs('#acctAvatar');
  var acctName = P.qs('#acctName');
  var acctEmail = P.qs('#acctEmail');
  var acctRolePill = P.qs('#acctRolePill');

  var passwordForm = P.qs('#passwordForm');
  var passwordAlert = P.qs('#passwordAlert');
  var fieldCurrentPassword = P.qs('#fieldCurrentPassword');
  var fieldNewPassword = P.qs('#fieldNewPassword');
  var fieldNewPasswordConfirm = P.qs('#fieldNewPasswordConfirm');
  var passwordFormSave = P.qs('#passwordFormSave');

  var mfaStatusBadge = P.qs('#mfaStatusBadge');
  var mfaStartPanel = P.qs('#mfaStartPanel');
  var mfaEnrollPanel = P.qs('#mfaEnrollPanel');
  var mfaEnabledPanel = P.qs('#mfaEnabledPanel');
  var mfaStartBtn = P.qs('#mfaStartBtn');
  var mfaSecretValue = P.qs('#mfaSecretValue');
  var mfaAccountLabel = P.qs('#mfaAccountLabel');
  var mfaEnrollForm = P.qs('#mfaEnrollForm');
  var mfaEnrollAlert = P.qs('#mfaEnrollAlert');
  var fieldMfaEnrollCode = P.qs('#fieldMfaEnrollCode');
  var mfaEnrollSubmitBtn = P.qs('#mfaEnrollSubmitBtn');
  var mfaEnrollCancelBtn = P.qs('#mfaEnrollCancelBtn');
  var mfaDisableBtn = P.qs('#mfaDisableBtn');

  var mfaDisableForm = P.qs('#mfaDisableForm');
  var mfaDisableAlert = P.qs('#mfaDisableAlert');
  var fieldMfaDisablePassword = P.qs('#fieldMfaDisablePassword');
  var mfaDisableConfirmBtn = P.qs('#mfaDisableConfirmBtn');

  function showAlert(el, message) {
    if (!el) return;
    el.textContent = message;
    el.classList.add('is-visible');
  }
  function hideAlert(el) { if (el) el.classList.remove('is-visible'); }

  /* ------------------------------- profile ------------------------------- */

  function showMfaState(user) {
    if (user.mfa_enabled) {
      mfaStatusBadge.textContent = 'Enabled';
      mfaStatusBadge.className = 'badge badge--on';
      mfaStartPanel.hidden = true;
      mfaEnrollPanel.hidden = true;
      mfaEnabledPanel.hidden = false;
    } else {
      mfaStatusBadge.textContent = 'Disabled';
      mfaStatusBadge.className = 'badge badge--neutral';
      mfaStartPanel.hidden = false;
      mfaEnrollPanel.hidden = true;
      mfaEnabledPanel.hidden = true;
    }
  }

  function loadProfile() {
    P.Api.me().then(function (user) {
      acctAvatar.textContent = P.initials(user.name);
      acctName.textContent = user.name;
      acctEmail.textContent = user.email;
      acctRolePill.textContent = user.role;
      acctRolePill.className = 'role-pill role-pill--' + P.roleClass(user.role);
      showMfaState(user);
    }).catch(function () { /* requireAuth already redirects on 401 */ });
  }

  /* ----------------------------- password change ----------------------------- */

  function submitPasswordForm(e) {
    e.preventDefault();
    hideAlert(passwordAlert);
    var current = fieldCurrentPassword.value;
    var next = fieldNewPassword.value;
    var confirm = fieldNewPasswordConfirm.value;

    if (next.length < 8) { showAlert(passwordAlert, 'New password must be at least 8 characters.'); return; }
    if (next !== confirm) { showAlert(passwordAlert, "New passwords don't match."); return; }

    passwordFormSave.disabled = true;
    P.Api.changePassword({ current_password: current, new_password: next }).then(function () {
      passwordForm.reset();
      P.toast('Password updated.', 'success');
    }).catch(function (err) {
      showAlert(passwordAlert, err.message);
    }).finally(function () {
      passwordFormSave.disabled = false;
    });
  }

  /* --------------------------------- MFA enroll --------------------------------- */

  function startEnroll() {
    P.Api.mfaEnroll().then(function (res) {
      mfaSecretValue.textContent = res.secret;
      var match = /name=([^&]+)/.exec(res.otpauth_uri || '');
      mfaAccountLabel.textContent = match ? decodeURIComponent(match[1]) : '';
      hideAlert(mfaEnrollAlert);
      fieldMfaEnrollCode.value = '';
      mfaStartPanel.hidden = true;
      mfaEnrollPanel.hidden = false;
      fieldMfaEnrollCode.focus();
    }).catch(function (err) {
      P.toast(err.message, 'error');
    });
  }

  function cancelEnroll() {
    mfaEnrollPanel.hidden = true;
    mfaStartPanel.hidden = false;
  }

  function submitEnroll(e) {
    e.preventDefault();
    hideAlert(mfaEnrollAlert);
    var code = fieldMfaEnrollCode.value.trim();
    if (!code) return;
    mfaEnrollSubmitBtn.disabled = true;
    P.Api.mfaEnable({ code: code }).then(function () {
      P.toast('Two-factor authentication is now enabled.', 'success');
      loadProfile();
    }).catch(function (err) {
      showAlert(mfaEnrollAlert, err.message);
    }).finally(function () {
      mfaEnrollSubmitBtn.disabled = false;
    });
  }

  /* --------------------------------- MFA disable --------------------------------- */

  function openDisableModal() {
    fieldMfaDisablePassword.value = '';
    hideAlert(mfaDisableAlert);
    P.openModal('mfaDisableModal');
  }

  function submitDisable(e) {
    e.preventDefault();
    hideAlert(mfaDisableAlert);
    var password = fieldMfaDisablePassword.value;
    if (!password) return;
    mfaDisableConfirmBtn.disabled = true;
    P.Api.mfaDisable({ password: password }).then(function () {
      P.closeModal('mfaDisableModal');
      P.toast('Two-factor authentication disabled.', 'success');
      loadProfile();
    }).catch(function (err) {
      showAlert(mfaDisableAlert, err.message);
    }).finally(function () {
      mfaDisableConfirmBtn.disabled = false;
    });
  }

  /* --------------------------------- wiring --------------------------------- */

  document.addEventListener('DOMContentLoaded', function () {
    if (document.body.dataset.page !== 'account') return;

    loadProfile();
    P.on(passwordForm, 'submit', submitPasswordForm);
    P.on(mfaStartBtn, 'click', startEnroll);
    P.on(mfaEnrollCancelBtn, 'click', cancelEnroll);
    P.on(mfaEnrollForm, 'submit', submitEnroll);
    P.on(mfaDisableBtn, 'click', openDisableModal);
    P.on(mfaDisableForm, 'submit', submitDisable);
  });
})();
