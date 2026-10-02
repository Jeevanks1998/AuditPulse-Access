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

  function cleanCode(input) {
    return (input.value || '').replace(/\D/g, '').slice(0, 6);
  }

  /* ============================== Login page ==============================
     Email -> Google Authenticator. No password.
       1. org + email      POST /auth/login -> { step, mfa_token, ... }
       2a. step "setup"    first login / admin reset: QR code + code
       2b. step "verify"   authenticator already set up: just the code
       3.  code            POST /auth/mfa/verify -> session -> dashboard
     ======================================================================== */
  function initLogin() {
    var form = P.qs('#loginForm');
    var setupForm = P.qs('#setupForm');
    var mfaForm = P.qs('#mfaForm');
    var alertEl = P.qs('#loginAlert');
    var setupAlertEl = P.qs('#setupAlert');
    var mfaAlertEl = P.qs('#mfaAlert');
    var ssoWrap = P.qs('#ssoOption');
    var ssoBtn = P.qs('#ssoButton');
    var ssoLabel = P.qs('#ssoButtonLabel');
    var orgField = P.qs('#loginOrgSlug');
    var emailField = P.qs('#loginEmail');
    var loginPanel = P.qs('#loginPanel');
    var setupPanel = P.qs('#setupPanel');
    var mfaPanel = P.qs('#mfaPanel');
    var setupCode = P.qs('#setupCode');
    var mfaCode = P.qs('#mfaCode');
    // Challenge token from step 1 — memory only, never stored; not a session.
    var mfaToken = null;
    var ssoCheckTimer = null;

    function showPanel(name) {
      loginPanel.hidden = name !== 'login';
      setupPanel.hidden = name !== 'setup';
      mfaPanel.hidden = name !== 'verify';
    }

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

    P.on(ssoBtn, 'click', function () {
      var slug = ssoBtn.dataset.orgSlug;
      if (slug) window.location.href = P.Api.ssoAuthorizeUrl(slug);
    });

    function backToLogin() {
      mfaToken = null;
      setupCode.value = '';
      mfaCode.value = '';
      P.qs('#setupQr').removeAttribute('src');
      P.qs('#setupSecret').textContent = '';
      hideAlert(setupAlertEl);
      hideAlert(mfaAlertEl);
      showPanel('login');
      emailField.focus();
    }

    P.qsa('[data-back-to-login]').forEach(function (btn) { P.on(btn, 'click', backToLogin); });

    // Step 1: org + email
    P.on(form, 'submit', function (e) {
      e.preventDefault();
      hideAlert(alertEl);
      var slug = slugify(orgField.value);
      var email = emailField.value.trim();
      if (!slug || !email) {
        showAlert(alertEl, 'Enter your organisation URL and email.');
        return;
      }
      var btn = P.qs('#loginSubmit');
      setBusy(btn, true, 'Checking…', 'Continue');
      P.Api.login({ org_slug: slug, email: email }).then(function (res) {
        mfaToken = res.mfa_token;
        if (res.step === 'setup') {
          P.qs('#setupEmail').textContent = res.email;
          P.qs('#setupQr').src = res.qr_code;
          P.qs('#setupSecret').textContent = (res.secret || '').replace(/(.{4})/g, '$1 ').trim();
          setupCode.value = '';
          hideAlert(setupAlertEl);
          showPanel('setup');
          setupCode.focus();
        } else {
          P.qs('#mfaEmail').textContent = res.email;
          mfaCode.value = '';
          hideAlert(mfaAlertEl);
          showPanel('verify');
          mfaCode.focus();
        }
      }).catch(function (err) {
        showAlert(alertEl, err.message);
      }).finally(function () {
        setBusy(btn, false, 'Checking…', 'Continue');
      });
    });

    // Step 2: 6-digit code (same endpoint for setup and normal login)
    function submitCode(input, alertBox, btn, idleLabel) {
      hideAlert(alertBox);
      var code = cleanCode(input);
      if (code.length !== 6) {
        showAlert(alertBox, 'Enter the 6-digit code from Google Authenticator.');
        return;
      }
      setBusy(btn, true, 'Verifying…', idleLabel);
      P.Api.verifyMfaLogin({ mfa_token: mfaToken, code: code }).then(function (res) {
        P.setToken(res.access_token);
        window.location.href = 'index.html';
      }).catch(function (err) {
        setBusy(btn, false, 'Verifying…', idleLabel);
        if (/enter your email again/i.test(err.message)) {
          backToLogin();
          showAlert(alertEl, err.message);
          return;
        }
        input.value = '';
        input.focus();
        showAlert(alertBox, err.message);
      });
    }

    [setupCode, mfaCode].forEach(function (input) {
      P.on(input, 'input', function () {
        var cleaned = cleanCode(input);
        if (input.value !== cleaned) input.value = cleaned;
      });
    });

    P.on(setupForm, 'submit', function (e) {
      e.preventDefault();
      submitCode(setupCode, setupAlertEl, P.qs('#setupSubmit'), 'Verify & continue');
    });

    P.on(mfaForm, 'submit', function (e) {
      e.preventDefault();
      submitCode(mfaCode, mfaAlertEl, P.qs('#mfaSubmit'), 'Verify');
    });

    // Arriving from signup.html (or a shared link): prefill, and continue
    // straight to the authenticator setup when asked to.
    var params = new URLSearchParams(window.location.search);
    if (params.get('org')) orgField.value = params.get('org');
    if (params.get('email')) emailField.value = params.get('email');
    checkSso();
    if (params.get('setup') === '1' && orgField.value && emailField.value) {
      history.replaceState(null, '', window.location.pathname);
      form.requestSubmit ? form.requestSubmit() : form.dispatchEvent(new Event('submit', { cancelable: true }));
    }
  }

  /* ============================= Signup page ===============================
     Creates the organisation + admin (no password), then hands over to
     login.html, which shows the Google Authenticator QR setup.
     ======================================================================== */
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

      var btn = P.qs('#signupSubmit');
      setBusy(btn, true, 'Creating your organisation…', 'Create organisation');
      P.Api.signup({
        org_name: nameField.value.trim(),
        org_slug: slugify(slugField.value),
        admin_name: P.qs('#signupAdminName').value.trim(),
        admin_email: P.qs('#signupAdminEmail').value.trim()
      }).then(function (res) {
        window.location.href = 'login.html?setup=1&org=' + encodeURIComponent(res.org_slug) +
          '&email=' + encodeURIComponent(res.email);
      }).catch(function (err) {
        showAlert(alertEl, err.message);
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
