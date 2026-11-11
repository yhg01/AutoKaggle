"use strict";
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const source = fs.readFileSync(path.join(__dirname, "..", "static", "workspace.js"), "utf8");
const start = source.indexOf("  async function api(");
const end = source.indexOf("  function notice(", start);
assert.ok(start >= 0 && end > start);

for (const status of [401, 403, 404, 500]) {
  test(`Session-tool HTTP ${status} uses account recovery only for access errors`, async () => {
    const events = [], requests = [];
    const api = new Function("fetch", "notify", source.slice(start, end) + "\nreturn api;")(
      async (url, options) => {
        requests.push({ url, options });
        return { ok: false, status, json: async () => ({ detail: "Unavailable" }) };
      }, (name) => events.push(name));
    await assert.rejects(api("/api/projects/p1/privacy", "PATCH", { accepted: true }),
      (error) => error.status === status && error.message === "Unavailable");
    assert.deepEqual(events, status === 500 ? [] : ["refresh"]);
    assert.equal(requests.length, 1);
    assert.equal(requests[0].options.credentials, "same-origin");
    assert.equal(requests[0].options.method, "PATCH");
    assert.equal(requests[0].options.body, JSON.stringify({ accepted: true }));
  });
}

function uiFunction(name, dependencies) {
  const definitions = [...source.matchAll(/^  (?:async )?function (\w+)\(/gm)];
  const index = definitions.findIndex(match => match[1] === name);
  assert.ok(index >= 0);
  const declaration = source.slice(definitions[index].index, definitions[index + 1]?.index ?? source.indexOf('  window.addEventListener("autokaggle:sources"'));
  return new Function(...Object.keys(dependencies), declaration + `\nreturn ${name};`)(...Object.values(dependencies));
}
function uiNode(tag, text, cls) {
  return { tag, textContent: text, className: cls, children: [], events: {}, value: "", disabled: false,
    append(...children) { this.children.push(...children); },
    setAttribute(key, value) { this[key] = value; },
    addEventListener(name, fn) { this.events[name] = fn; } };
}
class TestFormData { constructor() { this.parts = []; } append(...values) { this.parts.push(values); } }
function sourcesHarness(job, overrides = {}) {
  const ws = { id: "full-project", conversation: {}, busy: false, sourceDraft: null };
  const body = uiNode("div"); const nodes = {}; const buttons = []; const calls = []; const shows = []; const events = [];
  const api = async (path, method, payload) => { calls.push({ path, method, payload }); return method ? {} : job; };
  const deps = {
    ws, body, node: uiNode, section: () => {}, input: (label, id) => { const n = uiNode("input"); n.id = id; nodes[id] = n; return n; },
    button: (text, action) => { const n = uiNode("button", text); n.action = action; buttons.push(n); return n; },
    path: tail => `/api/projects/full-project${tail}`, api, requireIdle: () => { if (ws.busy) throw new Error("Busy"); },
    run: action => action(), notice: () => {}, show: async tab => shows.push(tab),
    crypto: { randomUUID: () => "request-source-test" }, FormData: TestFormData,
    dialog: { close: () => events.push("close") }, notify: name => events.push(name), setTimeout: () => 1,
    ...overrides,
  };
  return { render: uiFunction("sources", deps), ws, body, nodes, buttons, calls, shows, events };
}

test("Multipart PDF requests retain the browser boundary and private session", async () => {
  const requests = []; const form = new FormData(); form.append("file", new Blob(["%PDF-1.4"]), "paper.pdf");
  const api = new Function("fetch", "notify", source.slice(start, end) + "\nreturn api;")(
    async (url, options) => { requests.push({ url, options }); return { ok: true, json: async () => ({ uploaded_paper: {} }) }; }, () => {});
  await api("/api/projects/p1/sources/paper", "POST", form);
  assert.equal(requests[0].options.body, form);
  assert.deepEqual(requests[0].options.headers, {});
  assert.equal(requests[0].options.credentials, "same-origin");
});

test("A PDF upload preserves the repository draft and uses the Full source endpoint", async () => {
  const h = sourcesHarness({ status: "idle" }); await h.render();
  h.nodes["import-paper"].value = "https://example.org/old-paper";
  h.nodes["import-repository"].value = "https://github.com/lab/benchmark";
  const file = { name: "benchmark.pdf", size: 2000 };
  h.nodes["import-paper-file"].files = [file];
  h.nodes["import-paper-file"].value = "C:\\fakepath\\benchmark.pdf";
  await h.nodes["import-paper-file"].events.change();
  const request = h.calls.find(call => call.method === "POST");
  assert.equal(request.path, "/api/projects/full-project/sources/paper");
  assert.deepEqual(request.payload.parts, [["file", file]]);
  assert.deepEqual(h.ws.sourceDraft, { paper_url: "", repository_url: "https://github.com/lab/benchmark" });
  assert.deepEqual(h.shows, ["sources"]);
  assert.equal(h.nodes["import-paper-file"].value, "");
});

for (const failure of [new TypeError("Failed to fetch"), Object.assign(new Error("Research is busy"), { status: 409 })]) {
  test(`The same PDF can be selected again after ${failure.message}`, async () => {
    const requests = [];
    const h = sourcesHarness({ status: "idle" }, { api: async (path, method, payload) => {
      if (!method) return { status: "idle" };
      requests.push({ path, method, payload });
      if (requests.length === 1) throw failure;
      return {};
    } });
    await h.render();
    const paper = "https://example.org/paper";
    const repository = "https://github.com/lab/benchmark";
    h.nodes["import-paper"].value = paper;
    h.nodes["import-repository"].value = repository;
    const file = { name: "benchmark.pdf", size: 2000 };
    const upload = h.nodes["import-paper-file"];
    const chooseFile = async () => {
      // A browser emits change only when the selection changes.
      const selection = "C:\\fakepath\\benchmark.pdf";
      if (upload.value === selection) return;
      upload.value = selection; upload.files = [file];
      await upload.events.change();
    };
    await assert.rejects(chooseFile(), error => error === failure);
    assert.deepEqual(h.ws.sourceDraft, { paper_url: paper, repository_url: repository });
    assert.equal(h.nodes["import-paper"].value, paper);
    assert.equal(h.nodes["import-repository"].value, repository);
    assert.deepEqual(h.shows, []);
    await chooseFile();
    assert.equal(requests.length, 2);
    for (const request of requests) assert.deepEqual(request.payload.parts, [["file", file]]);
    assert.deepEqual(h.ws.sourceDraft, { paper_url: "", repository_url: repository });
    assert.equal(upload.value, "");
    assert.deepEqual(h.shows, ["sources"]);
  });
}

test("PDF upload rejects invalid types, oversized files, and missing storage consent", async () => {
  for (const file of [{ name: "paper.exe", size: 2 }, { name: "paper.pdf", size: 16 * 1048576 + 1 }]) {
    const h = sourcesHarness({ status: "idle" }); await h.render();
    h.nodes["import-paper-file"].files = [file];
    await assert.rejects(h.nodes["import-paper-file"].events.change(), /PDF file no larger than 16 MB/);
    assert.ok(h.calls.every(call => !call.method));
  }
  const h = sourcesHarness({ status: "idle" }); await h.render(); h.ws.conversation.storage = { required: true };
  h.nodes["import-paper-file"].files = [{ name: "paper.pdf", size: 2 }];
  await assert.rejects(h.nodes["import-paper-file"].events.change(), /Accept Data & privacy/);
  assert.ok(h.calls.every(call => !call.method));
});

test("A saved PDF can supply an import without another paper URL", async () => {
  const h = sourcesHarness({ status: "idle", uploaded_paper: { title: "Paper", sha256: "saved-digest" } }); await h.render();
  await h.buttons.find(button => button.textContent === "Import references").action();
  const request = h.calls.find(call => call.method === "POST");
  assert.equal(request.path, "/api/projects/full-project/sources");
  assert.deepEqual(request.payload, { paper_url: "", repository_url: "", request_id: "request-source-test" });
});

test("Source facts stay a proposal until the researcher applies the edited brief", async () => {
  const h = sourcesHarness({ status: "ready", proposal: { title: "Molecular benchmark", brief: "Source-backed definition", open_questions: ["Confirm the deployment inputs."] }, sources: [] });
  await h.render(); assert.ok(h.calls.every(call => !call.method));
  const brief = h.body.children.find(n => n.id === "source-brief");
  assert.equal(brief.maxLength, 6000);
  brief.value = "Edited benchmark definition.";
  await h.buttons.find(button => button.textContent === "Use this starting brief").action();
  const request = h.calls.find(call => call.method === "POST");
  assert.equal(request.path, "/api/projects/full-project/sources/apply");
  assert.deepEqual(request.payload, { brief: "Edited benchmark definition.", request_id: "request-source-test" });
  assert.deepEqual(h.events, ["close", "refresh"]);
});

test("An active source import disables replacement sources and duplicate import", async () => {
  const h = sourcesHarness({ status: "working", stage: "Reading source files" }); await h.render();
  for (const id of ["import-paper", "import-paper-file", "import-repository"]) assert.equal(h.nodes[id].disabled, true);
  assert.equal(h.buttons.find(button => button.textContent === "Import references").disabled, true);
});
