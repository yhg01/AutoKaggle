"use strict";

// Client checks supplement the live mail, browser, and model checks.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");
const source = fs.readFileSync(path.join(__dirname, "..", "static", "login.js"), "utf8");
const html = fs.readFileSync(path.join(__dirname, "..", "static", "login.html"), "utf8");
const flush = () => new Promise((resolve) => setImmediate(resolve));
const access = (extra = {}) => ({ private_mode: true, email_login_available: true, csrf_token: "fresh-csrf", ...extra });
const challenge = (extra = {}) => ({ challenge_id: "challenge-one", expires_in: 600, resend_after: 60, ...extra });
function harness(responses = [], search = "", storageValues = {}) {
  const elements = new Map(); const calls = []; const redirects = []; let now = 1_000_000;
  const $ = (id) => {
    if (!elements.has(id)) elements.set(id, { value: "", disabled: false, hidden: false, textContent: "", events: {}, attributes: {},
      classList: { values: new Set(), toggle(name, enable) { if (enable) this.values.add(name); else this.values.delete(name); } },
      addEventListener(event, fn) { this.events[event] = fn; }, setAttribute(key, val) { this.attributes[key] = val; },
      focus() { this.focused = true; }, reportValidity() { return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(this.value); },
    });
    return elements.get(id);
  };
  const intervals = []; const storage = { ...storageValues };
  Object.defineProperty(storage, "removeItem", { enumerable: false, value: (key) => { delete storage[key]; } });
  Object.defineProperty(storage, "setItem", { enumerable: false, value: (key, value) => { storage[key] = value; } });
  const sandbox = { document: { getElementById: $ }, URL, URLSearchParams, AbortController, Date: { now: () => now },
    window: { localStorage: storage, location: { search, origin: "https://intake.example.org", replace: (url) => redirects.push(url) },
      setTimeout: () => 1, clearTimeout() {}, setInterval: (fn) => intervals.push(fn) },
    fetch: async (url, options) => {
      calls.push({ url, options }); const next = responses.shift();
      if (next instanceof Error) throw next;
      if (!next) throw new Error(`Unexpected request ${url}`);
      if (typeof next === "function") return next();
      return { ok: !(next.status >= 400), status: next.status || 200, headers: { get: (key) => next.headers?.[key] ?? null },
        json: async () => { if (next.malformed) throw new Error("Invalid JSON"); return next.body === undefined ? next : next.body; } };
    },
  };
  vm.runInNewContext(source, sandbox);
  return { $, calls, responses, redirects, storage, async event(id, type = "submit") { $(id).events[type]({ preventDefault() {} }); await flush(); },
    tick(seconds) { now += seconds * 1000; for (const fn of intervals) fn(); } };
}
async function sent(search = "") {
  const h = harness([access(), access(), challenge()], search); await flush(); h.$("login-email").value = "researcher@example.org";
  await h.event("email-request-form"); return h;
}

test("The email form has one accessible OTP input and a collapsed administrator option", () => {
  assert.match(html, /id="email-code"[^>]*inputmode="numeric"[^>]*autocomplete="one-time-code"/);
  assert.match(html, /id="email-code"[^>]*maxlength="6"/);
  assert.match(html, /id="login-status" role="status" aria-live="polite"/);
  assert.match(html, /<details id="admin-access" class="admin-access">/);
  assert.doesNotMatch(source, /sessionStorage|console\./);
  assert.equal((source.match(/setItem\(/g) || []).length, 1, "Only a session-change timestamp is stored; no codes are stored");
});

test("Email is sent with a fresh CSRF token and same-origin cookies before code entry is shown", async () => {
  const h = await sent();
  assert.equal(h.$("email-code-form").hidden, false); assert.equal(h.$("email-request-form").hidden, true);
  assert.equal(h.$("login-email-sent").textContent, "researcher@example.org");
  assert.equal(h.calls[2].url, "/api/access/email/request");
  assert.equal(h.calls[2].options.headers["X-CSRF-Token"], "fresh-csrf");
  assert.equal(h.calls[2].options.credentials, "same-origin");
  assert.deepEqual(JSON.parse(h.calls[2].options.body), { email: "researcher@example.org" });
  assert.equal(h.$("email-code").focused, true); assert.equal(h.$("resend-code").disabled, true);
});

test("Successful verification clears the code and preserves a safe project destination", async () => {
  const h = await sent("?next=%2F%3Fproject%3Dmine"); h.responses.push(access({ csrf_token: "verify-csrf" }), { redirect: "/" });
  h.$("email-code").value = "123456"; await h.event("email-code", "input");
  assert.equal(h.$("verify-code").disabled, false); await h.event("email-code-form");
  assert.deepEqual(h.redirects, ["/?project=mine"]); assert.equal(h.$("email-code").value, "");
  assert.equal(h.calls.at(-1).options.headers["X-CSRF-Token"], "verify-csrf");
  assert.deepEqual(JSON.parse(h.calls.at(-1).options.body), { challenge_id: "challenge-one", code: "123456" });
});

test("Invalid email and incomplete codes make no submission request", async () => {
  const h = harness([access()]); await flush(); h.$("login-email").value = "not-an-email";
  await h.event("email-request-form"); assert.equal(h.calls.length, 1);
  const c = await sent(); c.$("email-code").value = "12x3"; await c.event("email-code", "input");
  assert.equal(c.$("email-code").value, "123"); assert.equal(c.$("verify-code").disabled, true);
  await c.event("email-code-form"); assert.equal(c.calls.length, 3);
});

test("An incorrect code is cleared and the same challenge can be retried", async () => {
  const h = await sent(); h.responses.push(access(), { status: 401, body: { detail: "The code is not valid." } });
  h.$("email-code").value = "123456"; await h.event("email-code-form");
  assert.equal(h.$("email-code").value, ""); assert.equal(h.$("email-code-form").hidden, false);
  assert.equal(h.$("login-status").textContent, "The code is not valid.");
  h.responses.push(access(), { redirect: "/" }); h.$("email-code").value = "654321";
  await h.event("email-code-form"); assert.deepEqual(h.redirects, ["/"]);
});

test("Resend waits for cooldown and uses the new challenge", async () => {
  const h = await sent(); await h.event("resend-code", "click"); assert.equal(h.calls.length, 3);
  h.tick(59); assert.equal(h.$("resend-code").disabled, true); h.tick(1);
  assert.equal(h.$("resend-code").disabled, false);
  h.responses.push(access(), challenge({ challenge_id: "challenge-two" })); await h.event("resend-code", "click");
  h.responses.push(access(), { redirect: "/" }); h.$("email-code").value = "123456"; await h.event("email-code-form");
  assert.equal(JSON.parse(h.calls.at(-1).options.body).challenge_id, "challenge-two");
});

test("Expired codes require a new request and cannot be submitted", async () => {
  const h = await sent(); h.tick(600); h.$("email-code").value = "123456"; await h.event("email-code", "input");
  assert.equal(h.$("verify-code").disabled, true); assert.equal(h.$("email-code").disabled, true);
  assert.match(h.$("code-help").textContent, /expired/); await h.event("email-code-form"); assert.equal(h.calls.length, 3);
});

test("A server expiry also disables a code and permits a later resend", async () => {
  const h = await sent(); h.responses.push(access(), { status: 410, body: { detail: "The code has expired." } });
  h.$("email-code").value = "123456"; await h.event("email-code-form");
  assert.equal(h.$("email-code").disabled, true); h.tick(60); assert.equal(h.$("resend-code").disabled, false);
});

test("Unavailable email service shows an honest state and leaves administrator sign-in usable", async () => {
  const h = harness([access({ email_login_available: false })]); await flush();
  assert.equal(h.$("email-unavailable").hidden, false); assert.equal(h.$("email-request-form").hidden, true);
  assert.equal(h.$("sign-in").disabled, false); assert.doesNotMatch(h.$("login-status").textContent, /sent/);
});

test("Mail failure never shows a sent state", async () => {
  const h = harness([access(), access(), { status: 503, body: { detail: "Email could not be sent." } }]); await flush();
  h.$("login-email").value = "researcher@example.org"; await h.event("email-request-form");
  assert.equal(h.$("email-code-form").hidden, true); assert.equal(h.$("email-unavailable").hidden, false);
  assert.equal(h.$("login-status").textContent, "Email could not be sent."); assert.equal(h.$("sign-in").disabled, false);
});

test("Rate limits enforce the server Retry-After before another email request", async () => {
  const h = harness([access(), access(), { status: 429, headers: { "Retry-After": "120" }, body: { detail: "Wait before trying again." } }]); await flush();
  h.$("login-email").value = "researcher@example.org"; await h.event("email-request-form");
  assert.equal(h.$("send-code").disabled, true); h.tick(119); assert.equal(h.$("send-code").disabled, true);
  h.tick(1); assert.equal(h.$("send-code").disabled, false);
});

test("Malformed server data does not open a code form or claim delivery", async () => {
  for (const invalid of [{ malformed: true }, { body: { challenge_id: "x" } }, { body: null }]) {
    const h = harness([access(), access(), invalid]); await flush(); h.$("login-email").value = "researcher@example.org";
    await h.event("email-request-form"); assert.equal(h.$("email-code-form").hidden, true);
    assert.ok(h.$("login-status").classList.values.has("error")); assert.equal(h.redirects.length, 0);
  }
});

test("A missing CSRF token leaves all sign-in submission controls disabled", async () => {
  const h = harness([access({ csrf_token: null })]); await flush();
  assert.equal(h.$("send-code").disabled, true); assert.equal(h.$("sign-in").disabled, true);
  assert.match(h.$("login-status").textContent, /Reload/);
});

test("Changing email clears the code and maintains the resend cooldown", async () => {
  const h = await sent(); h.$("email-code").value = "123456"; await h.event("change-email", "click");
  assert.equal(h.$("email-code").value, ""); assert.equal(h.$("email-request-form").hidden, false);
  assert.equal(h.$("login-email").value, "researcher@example.org"); assert.equal(h.$("send-code").disabled, true);
});

test("Administrator sign-in stays available and rejects external next URLs", async () => {
  const h = harness([access({ email_login_available: false }), access({ email_login_available: false }), { redirect: "/" }], "?next=https%3A%2F%2Fother.example.org%2F");
  await flush(); h.$("access-code").value = "private-code-for-client-test"; await h.event("login-form");
  assert.deepEqual(h.redirects, ["/"]); assert.equal(h.$("access-code").value, "");
  assert.equal(h.calls.at(-1).url, "/api/access/login");
});

test("An interrupted request keeps the email and lets the researcher try again", async () => {
  const h = harness([access(), access(), new Error("Connection interrupted")]); await flush();
  h.$("login-email").value = "researcher@example.org"; await h.event("email-request-form");
  assert.equal(h.$("email-code-form").hidden, true); assert.equal(h.$("login-email").value, "researcher@example.org");
  assert.equal(h.$("send-code").disabled, false); assert.equal(h.$("login-status").textContent, "Connection interrupted");
  h.responses.push(access(), challenge()); await h.event("email-request-form"); assert.equal(h.$("email-code-form").hidden, false);
});

test("Repeated clicks cannot send duplicate emails while a request is pending", async () => {
  let finish;
  const h = harness([access(), access(), () => new Promise((resolve) => { finish = resolve; })]); await flush();
  h.$("login-email").value = "researcher@example.org"; await h.event("email-request-form");
  assert.equal(h.$("send-code").disabled, true); await h.event("email-request-form"); assert.equal(h.calls.length, 3);
  finish({ ok: true, status: 200, headers: { get: () => null }, json: async () => challenge() }); await flush();
  assert.equal(h.$("email-code-form").hidden, false); assert.equal(h.calls.length, 3);
});

test("Successful sign-in clears prior account drafts and tells other tabs to sign in again", async () => {
  const h = harness([access(), access(), challenge(), access(), { redirect: "/" }], "", {
    "autokaggle-chat-last-project": "previous-project", "autokaggle-chat-compose:previous-project": "private draft",
    "autokaggle-chat-pending:previous-project": "private pending request", "autokaggle-chat-pending:previous-project:scope-drafts": "private scope", preference: "keep",
  }); await flush();
  h.$("login-email").value = "another@example.org"; await h.event("email-request-form");
  assert.equal(h.storage["autokaggle-chat-compose:previous-project"], "private draft", "Do not delete work before authentication succeeds");
  h.$("email-code").value = "123456"; await h.event("email-code-form");
  assert.deepEqual(h.storage, { preference: "keep", "autokaggle-session-ended": "1000000" });
});
