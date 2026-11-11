"use strict";
(() => {
  const $ = id => document.getElementById(id);
  const state = { csrf: "", account: "", busy: false, ready: false };
  function destination(administrator) {
    try {
      const target = new URL(new URLSearchParams(location.search).get("next") || "/", location.origin);
      if (target.origin !== location.origin || !["/", "/workbench", "/internal"].includes(target.pathname) || (target.pathname === "/internal" && !administrator)) return "/";
      if (target.pathname === "/workbench"
          && !(target.searchParams.get("view") === "review" && target.searchParams.get("project"))) {
        const interview = new URL("/", location.origin);
        if (target.searchParams.get("project")) interview.searchParams.set("project", target.searchParams.get("project"));
        return interview.pathname + interview.search;
      }
      return target.pathname + target.search;
    } catch (_) { return "/"; }
  }
  function render() {
    $("researcher-name").disabled = state.busy || !state.ready;
    $("save-profile").disabled = state.busy || !state.ready || !$("researcher-name").value.trim();
    $("save-profile").textContent = state.busy ? "Saving…" : "Save and continue";
    $("profile-form").setAttribute("aria-busy", String(state.busy));
  }
  async function request(path, options = {}) {
    const response = await fetch(path, { credentials: "same-origin", cache: "no-store", signal: AbortSignal.timeout(20000), ...options });
    const result = await response.json();
    if (!response.ok) {
      const error = new Error(typeof result.detail === "string" ? result.detail : "The name could not be saved. Please try again.");
      error.status = response.status; throw error;
    }
    return result;
  }
  function failure(error) {
    $("profile-status").textContent = error.message || "The connection stopped. Your name is still in the form. Try again.";
    $("profile-status").className = "error";
    if (error.status === 401) {
      state.ready = false; $("profile-sign-in").hidden = false;
      $("profile-sign-in").href = "/login?next=" + encodeURIComponent(location.pathname + location.search);
    } else if (error.status === 409) {
      state.ready = false; $("profile-sign-in").hidden = false;
      $("profile-sign-in").textContent = "Reload profile";
      $("profile-sign-in").href = location.pathname + location.search;
    }
  }
  async function refreshCsrf() {
    const access = await request("/api/access");
    if (typeof access.csrf_token !== "string" || !access.csrf_token) throw new Error("Reload this page to load the profile form.");
    state.csrf = access.csrf_token;
  }
  async function save(event) {
    event.preventDefault();
    if (state.busy || !state.ready || !$("researcher-name").reportValidity()) return;
    const name = $("researcher-name").value.trim(); if (!name) return;
    state.busy = true; render(); $("profile-status").textContent = "Saving your name…";
    try {
      await refreshCsrf();
      const result = await request("/api/access/profile", { method: "PATCH", headers: { "Content-Type": "application/json", "X-CSRF-Token": state.csrf }, body: JSON.stringify({ name, account_id: state.account }) });
      if (typeof result.name !== "string" || !result.name.trim()) throw new Error("The server did not confirm the saved name. Try again.");
      location.replace(destination(result.is_admin === true));
    } catch (error) { failure(error); }
    finally { state.busy = false; render(); }
  }
  async function init() {
    try {
      await refreshCsrf();
      const profile = await request("/api/access/profile");
      if (typeof profile.name !== "string" || typeof profile.account_id !== "string" || !profile.account_id) throw new Error("Reload this page to load your researcher name.");
      state.account = profile.account_id; $("researcher-name").value = profile.name; state.ready = true; $("profile-status").textContent = "";
      render(); $("researcher-name").focus();
    } catch (error) { failure(error); render(); }
  }
  $("profile-form").addEventListener("submit", save);
  $("researcher-name").addEventListener("input", render);
  init();
})();
