"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const state = { csrf: "", available: false, busy: false, challenge: "", email: "", expires: 0, resend: 0 };

  function status(text, error = false) {
    $("login-status").textContent = text;
    $("login-status").classList.toggle("error", error);
  }
  function remaining() { return Math.max(0, Math.ceil((state.resend - Date.now()) / 1000)); }
  function render() {
    const cooldown = remaining(); const codeStep = !!state.challenge;
    $("email-request-form").hidden = codeStep || !state.available;
    $("email-code-form").hidden = !codeStep || !state.available;
    $("email-unavailable").hidden = state.available || !state.csrf;
    $("login-email").disabled = state.busy || !state.available;
    $("send-code").disabled = state.busy || !state.available || !state.csrf || cooldown > 0;
    $("send-code").textContent = state.busy && !codeStep ? "Sending…" : cooldown ? `Send code in ${cooldown}s` : "Email me a code →";
    $("verify-code").disabled = state.busy || !state.challenge || Date.now() >= state.expires || !/^[0-9]{6}$/.test($("email-code").value);
    $("verify-code").textContent = state.busy && codeStep ? "Please wait…" : "Sign in →";
    $("email-code").disabled = state.busy || Date.now() >= state.expires;
    $("resend-code").disabled = state.busy || cooldown > 0;
    $("resend-code").textContent = cooldown ? `Send a new code in ${cooldown}s` : "Send a new code";
    $("change-email").disabled = state.busy;
    $("sign-in").disabled = state.busy || !state.csrf;
    $("access-code").disabled = state.busy;
    for (const id of ["email-request-form", "email-code-form", "login-form"]) $(id).setAttribute("aria-busy", String(state.busy));
    if (codeStep && Date.now() >= state.expires) $("code-help").textContent = "This code has expired. Request a new code to continue.";
  }
  function clearPreviousAccount() {
    try {
      const storage = window.localStorage;
      for (const key of Object.keys(storage)) {
        if (key === "autokaggle-chat-last-project" || key.startsWith("autokaggle-chat-compose:") || key.startsWith("autokaggle-chat-pending:")) storage.removeItem(key);
      }
      storage.setItem("autokaggle-session-ended", String(Date.now()));
    } catch (_) { /* A new account can sign in when browser storage is unavailable. */ }
  }
  function destination() {
    const requested = new URLSearchParams(window.location.search).get("next") || "/";
    try {
      const target = new URL(requested, window.location.origin);
      return target.origin === window.location.origin && ["/", "/workbench"].includes(target.pathname) ? target.pathname + target.search : "/";
    } catch (_) { return "/"; }
  }
  async function request(path, payload) {
    const controller = new AbortController(); const timeout = window.setTimeout(() => controller.abort(), 30000);
    try {
      const response = await fetch(path, {
        credentials: "same-origin", cache: "no-store", signal: controller.signal,
        ...(payload === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": state.csrf }, body: JSON.stringify(payload) }),
      });
      let result;
      try { result = await response.json(); } catch (_) { throw new Error("The server returned an unexpected response. Please try again."); }
      if (!response.ok) {
        const error = new Error(typeof result?.detail === "string" ? result.detail : "Sign-in could not be completed. Please try again.");
        error.status = response.status; error.retryAfter = Math.min(3600, Math.max(1, Number(response.headers.get("Retry-After")) || 60)); throw error;
      }
      if (!result || typeof result !== "object" || Array.isArray(result)) throw new Error("The server returned an unexpected response. Please try again.");
      return result;
    } catch (error) {
      if (error.name === "AbortError" || error instanceof TypeError) throw new Error("The connection was interrupted. The request could not be confirmed. Please try again.");
      throw error;
    } finally { window.clearTimeout(timeout); }
  }
  async function refreshAccess() {
    const result = await request("/api/access");
    if (!result.private_mode) { window.location.replace("/"); return false; }
    if (typeof result.csrf_token !== "string" || !result.csrf_token) throw new Error("The sign-in form could not load. Reload this page.");
    state.csrf = result.csrf_token; state.available = result.email_login_available === true;
    return true;
  }
  async function sendCode() {
    if (state.busy || !state.available || remaining()) return;
    const email = state.challenge ? state.email : $("login-email").value.trim();
    $("login-email").value = email;
    if (!email || (!state.challenge && !$("login-email").reportValidity())) return;
    state.busy = true; status("Sending your sign-in code…"); render();
    try {
      if (!await refreshAccess()) return;
      if (!state.available) { status(""); return; }
      const result = await request("/api/access/email/request", { email });
      if (typeof result.challenge_id !== "string" || !result.challenge_id || !Number.isFinite(result.expires_in) || result.expires_in <= 0 || !Number.isFinite(result.resend_after) || result.resend_after < 0) throw new Error("The sign-in request could not be confirmed. Please try again.");
      state.challenge = result.challenge_id; state.email = email;
      state.expires = Date.now() + Math.min(result.expires_in, 600) * 1000;
      state.resend = Date.now() + Math.min(result.resend_after, 3600) * 1000;
      $("login-email-sent").textContent = email; $("email-code").value = "";
      $("code-help").textContent = "The code expires in 10 minutes. Check your spam folder if it does not arrive.";
      status("Your sign-in code has been sent.");
    } catch (error) {
      if (error.status === 429) state.resend = Date.now() + error.retryAfter * 1000;
      if (error.status === 503) state.available = false;
      status(error.message, true);
    } finally { state.busy = false; render(); if (state.challenge && state.available) $("email-code").focus(); }
  }
  async function verifyCode() {
    const code = $("email-code").value;
    if (state.busy || !state.challenge || Date.now() >= state.expires || !/^[0-9]{6}$/.test(code)) return;
    state.busy = true; status("Checking your code…"); render();
    try {
      if (!await refreshAccess()) return;
      const result = await request("/api/access/email/verify", { challenge_id: state.challenge, code });
      if (result.redirect !== "/") throw new Error("The server returned an unexpected response. Please try again.");
      $("email-code").value = ""; state.challenge = ""; state.csrf = "";
      status("Signed in. Opening your workspace…"); clearPreviousAccount(); window.location.replace(destination());
    } catch (error) {
      $("email-code").value = "";
      if (error.status === 410) state.expires = 0;
      status(error.message, true);
    } finally { state.busy = false; render(); if (state.challenge) $("email-code").focus(); }
  }
  async function adminLogin() {
    if (state.busy || !state.csrf) return;
    state.busy = true; status("Checking your access code…"); render();
    try {
      if (!await refreshAccess()) return;
      const result = await request("/api/access/login", { access_code: $("access-code").value });
      if (result.redirect !== "/") throw new Error("The server returned an unexpected response. Please try again.");
      $("access-code").value = ""; state.csrf = ""; clearPreviousAccount(); window.location.replace(destination());
    } catch (error) { $("access-code").value = ""; status(error.message, true); }
    finally { state.busy = false; render(); if (state.csrf) $("access-code").focus(); }
  }
  $("email-request-form").addEventListener("submit", (event) => { event.preventDefault(); sendCode(); });
  $("email-code-form").addEventListener("submit", (event) => { event.preventDefault(); verifyCode(); });
  $("login-form").addEventListener("submit", (event) => { event.preventDefault(); adminLogin(); });
  $("email-code").addEventListener("input", () => { $("email-code").value = $("email-code").value.replace(/[^0-9]/g, "").slice(0, 6); render(); });
  $("resend-code").addEventListener("click", sendCode);
  $("change-email").addEventListener("click", () => {
    if (state.busy) return;
    state.challenge = ""; state.expires = 0; $("email-code").value = ""; status(""); render(); $("login-email").focus();
  });
  window.setInterval(render, 1000);
  refreshAccess().then(() => { status(""); render(); }).catch((error) => { status(error.message, true); render(); });
})();
