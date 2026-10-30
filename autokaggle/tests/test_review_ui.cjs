"use strict";

// Run the actual review-page script with a small DOM and fake transport.
// These checks do not call a server, runner, email service, or model.
const assert = require("node:assert/strict");
const { test } = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { webcrypto } = require("node:crypto");

const source = fs.readFileSync(path.join(__dirname, "..", "static", "review.js"), "utf8");

function harness({ mode = "prediction", storage = new Map(), storageBlocked = false, response, button = true } = {}) {
  const nodes = new Map();
  function node(id, extra = {}) {
    const value = { hidden: false, disabled: false, textContent: "", listeners: {},
      addEventListener(name, callback) { this.listeners[name] = callback; }, ...extra };
    nodes.set(id, value);
    return value;
  }
  const submit = node("submit-predictions");
  const next = button ? node("new-submission-attempt", { hidden: true }) : null;
  const result = node("submission-result");
  const container = node("submission", { dataset: { type: mode, project: "project-one", version: "version-one" } });
  const chooser = node("prediction-file", { files: [] });
  const calls = [];
  let sequence = 0;
  const context = {
    document: { getElementById(id) { return nodes.get(id) || null; } },
    crypto: { subtle: webcrypto.subtle, randomUUID: () => `request-number-${++sequence}` },
    TextEncoder,
    sessionStorage: {
      getItem(key) { if (storageBlocked) throw new Error("Blocked storage"); return storage.get(key) ?? null; },
      setItem(key, value) { if (storageBlocked) throw new Error("Blocked storage"); storage.set(key, value); },
      removeItem(key) { if (storageBlocked) throw new Error("Blocked storage"); storage.delete(key); },
    },
    fetch: async (url, options) => {
      const payload = JSON.parse(options.body);
      calls.push({ url, payload });
      return response ? response(calls.length, payload) : reply("scored");
    },
  };
  vm.runInNewContext(source, context);
  return { submit, next, result, container, calls, storage, context,
    choose(text, size = Buffer.byteLength(text)) { chooser.files = [{ size, text: async () => text }]; },
    async click(element = submit) { if (!element.disabled) await element.listeners.click(); },
  };
}

function reply(status, ok = true) {
  return { ok, json: async () => ({ status, metric: "accuracy", score: 0.5, remaining_today: 4, detail: "Recorded result." }) };
}

for (const status of ["scored", "invalid", "failed", "interrupted"]) {
  test(`${status}: explicit New attempt changes ID, while repeat click keeps ID`, async () => {
    const ui = harness({ response: () => reply(status) });
    ui.choose("_autokaggle_id,prediction\nvalidation-0,1\n");
    await ui.click();
    assert.equal(ui.next.hidden, false);
    assert.match(ui.result.textContent, /next submission will count/);
    await ui.click();
    assert.equal(ui.calls[1].payload.request_id, ui.calls[0].payload.request_id);
    await ui.click(ui.next);
    assert.equal(ui.next.hidden, true);
    assert.match(ui.result.textContent, /Ready for a new attempt/);
    await ui.click();
    assert.notEqual(ui.calls[2].payload.request_id, ui.calls[0].payload.request_id);
  });
}

test("network uncertainty preserves request ID and does not offer a new attempt", async () => {
  const ui = harness({ response: (count) => { if (count === 1) throw new Error("Connection lost"); return reply("scored"); } });
  ui.choose("predictions");
  await ui.click();
  assert.equal(ui.next.hidden, true);
  assert.equal(ui.submit.disabled, false);
  assert.equal(ui.result.textContent, "Connection lost");
  await ui.click();
  assert.equal(ui.calls[1].payload.request_id, ui.calls[0].payload.request_id);
});

test("HTTP and incomplete JSON errors keep the same retry identity", async () => {
  const ui = harness({ response: (count) => count === 1 ? reply("failed", false) : count === 2
    ? { ok: true, json: async () => { throw new Error("Response interrupted"); } } : reply("scored") });
  ui.choose("predictions");
  await ui.click();
  assert.equal(ui.next.hidden, true);
  await ui.click();
  assert.equal(ui.next.hidden, true);
  await ui.click();
  assert.equal(new Set(ui.calls.map(call => call.payload.request_id)).size, 1);
});

test("blocked storage uses memory for uncertain retries and explicit new attempts", async () => {
  const ui = harness({ storageBlocked: true, response: (count) => {
    if (count === 1) throw new Error("Connection lost");
    return reply("interrupted");
  } });
  ui.choose("predictions");
  await ui.click();
  await ui.click();
  assert.equal(ui.calls[1].payload.request_id, ui.calls[0].payload.request_id);
  await ui.click(ui.next);
  await ui.click();
  assert.notEqual(ui.calls[2].payload.request_id, ui.calls[0].payload.request_id);
});

test("New attempt clears only the current project and version", async () => {
  const storage = new Map([
    ["autokaggle-draft-upload:project-two:version-one", "other-project-state"],
    ["autokaggle-draft-upload:project-one:version-zero", "prior-version-state"],
  ]);
  const ui = harness({ storage });
  ui.choose("predictions");
  await ui.click();
  await ui.click(ui.next);
  assert.equal(storage.size, 2);
  assert.equal(storage.get("autokaggle-draft-upload:project-two:version-one"), "other-project-state");
  assert.equal(storage.get("autokaggle-draft-upload:project-one:version-zero"), "prior-version-state");
});

test("failed removal cannot resurrect an old stored request ID", async () => {
  const ui = harness();
  ui.choose("predictions");
  await ui.click();
  ui.context.sessionStorage.removeItem = () => { throw new Error("Storage changed"); };
  await ui.click(ui.next);
  await ui.click();
  assert.notEqual(ui.calls[1].payload.request_id, ui.calls[0].payload.request_id);
});

test("the saved request ID survives a page reload for the same file", async () => {
  const storage = new Map();
  const first = harness({ storage });
  first.choose("predictions");
  await first.click();
  const reloaded = harness({ storage });
  reloaded.choose("predictions");
  await reloaded.click();
  assert.equal(reloaded.calls[0].payload.request_id, first.calls[0].payload.request_id);
});

test("malformed saved state does not block submission", async () => {
  const storage = new Map([["autokaggle-draft-upload:project-one:version-one", "{incomplete"]]);
  const ui = harness({ storage });
  ui.choose("predictions");
  await ui.click();
  assert.equal(ui.calls.length, 1);
  assert.equal(ui.next.hidden, false);
});

test("code uploads retain their endpoint, payload field, and byte limit", async () => {
  const ui = harness({ mode: "code" });
  ui.choose("print('test')", 262145);
  await ui.click();
  assert.equal(ui.calls.length, 0);
  assert.match(ui.result.textContent, /256 KiB/);
  ui.choose("print('test')");
  await ui.click();
  assert.match(ui.calls[0].url, /\/workflow\/code-submissions$/);
  assert.equal(ui.calls[0].payload.source_code, "print('test')");
  assert.equal(ui.calls[0].payload.predictions_csv, undefined);
});

test("prediction uploads retain their size limit and endpoint", async () => {
  const ui = harness();
  ui.choose("predictions", 5000001);
  await ui.click();
  assert.equal(ui.calls.length, 0);
  assert.match(ui.result.textContent, /5 MB/);
  ui.choose("predictions");
  await ui.click();
  assert.match(ui.calls[0].url, /\/workflow\/submissions$/);
  assert.equal(ui.calls[0].payload.predictions_csv, "predictions");
});

test("an older preview without the new control can still submit", async () => {
  const ui = harness({ button: false });
  ui.choose("predictions");
  await ui.click();
  assert.equal(ui.calls.length, 1);
  assert.match(ui.result.textContent, /accuracy: 0.5/);
});

function invitationHarness({ token = "private-invitation-token", fail = false } = {}) {
  const open = { disabled: false, listeners: {}, addEventListener(name, callback) { this.listeners[name] = callback; } };
  const status = { textContent: "" }; const calls = []; const historyCalls = []; const redirects = [];
  const context = {
    document: { getElementById(id) { return id === "open-review" ? open : id === "review-status" ? status : null; } },
    URLSearchParams,
    location: { hash: token ? `#token=${token}` : "", pathname: "/review", assign: (url) => redirects.push(url) },
    history: { replaceState: (...args) => historyCalls.push(args) },
    fetch: async (url, options) => { calls.push({ url, options }); return { ok: !fail, json: async () => fail ? { detail: "The invitation expired." } : { redirect: "/?project=project-one&view=review" } }; },
  };
  vm.runInNewContext(source, context);
  return { open, status, calls, historyCalls, redirects };
}

test("An invitation removes its token from the URL and exchanges it only on a click", async () => {
  const ui = invitationHarness();
  assert.equal(ui.calls.length, 0); assert.equal(ui.open.disabled, false);
  assert.deepEqual(Array.from(ui.historyCalls[0]), [null, "", "/review"]);
  await ui.open.listeners.click();
  assert.equal(ui.calls[0].url, "/api/review/exchange");
  assert.equal(ui.calls[0].options.credentials, "same-origin");
  assert.deepEqual(JSON.parse(ui.calls[0].options.body), { token: "private-invitation-token" });
  assert.deepEqual(ui.redirects, ["/?project=project-one&view=review"]);
  assert.equal(ui.open.disabled, true);
});

test("Missing or expired invitations show useful errors without opening another project", async () => {
  const missing = invitationHarness({ token: "" });
  assert.equal(missing.open.disabled, true); assert.match(missing.status.textContent, /complete link/);
  const expired = invitationHarness({ fail: true }); await expired.open.listeners.click();
  assert.equal(expired.open.disabled, false); assert.equal(expired.status.textContent, "The invitation expired.");
  assert.deepEqual(expired.redirects, []);
});
