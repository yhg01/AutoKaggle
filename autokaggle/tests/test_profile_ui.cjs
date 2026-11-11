"use strict";
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "..", "static", "profile.js"), "utf8");
const flush = async () => { for (let i = 0; i < 4; i++) await new Promise(setImmediate); };
function harness(responses, search = "") {
  const nodes = new Map(), redirects = [], calls = [];
  const $ = id => {
    if (!nodes.has(id)) nodes.set(id, { value: "", disabled: true, hidden: true, events: {}, textContent: "", setAttribute() {}, focus() {}, reportValidity() { return this.value.trim().length > 0 && this.value.length <= 100; }, addEventListener(name, callback) { this.events[name] = callback; } });
    return nodes.get(id);
  };
  const location = { origin: "https://intake.example.org", pathname: "/profile", search, replace: value => redirects.push(value) };
  const fetch = async (url, options) => {
    calls.push({ url, options }); const response = responses.shift();
    if (response instanceof Error) throw response;
    if (typeof response === "function") return response();
    if (!response) throw new Error("Unexpected request " + url);
    return { ok: !(response.status >= 400), status: response.status || 200, json: async () => response.body || response };
  };
  vm.runInNewContext(source, { document: { getElementById: $ }, location, URL, URLSearchParams, AbortSignal, fetch });
  return { $, responses, redirects, calls, async submit() { await $("profile-form").events.submit({ preventDefault() {} }); await flush(); }, input() { $("researcher-name").events.input(); } };
}
const access = () => ({ csrf_token: "fresh-csrf" });

test("A verified account can save a name and return to the same challenge", async () => {
  const h = harness([access(), { account_id: "account-fixture", name: "" }, access(), { account_id: "account-fixture", name: "Antonio", is_admin: false }], "?next=%2F%3Fproject%3Dp1");
  await flush(); assert.equal(h.$("researcher-name").disabled, false); assert.equal(h.$("save-profile").disabled, true);
  h.$("researcher-name").value = " Antonio "; h.input(); assert.equal(h.$("save-profile").disabled, false);
  await h.submit();
  const call = h.calls.at(-1); assert.equal(call.url, "/api/access/profile"); assert.equal(call.options.method, "PATCH");
  assert.equal(call.options.credentials, "same-origin"); assert.equal(call.options.headers["X-CSRF-Token"], "fresh-csrf");
  assert.deepEqual(JSON.parse(call.options.body), { name: "Antonio", account_id: "account-fixture" }); assert.deepEqual(h.redirects, ["/?project=p1"]);
});

test("A saved name is loaded without changing it", async () => {
  const h = harness([access(), { account_id: "account-fixture", name: "Éduardo García" }]); await flush();
  assert.equal(h.$("researcher-name").value, "Éduardo García"); assert.equal(h.calls.length, 2); assert.equal(h.$("save-profile").disabled, false);
});

for (const next of ["https://other.example.org/", "//other.example.org/", "/internal", "/profile", "/api/internal/projects"]) {
  test(`A profile save keeps the redirect inside the allowed workspace: ${next}`, async () => {
    const h = harness([access(), { account_id: "account-fixture", name: "A" }, access(), { account_id: "account-fixture", name: "A", is_admin: false }], "?next=" + encodeURIComponent(next));
    await flush(); await h.submit(); assert.deepEqual(h.redirects, ["/"]);
  });
}

test("Administrator status from the saved response permits return to Internal", async () => {
  const h = harness([access(), { account_id: "account-fixture", name: "A" }, access(), { account_id: "account-fixture", name: "A", is_admin: true }], "?next=%2Finternal%3Fproject%3Dp1");
  await flush(); await h.submit(); assert.deepEqual(h.redirects, ["/internal?project=p1"]);
});

test("Validation failure keeps the typed name and allows a retry with fresh CSRF", async () => {
  const h = harness([access(), { account_id: "account-fixture", name: "" }, access(), { status: 400, body: { detail: "Enter a valid name." } }]);
  await flush(); h.$("researcher-name").value = "Researcher"; await h.submit();
  assert.equal(h.$("researcher-name").value, "Researcher"); assert.equal(h.$("researcher-name").disabled, false);
  assert.match(h.$("profile-status").textContent, /valid name/); assert.deepEqual(h.redirects, []);
  h.responses.push(access(), { account_id: "account-fixture", name: "Researcher", is_admin: false }); await h.submit(); assert.deepEqual(h.redirects, ["/"]);
});

test("Expired sign-in preserves the profile destination and disables further writes", async () => {
  const h = harness([access(), { account_id: "account-fixture", name: "A" }, access(), { status: 401, body: { detail: "Sign in again." } }], "?next=%2F%3Fproject%3Dp1");
  await flush(); await h.submit();
  assert.equal(h.$("profile-sign-in").hidden, false); assert.equal(h.$("researcher-name").disabled, true);
  assert.equal(h.$("profile-sign-in").href, "/login?next=" + encodeURIComponent("/profile?next=%2F%3Fproject%3Dp1"));
});

test("A slow save cannot create duplicate profile writes", async () => {
  let release;
  const h = harness([access(), { account_id: "account-fixture", name: "A" }, access(), () => new Promise(resolve => { release = resolve; })]);
  await flush(); const pending = h.submit(); await flush(); await h.submit();
  assert.equal(h.calls.filter(call => call.options.method === "PATCH").length, 1);
  release({ ok: true, json: async () => ({ account_id: "account-fixture", name: "A" }) }); await pending;
});

test("An unavailable profile does not enable saving or claim success", async () => {
  const h = harness([access(), new Error("Connection stopped.")]); await flush();
  assert.equal(h.$("researcher-name").disabled, true); assert.equal(h.$("save-profile").disabled, true);
  assert.match(h.$("profile-status").textContent, /Connection stopped/); assert.deepEqual(h.redirects, []);
});

test("An account switch requires a fresh form and cannot retry with the old identity", async () => {
  const h = harness([access(), { account_id: "first-account", name: "Antonio" }, access(), { status: 409, body: { detail: "Your signed-in account changed. Reload the profile before saving a name." } }]);
  await flush(); await h.submit();
  assert.equal(JSON.parse(h.calls.at(-1).options.body).account_id, "first-account");
  assert.equal(h.$("save-profile").disabled, true); assert.equal(h.$("profile-sign-in").hidden, false);
  assert.equal(h.$("profile-sign-in").textContent, "Reload profile"); assert.deepEqual(h.redirects, []);
});


for (const [next, expected] of [
  ["/workbench", "/"],
  ["/workbench?project=p1", "/?project=p1"],
  ["/workbench?project=p1&view=problem", "/?project=p1"],
  ["/workbench?view=review", "/"],
  ["/workbench?project=p1&view=review", "/workbench?project=p1&view=review"],
]) {
  test(`Saving a profile opens the agent unless a challenge review was selected: ${next}`, async () => {
    const h = harness([access(), { account_id: "account-fixture", name: "A" }, access(), { account_id: "account-fixture", name: "A", is_admin: false }], "?next=" + encodeURIComponent(next));
    await flush(); await h.submit(); assert.deepEqual(h.redirects, [expected]);
  });
}
