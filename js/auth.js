/* ==========================================================================
   auth.js — login.html, signup.html, sso-callback.html. These run before
   any session exists, so unlike users.js/roles.js/etc. they can't assume
   a token is already in localStorage. Depends on window.Portal (app.js).
   ========================================================================== */

(function () {
  var P = window.Portal;
  if (!P) return;

  function slugify(raw) {
    return (raw || '').toLowerCase().trim().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
  }

  function showAlert(el, message) {
    if (!el) return;
    el.textContent = message;
    el.classList.add('is-visible');
  }
  function hideAlert(el) { if (el) el.classList.remove('is-visible'); }

  function setBusy(btn, busy, busyLabel, idleLabel) {
    if (!btn) return;
    btn.disabled = busy;
    btn.textContent = busy ? busyLabel : idleLabel;
  }

  /* ============================== Login page ============================== */
  function initLogin() {
    var form = P.qs('#loginForm');
    var mfaForm = P.qs('#mfaForm');
    var alertEl = P.qs('#loginAlert');
    var mfaAlertEl = P.qs('#mfaAlert');
    var ssoWrap = P.qs('#ssoOption');
    var ssoBtn = P.qs('#ssoButton');
    var ssoLabel = P.qs('#ssoButtonLabel');
    var orgField = P.qs('#loginOrgSlug');
    var loginPanel = P.qs('#loginPanel');
    var mfaPanel = P.qs('#mfaPanel');
    var mfaToken = null;
    var ssoCheckTimer = null;

    function checkSso() {
      var slug = slugify(orgField.value);
      if (!slug) { ssoWrap.hidden = true; return; }
      P.Api.ssoPublicConfig(slug).then(function (cfg) {
        if (cfg.enabled) {
          ssoLabel.textContent = 'Sign in with ' + cfg.label;
          ssoWrap.hidden = false;
          ssoBtn.dataset.orgSlug = slug;
        } else {
          ssoWrap.hidden = true;
        }
      }).catch(function () { ssoWrap.hidden = true; });
    }

    P.on(orgField, 'input', function () {
      clearTimeout(ssoCheckTimer);
      ssoCheckTimer = setTimeout(checkSso, 350);
    });
    checkSso();

    P.on(ssoBtn, 'click', function () {
      var slug = ssoBtn.dataset.orgSlug;
      if (slug) window.location.href = P.Api.ssoAuthorizeUrl(slug);
    });

    P.on(form, 'submit', function (e) {
      e.preventDefault();
      hideAlert(alertEl);
      var btn = P.qs('#loginSubmit');
      setBusy(btn, true, 'Signing in…', 'Sign in');
      P.Api.login({
        org_slug: slugify(orgField.value),
        email: P.qs('#loginEmail').value.trim(),
        password: P.qs('#loginPassword').value
      }).then(function (res) {
        if (res.mfa_required) {
          mfaToken = res.mfa_token;
          loginPanel.hidden = true;
          mfaPanel.hidden = false;
          P.qs('#mfaCode').focus();
          return;
        }
        P.setToken(res.access_token);
        window.location.href = 'index.html';
      }).catch(function (err) {
        showAlert(alertEl, err.message);
      }).finally(function () {
        setBusy(btn, false, 'Signing in…', 'Sign in');
      });
    });

    P.on(mfaForm, 'submit', function (e) {
      e.preventDefault();
      hideAlert(mfaAlertEl);
      var btn = P.qs('#mfaSubmit');
      setBusy(btn, true, 'Verifying…', 'Verify');
      P.Api.verifyMfaLogin({ mfa_token: mfaToken, code: P.qs('#mfaCode').value.trim() }).then(function (res) {
        P.setToken(res.access_token);
        window.location.href = 'index.html';
      }).catch(function (err) {
        showAlert(mfaAlertEl, err.message);
      }).finally(function () {
        setBusy(btn, false, 'Verifying…', 'Verify');
      });
    });

    P.on(P.qs('#mfaBack'), 'click', function () {
      mfaPanel.hidden = true;
      loginPanel.hidden = false;
      mfaToken = null;
    });
  }

  /* ============================= Signup page =============================== */
  function initSignup() {
    var form = P.qs('#signupForm');
    var alertEl = P.qs('#signupAlert');
    var nameField = P.qs('#signupOrgName');
    var slugField = P.qs('#signupOrgSlug');
    var slugTouched = false;

    P.on(slugField, 'input', function () { slugTouched = true; });
    P.on(nameField, 'input', function () {
      if (!slugTouched) slugField.value = slugify(nameField.value);
    });

    P.on(form, 'submit', function (e) {
      e.preventDefault();
      hideAlert(alertEl);

      var password = P.qs('#signupPassword').value;
      var confirm = P.qs('#signupPasswordConfirm').value;
      if (password !== confirm) {
        showAlert(alertEl, "Passwords don't match.");
        return;
      }

      var btn = P.qs('#signupSubmit');
      setBusy(btn, true, 'Creating your organisation…', 'Create organisation');
      P.Api.signup({
        org_name: nameField.value.trim(),
        org_slug: slugify(slugField.value),
        admin_name: P.qs('#signupAdminName').value.trim(),
        admin_email: P.qs('#signupAdminEmail').value.trim(),
        admin_password: password
      }).then(function (res) {
        P.setToken(res.access_token);
        window.location.href = 'index.html';
      }).catch(function (err) {
        showAlert(alertEl, err.message);
      }).finally(function () {
        setBusy(btn, false, 'Creating your organisation…', 'Create organisation');
      });
    });
  }

  /* =========================== SSO callback page ============================ */
  function initSsoCallback() {
    var hash = window.location.hash.replace(/^#/, '');
    var params = new URLSearchParams(hash);
    var token = params.get('token');
    var errorEl = P.qs('#ssoCallbackError');
    var successEl = P.qs('#ssoCallbackSuccess');
    var spinnerEl = P.qs('#ssoCallbackSpinner');

    if (token) {
      P.setToken(token);
      history.replaceState(null, '', window.location.pathname);
      successEl.hidden = false;
      setTimeout(function () { window.location.href = 'index.html'; }, 600);
    } else {
      if (spinnerEl) spinnerEl.hidden = true;
      errorEl.hidden = false;
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    var pg = document.body.dataset.page;
    // If someone with an existing session lands on login/signup, send
    // them straight through rather than making them sign in again.
    if ((pg === 'login' || pg === 'signup') && P.getToken()) {
      window.location.href = 'index.html';
      return;
    }
    if (pg === 'login') initLogin();
    if (pg === 'signup') initSignup();
    if (pg === 'sso-callback') initSsoCallback();
  });
})();
