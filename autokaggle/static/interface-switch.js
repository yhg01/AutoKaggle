/* Interface navigation changes the view, never the authenticated identity. */
"use strict";
(() => {
  const nav = document.getElementById("interface-switch");
  if (!nav) return;
  const mode = location.pathname === "/internal" ? "internal" : "intake";
  const storageKey = kind => `autokaggle-interface-context:${kind}`;
  let allowed = false, navigating = false;

  function safeContext(value, kind) {
    if (!value) return null;
    try {
      const url = new URL(value, location.origin);
      if (url.origin !== location.origin || !(kind === "internal" ? ["/internal"] : ["/", "/workbench"]).includes(url.pathname)) return null;
      const clean = new URL(url.pathname, location.origin);
      for (const key of kind === "internal" ? ["project", "view", "record"] : ["project", "view"]) {
        const value = url.searchParams.get(key);
        if (value && value.length <= 256) clean.searchParams.set(key, value);
      }
      return clean;
    } catch (_) {return null;}
  }
  function recall(kind) {try {return safeContext(sessionStorage.getItem(storageKey(kind)), kind);} catch (_) {return null;}}
  function remember() {try {const safe = safeContext(location.href, mode); if (safe) sessionStorage.setItem(storageKey(mode), safe.pathname + safe.search);} catch (_) { /* Switching works without storage. */ }}
  function project() {return new URLSearchParams(location.search).get("project");}
  async function canOpen(id) {
    if (!id) return false;
    try {return (await fetch(`/api/projects/${encodeURIComponent(id)}`, {credentials: "same-origin", cache: "no-store", signal: AbortSignal.timeout(10000)})).ok;} catch (_) {return false;}
  }
  async function destination(kind) {
    const saved = recall(kind), id = project();
    if (kind === "internal") {
      const target = saved || new URL("/internal", location.origin);
      if (id) {
        if (target.searchParams.get("project") !== id) target.searchParams.delete("record");
        target.searchParams.set("project", id);
      }
      return target.pathname + target.search;
    }
    // The internal browser can inspect other owners. Opening the interview
    // still requires the existing owner/reviewer permission check.
    if (id && await canOpen(id)) {
      const target = saved?.searchParams.get("project") === id ? saved : new URL("/", location.origin);
      target.searchParams.set("project", id);
      return target.pathname + target.search;
    }
    if (saved?.searchParams.get("project") && await canOpen(saved.searchParams.get("project"))) return saved.pathname + saved.search;
    return "/";
  }
  for (const link of nav.querySelectorAll("a[data-interface]")) {
    const kind = link.dataset.interface;
    if (kind === mode) link.setAttribute("aria-current", "page");
    link.addEventListener("click", async event => {
      if (kind === mode) {event.preventDefault(); return;}
      if (!allowed || navigating) {event.preventDefault(); return;}
      if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      event.preventDefault(); navigating = true; nav.setAttribute("aria-busy", "true"); remember();
      try {location.assign(await destination(kind));}
      finally {navigating = false; nav.removeAttribute("aria-busy");}
    });
  }
  fetch("/api/access", {credentials: "same-origin", cache: "no-store", signal: AbortSignal.timeout(10000)})
    .then(response => response.ok ? response.json() : null)
    .then(access => {allowed = access?.is_admin === true; nav.hidden = !allowed;})
    .catch(() => {nav.hidden = true;});
  window.addEventListener("storage", event => {
    if (event.key !== "autokaggle-session-ended") return;
    allowed = false; nav.hidden = true;
    try {for (const kind of ["internal", "intake"]) sessionStorage.removeItem(storageKey(kind));} catch (_) {}
  });
})();
