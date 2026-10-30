"use strict";

// Focused UI checks supplement live browser and model validation.
// These checks do not establish live integration coverage.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "..", "static", "chat.js"), "utf8");

function uiFunction(name, dependencies = {}) {
  const definitions = [...source.matchAll(/^  (?:async )?function (\w+)\(/gm)];
  const index = definitions.findIndex((match) => match[1] === name);
  assert.notEqual(index, -1, `UI function ${name} must exist`);
  const start = definitions[index].index;
  const end = definitions[index + 1]?.index ?? source.lastIndexOf("  init();");
  const declaration = source.slice(start, end);
  return new Function(...Object.keys(dependencies), `${declaration}\nreturn ${name};`)(...Object.values(dependencies));
}

const noop = () => {};
const coverageText = uiFunction("coverageText");
const immediateWindow = {
  setTimeout(callback) { callback(); return 0; },
  requestAnimationFrame(callback) { callback(); },
};

function node(tag = "div", className = "", text = "") {
  return {
    tag, className, textContent: text, children: [], attributes: {}, value: "",
    hidden: false, disabled: false, replaceCount: 0,
    scrollTop: 0, scrollHeight: 100, clientHeight: 100,
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = children; this.replaceCount += 1; },
    setAttribute(key, value) { this.attributes[key] = value; },
    addEventListener(event, callback) { this.events ||= {}; this.events[event] = callback; },
    focus(options) { this.focusOptions = options; },
  };
}

function dom() {
  const nodes = new Map();
  const $ = (id) => { if (!nodes.has(id)) nodes.set(id, node()); return nodes.get(id); };
  return { $, nodes };
}

function pollHarness(state, api) {
  const calls = { cleared: 0, errors: 0, viewChanges: 0 };
  const rememberPending = (value) => { if (value === null) calls.cleared += 1; state.pending = value; };
  const poll = uiFunction("pollWorking", {
    state, api, window: immediateWindow, updateControls: noop,
    renderConversation: noop, showError: () => { calls.errors += 1; },
    base: () => "/conversation", rememberPending,
    clearDeliveredCompose: () => { throw new Error("A GET must not acknowledge a message"); },
    setView: () => { calls.viewChanges += 1; },
  });
  return { poll, calls, rememberPending };
}

function dispatchHarness(state, api, overrides = {}) {
  const { $ } = dom();
  let composeSaves = 0;
  const rememberPending = (value) => { state.pending = value; };
  const rememberCompose = () => { composeSaves += 1; };
  const clearDeliveredCompose = uiFunction("clearDeliveredCompose", { $, rememberCompose });
  const dependencies = {
    state, api, $, window: immediateWindow, contactRequired: () => false,
    working: () => !!state.busy || !!state.polling || state.conversation?.status === "working",
    rememberPending, rememberCompose, clearDeliveredCompose,
    setView: (view) => { state.view = view; },
    setBusy: (busy) => { state.busy = busy; },
    base: () => "/conversation", renderConversation: noop,
    pollWorking: noop, refreshWorkflow: async () => {},
    showError: (text) => { state.localError = text; },
    userCount: () => (state.conversation?.messages || []).filter((message) => message.role === "user").length,
    crypto: { randomUUID: () => "new-request-id" },
    ...overrides,
  };
  return { dispatch: uiFunction("dispatch", dependencies), $, get composeSaves() { return composeSaves; } };
}

test("HTML references decode once and reject invalid code points", () => {
  const decode = uiFunction("decodeReferences");
  assert.equal(decode("Researcher&#x27;s A &amp; B &lt; 5 &quot;units&quot;"), 'Researcher\'s A & B < 5 "units"');
  assert.equal(decode("&#39; &#x1F9EA; &apos; &nbsp;"), "' 🧪 ' \u00a0");
  assert.equal(decode("&amp;lt;"), "&lt;", "Double-escaped text must not be decoded twice");
  assert.equal(decode("&#xD800; &#99999999999; &#0; &unknown;"), "&#xD800; &#99999999999; &#0; &unknown;");
});

test("Decoded script-like text remains a text node", () => {
  const decodeReferences = uiFunction("decodeReferences");
  const inline = uiFunction("inline", {
    decodeReferences,
    document: { createTextNode: (text) => ({ nodeType: 3, textContent: text }) },
    element: node,
  });
  const parent = node();
  inline(parent, "&lt;img src=x onerror=alert(1)&gt; &lt;script&gt;alert(2)&lt;/script&gt;");
  assert.ok(parent.children.every((child) => child.nodeType === 3));
  assert.equal(parent.children.map((child) => child.textContent).join(""), "<img src=x onerror=alert(1)> <script>alert(2)</script>");
  const unsafeLink = node();
  inline(unsafeLink, "[open](&#106;avascript:alert(1))");
  assert.ok(unsafeLink.children.every((child) => child.nodeType === 3));
});

test("Another tab finishing work does not clear this tab's pending request", async () => {
  const pending = { action: "messages", request_id: "second-tab", message: "My correction" };
  const state = { pending, polling: false, conversation: { status: "working" } };
  const harness = pollHarness(state, async () => ({ status: "idle", messages: [{ role: "user", content: "Other tab's message" }] }));
  await harness.poll();
  assert.equal(state.pending, pending);
  assert.equal(harness.calls.cleared, 0);
  assert.equal(harness.calls.viewChanges, 0);
  assert.equal(state.polling, false);
});

test("A failed status connection also preserves the pending payload", async () => {
  const pending = { action: "draft", request_id: "draft-awaiting-confirmation" };
  const state = { pending, polling: false, conversation: { status: "working" } };
  let attempts = 0;
  const harness = pollHarness(state, async () => { attempts += 1; throw new Error("Disconnected"); });
  await harness.poll();
  assert.equal(attempts, 3);
  assert.equal(state.pending, pending);
  assert.equal(harness.calls.cleared, 0);
  assert.equal(state.polling, false);
  assert.equal(state.conversation.status, "error");
  assert.equal(state.conversation.can_retry, true);
});

test("POST 409 followed by another job completing retains the unsent message", async () => {
  const state = { projectId: "p1", busy: false, polling: false, pending: null, conversation: { status: "idle", messages: [] } };
  let gets = 0;
  const api = async (_path, options) => {
    if (options?.method === "POST") { const error = new Error("Another action is active"); error.status = 409; throw error; }
    gets += 1;
    return gets === 1 ? { status: "working", messages: [] } : { status: "idle", messages: [{ role: "user", content: "Other tab's message" }] };
  };
  const { poll } = pollHarness(state, api);
  const harness = dispatchHarness(state, api, { pollWorking: poll });
  harness.$("message-input").value = "My unsent correction";
  await harness.dispatch("messages", "My unsent correction");
  assert.equal(gets, 2);
  assert.equal(state.pending.request_id, "new-request-id");
  assert.equal(state.pending.message, "My unsent correction");
  assert.equal(state.busy, false);
});

test("Retry uses the same request ID and clears pending only after its POST succeeds", async () => {
  const pending = { project_id: "p1", action: "messages", request_id: "already-accepted-id", message: "Recorded answer", before_user_count: 0 };
  const transcript = [{ id: "existing-user", role: "user", content: "Recorded answer" }, { id: "existing-reply", role: "assistant", content: "Next question" }];
  const state = { projectId: "p1", busy: false, polling: false, pending, conversation: { status: "idle", messages: transcript } };
  const requests = [];
  const harness = dispatchHarness(state, async (route, options) => {
    requests.push({ route, body: JSON.parse(options.body) });
    return { status: "idle", messages: transcript };
  });
  harness.$("message-input").value = "A separate, unsent correction";
  await harness.dispatch(pending.action, pending.message, pending);
  assert.deepEqual(requests, [{ route: "/conversation/messages", body: { request_id: "already-accepted-id", message: "Recorded answer" } }]);
  assert.equal(state.pending, null);
  assert.equal(state.conversation.messages, transcript, "Replay must use the server transcript without adding a duplicate");
  assert.equal(harness.$("message-input").value, "A separate, unsent correction");
  assert.equal(harness.composeSaves, 0);
});

function messageHarness(messages, pending) {
  const { $ } = dom();
  const state = { projectId: "p1", conversation: { messages }, pending, messageKey: "" };
  const render = uiFunction("renderMessages", {
    state, $, element: node, markdown: (text, className) => node("div", className, text),
    document: { createTextNode: (text) => ({ nodeType: 3, textContent: text }) },
    window: immediateWindow, working: () => false,
    userCount: () => state.conversation.messages.filter((message) => message.role === "user").length,
  });
  return { state, render, $ };
}

test("Repeated server transcripts do not duplicate visible messages", () => {
  const messages = [{ id: "u1", role: "user", content: "My answer" }, { id: "a1", role: "assistant", content: "Thank you" }];
  const pending = { action: "messages", request_id: "r1", message: "My answer", before_user_count: 0 };
  const harness = messageHarness(messages, pending);
  harness.render();
  assert.equal(harness.$("messages").children.length, 2, "An answer already present in new history needs no extra pending bubble");
  const replaces = harness.$("messages").replaceCount;
  harness.render();
  assert.equal(harness.$("messages").replaceCount, replaces, "An unchanged transcript should not be replaced");
  assert.equal(harness.state.pending, pending, "Display deduplication does not acknowledge the request");
});

test("An unrelated message or an older identical answer cannot hide a new pending correction", () => {
  for (const [messages, before_user_count] of [
    [[{ id: "u1", role: "user", content: "Other tab's message" }], 0],
    [[{ id: "u1", role: "user", content: "My answer" }], 1],
  ]) {
    const pending = { action: "messages", request_id: "new-message", message: "My answer", before_user_count };
    const harness = messageHarness(messages, pending);
    harness.render();
    assert.equal(harness.$("messages").children.length, 2);
    const last = harness.$("messages").children.at(-1);
    assert.equal(last.children[0].textContent, "You · awaiting confirmation");
    assert.equal(last.children[1].textContent, "My answer");
  }
});

test("All error states block Send and Skip but allow editing and drafting", () => {
  for (const can_retry of [true, false]) {
    const { $ } = dom();
    $("message-input").value = "A new correction";
    const state = { projectId: "p1", pending: null, conversation: { status: "error", can_retry, current_question: { text: "What is the target?" }, messages: [{ role: "user", content: "My problem" }] } };
    const update = uiFunction("updateControls", { state, $, working: () => false, userCount: () => 1, contactRequired: () => false, reviewAvailable: () => true, renderContact: noop, renderReviewControls: noop, renderError: noop, updateSetupControls: noop, updateBypassControls: noop, updateWorkflowControls: noop, updateDataControls: noop });
    update();
    assert.equal($("send-message").disabled, true);
    assert.equal($("skip-question").disabled, true);
    assert.equal($("message-input").disabled, false);
    assert.equal($("draft-readme").disabled, false);
  }
});


test("An explicit project link takes priority over the stored conversation", async () => {
  const opened = [];
  const initialize = uiFunction("initializeProject", {
    window: { location: { search: "?project=review-project" } },
    openProject: async (id) => { opened.push(id); },
    refreshProjects: async () => { throw new Error("The explicit project must be verified directly"); },
    readStorage: () => "previous-project", LAST_PROJECT: "last", state: {},
    createProject: () => { throw new Error("An explicit project must not create a different conversation"); },
  });
  await initialize();
  assert.deepEqual(opened, ["review-project"]);
});

test("An inaccessible explicit project does not fall back to another conversation", async () => {
  const initialize = uiFunction("initializeProject", {
    window: { location: { search: "?project=not-owned" } },
    openProject: async () => { throw new Error("Not found"); },
    refreshProjects: async () => {}, readStorage: () => "previous-project", LAST_PROJECT: "last", state: {},
    createProject: () => { throw new Error("Must not create a replacement"); },
  });
  await assert.rejects(initialize(), /Not found/);
});

test("A review session at the home page opens its granted project without creating one", async () => {
  const opened = [];
  const initialize = uiFunction("initializeProject", {
    window: { location: { search: "" } },
    openProject: async (id) => { opened.push(id); },
    refreshProjects: async () => {}, readStorage: () => "unrelated-project", LAST_PROJECT: "last",
    state: { projects: [{ id: "granted-project" }], config: { can_create_projects: false } },
    createProject: () => { throw new Error("Review access cannot create a challenge"); },
  });
  await initialize();
  assert.deepEqual(opened, ["granted-project"]);
});

test("An expired review session returns to sign-in instead of creating a challenge", async () => {
  const destinations = [];
  const initialize = uiFunction("initializeProject", {
    window: { location: { search: "", replace: (path) => destinations.push(path) } },
    openProject: async () => { throw new Error("No project is accessible"); },
    refreshProjects: async () => {}, readStorage: () => null, LAST_PROJECT: "last",
    state: { projects: [], config: { can_create_projects: false } },
    createProject: () => { throw new Error("An expired session cannot create a challenge"); },
  });
  await initialize();
  assert.deepEqual(destinations, ["/login"]);
});

test("The new challenge action checks the creation capability before any request", async () => {
  const create = uiFunction("createProject", {
    state: { config: { can_create_projects: false } },
    api: async () => { throw new Error("No creation request is permitted"); },
    openProject: async () => {},
  });
  await assert.rejects(create(), /Sign in with your email/);
});

test("Workflow states distinguish drafts, ready for review, and earlier versions", () => {
  const present = uiFunction("workflowPresentation");
  assert.equal(present(null).text[0], "Not built");
  assert.equal(present({ status: "draft" }).text[0], "Draft files");
  assert.equal(present({ status: "ready_for_review" }).text[0], "Ready for review");
  assert.match(present({ status: "ready_for_review" }).text[1], /organizer still needs to review/);
  assert.equal(present({ status: "stale" }).text[0], "Earlier version");
  assert.equal(present({ status: "unexpected" }).text[0], "Status unavailable");
});

test("Only an explicit sent status is shown as email sent", () => {
  const { $ } = dom();
  const state = { projectId: "p1", workflow: null };
  const render = uiFunction("renderWorkflow", {
    state, $, element: node,
    workflowPresentation: uiFunction("workflowPresentation"),
    document: { createTextNode: (text) => ({ textContent: text }) },
    safeWebLink: uiFunction("safeWebLink", { window: { location: { origin: "http://localhost:8877" } } }),
    projectPath: () => "/api/projects/p1", updateWorkflowControls: noop, renderReview: noop, reviewAvailable: () => false,
  });
  for (const status of ["not_ready", "not_configured", "pending", "failed", "unknown", "sent"]) {
    state.workflow = { status: "draft", checks: [], artifacts: [], notification: { status }, review_url: "javascript:alert(1)", download_url: "https://untrusted.invalid/package" };
    render();
    assert.equal($("notification-status").textContent === "Email sent", status === "sent");
    if (status === "sent") { assert.equal($("retry-notification").textContent, "Send a new review link"); assert.equal($("retry-notification").hidden, false); }
    assert.equal($("review-link").hidden, true, "A script URL must never become a link");
    assert.equal($("download-package").href, "/api/projects/p1/workflow/package", "ZIP downloads stay on the owner API");
  }
});

test("An interrupted package build requires a status check before another POST", async () => {
  const { $ } = dom();
  const state = { projectId: "p1", conversation: { readme: "# Draft" }, workflowBusy: false, workflowLoading: false, workflowUncertain: false, pending: null };
  let posts = 0;
  const run = uiFunction("runWorkflow", {
    state, $, working: () => !!state.workflowBusy, contactRequired: () => false, projectPath: () => "/api/projects/p1",
    api: async () => { posts += 1; throw new Error("Connection lost"); }, updateControls: noop, renderWorkflow: noop,
  });
  await run(); await run();
  assert.equal(posts, 1);
  assert.equal(state.workflowUncertain, true);
  assert.match(state.workflowError, /Check status/);
});

test("Workflow and data reads block concurrent changes until their state is current", () => {
  for (const flag of ["workflowLoading", "workflowBusy", "dataLoading", "dataBusy"]) {
    const state = { [flag]: true, conversation: { status: "idle" } };
    assert.equal(uiFunction("working", { state })(), true);
  }
});

test("Data defaults keep the 80/20 split and clear column selections missing from a replacement file", () => {
  const defaults = uiFunction("dataDefaults");
  const result = defaults({ dataset: { columns: [{ name: "feature" }, { name: "answer" }] }, design: { target: "answer", group_column: "removed", exclude_columns: ["removed", "answer", "feature", "feature"] }, answers: { data_origin: "private", rights: "yes", compute_budget: "$20" } });
  assert.equal(result.design.test_fraction, 0.2);
  assert.equal(result.design.split, "random");
  assert.equal(result.design.group_column, "");
  assert.deepEqual(result.design.exclude_columns, ["feature"]);
  assert.equal(result.answers.compute_budget, "$20");
  assert.equal(result.answers.labels_public, "unknown");
});

test("The data PATCH contains only evaluation design and data metadata", () => {
  const { $ } = dom();
  const values = { "data-target": "label", "data-task": "classification", "data-metric": "balanced_accuracy", "data-split": "group", "data-group-column": "patient", "data-time-column": "", "data-origin-choice": "private", "data-labels-public": "no", "data-rights": "yes", "data-compute-budget": " $20 ", "data-token-budget": "$5" };
  for (const [id, value] of Object.entries(values)) $(id).value = value;
  const collect = uiFunction("collectDataForm", { $, document: { querySelectorAll: () => [{ value: "label" }, { value: "proxy" }] } });
  const payload = collect();
  assert.deepEqual(Object.keys(payload), ["design", "answers"]);
  assert.equal(payload.design.split, "group");
  assert.equal(payload.design.group_column, "patient");
  assert.equal(payload.design.test_fraction, 0.2);
  assert.deepEqual(payload.design.exclude_columns, ["proxy"]);
  assert.equal(payload.answers.compute_budget, "$20");
  assert.ok(!("organizer_email" in payload.answers));
});

test("Data edits are saved before the baseline runs and the conversation checklist stays intact", async () => {
  const { $ } = dom(); $("data-form").reportValidity = () => true;
  const checklist = [{ id: "question", status: "answered", value: "Existing scientific question" }];
  const state = { projectId: "p1", pending: null, dataProject: { id: "p1", dataset: {} }, dataDirty: true, dataBusy: false, conversation: { checklist } };
  const calls = []; const payload = { design: { target: "label" }, answers: { rights: "yes" } };
  const api = async (route, options) => { calls.push([route, options.method]); return { id: "p1", title: "My question", dataset: {}, analysis: route.endsWith("/analyze") ? { summary: { blockers: 0 } } : null }; };
  const renderDataForm = (project) => { state.dataProject = project; state.dataDirty = false; };
  const saveDataIfNeeded = uiFunction("saveDataIfNeeded", { state, api, projectPath: () => "/api/projects/p1", collectDataForm: () => payload, renderDataForm, invalidateWorkflow: noop });
  const run = uiFunction("runDataAction", { state, $, working: () => state.dataBusy, api, projectPath: () => "/api/projects/p1", renderDataForm, saveDataIfNeeded, dataMessage: noop, updateControls: noop, invalidateWorkflow: noop, refreshWorkflow: async () => { calls.push(["workflow", "GET"]); } });
  await run("analyze");
  assert.deepEqual(calls, [["/api/projects/p1", "PATCH"], ["/api/projects/p1/analyze", "POST"], ["workflow", "GET"]]);
  assert.equal(state.conversation.checklist, checklist);
  assert.equal(state.dataProject.analysis.summary.blockers, 0);
  assert.equal(state.dataBusy, false);
});

test("Synthetic example loading is blocked when a dataset already exists or consent is missing", async () => {
  const { $ } = dom();
  const state = { projectId: "p1", dataProject: { dataset: {} }, pending: null };
  const run = uiFunction("runDataAction", { state, $, working: () => false, api: () => { throw new Error("The example must not be loaded"); } });
  $("data-example-confirm").checked = true; await run("example");
  state.dataProject.dataset = null; $("data-example-confirm").checked = false; await run("example");
});

test("Unsaved data changes prevent package creation", async () => {
  const state = { dataDirty: true, conversation: { readme: "# Draft" } };
  const run = uiFunction("runWorkflow", { state, working: () => false, contactRequired: () => false, api: () => { throw new Error("Unsaved data must not build a package"); } });
  await run();
});

test("Baseline rendering uses the measured scores, including zero, and marks the final test as unscored", () => {
  const { $ } = dom();
  const render = uiFunction("renderDataAnalysis", { $, element: node, displayScore: uiFunction("displayScore") });
  render({ summary: { blockers: 0, warnings: 1, passed: 3 }, baseline: { metric: "accuracy", score: 0, dummy_score: 0.5, validation_rows: 20 }, split: { train_rows: 80, test_rows: 20 }, checks: [] });
  const flatten = (entry) => [entry.textContent, ...entry.children.map(flatten)].join(" ");
  const text = flatten($("data-baseline"));
  assert.match(text, /Simple model 0/);
  assert.match(text, /Dummy reference 0.5/);
  assert.match(text, /final hidden test was not scored/);
  assert.equal($("data-audit-summary").textContent, "0 blocking checks · 1 warnings · 3 passed");
});


function interviewHarness(conversation) {
  const constants = source.slice(source.indexOf("  const topics ="), source.indexOf("  function element"));
  const { topics, statusLabels } = new Function(`${constants}; return { topics, statusLabels };`)();
  const state = { conversation, selectedTopic: null };
  const checklistItems = uiFunction("checklistItems", { state });
  const itemUnderstanding = uiFunction("itemUnderstanding");
  const interviewTopics = uiFunction("interviewTopics", { state, checklistItems, topics, statusLabels, itemUnderstanding });
  const knowledgeGroups = uiFunction("knowledgeGroups", { interviewTopics, checklistItems });
  return { state, topics, statusLabels, checklistItems, interviewTopics, itemUnderstanding, knowledgeGroups, coverageText };
}

test("Server stage fields and progress control notes without claiming verification", () => {
  const harness = interviewHarness({
    checklist: [{ id: "question", value: "Predict damage", status: "answered" }, { id: "difficulty", value: "Published method with 0.8 AUC", status: "answered" }, { id: "trial", value: "Not yet executed", status: "missing" }],
    interview: { stages: [{ id: "baseline", fields: ["difficulty"], status: "answered", answered: 1, total: 1 }] },
  });
  const stages = harness.interviewTopics();
  assert.deepEqual(stages.map((stage) => stage.id), ["problem", "approach", "baseline", "setup"]);
  assert.deepEqual(stages[2].fields, ["difficulty"]);
  assert.equal(stages[2].status, "answered", "An application execution check must not cause more researcher questions");
  assert.equal(harness.statusLabels.answered, "Recorded", "A collected answer is not a verified baseline result");
});

test("Old drafts retain recorded data and reference method under the correct topics", () => {
  const harness = interviewHarness({ checklist: [
    { id: "question", status: "answered", value: "Scientific question" },
    { id: "data", status: "partial", value: "CSV" },
    { id: "difficulty", status: "answered", value: "Existing method" },
    { id: "deployment", status: "deferred", value: "" },
  ] });
  const stages = harness.interviewTopics();
  assert.equal(stages[0].status, "partial");
  assert.equal(stages[1].status, "deferred");
  assert.equal(stages[2].status, "answered");
  assert.ok(!stages[0].fields.includes("difficulty"));
  assert.ok(stages[2].fields.includes("difficulty"));
});

test("The opening assistant message is shown before the researcher replies", () => {
  const harness = messageHarness([{ id: "greeting", role: "assistant", content: "What scientific outcome do you want to improve?" }], null);
  harness.render();
  assert.equal(harness.$("welcome").hidden, true, "Do not duplicate the static greeting");
  assert.equal(harness.$("messages").children.length, 1);
  assert.equal(harness.$("messages").children[0].children[1].textContent, "What scientific outcome do you want to improve?");
});

test("Collected notes show answers and deferred questions without an unanswered form list", () => {
  const harness = interviewHarness({ checklist: [
    { id: "question", label: "Scientific goal", status: "answered", value: "Reduce false alarms" },
    { id: "data", label: "Data", status: "missing", value: "" },
    { id: "difficulty", label: "Reference method", status: "deferred", value: "", gap: "Find the strongest reference." },
    { id: "organizer", label: "Organizer email", status: "answered", value: "owner@example.test" },
  ] });
  const { $ } = dom();
  const render = uiFunction("renderSummary", { ...harness, $, element: node });
  render();
  const flatten = (entry) => [entry.textContent, ...entry.children.map(flatten)].join(" ");
  let text = flatten($("summary-content"));
  assert.match(text, /Reduce false alarms/);
  assert.match(text, /Open question: Find the strongest reference/);
  assert.match(text, /owner@example.test/);
  assert.doesNotMatch(text, /Data/);
  harness.state.selectedTopic = "baseline"; render();
  text = flatten($("summary-content"));
  assert.match(text, /Reference method/);
  assert.doesNotMatch(text, /owner@example.test|Reduce false alarms/);
});

test("Interview screen has no setup form and retains secondary review and data controls", () => {
  const html = fs.readFileSync(path.join(__dirname, "..", "static", "chat.html"), "utf8");
  assert.doesNotMatch(html, /class="checklist-sidebar"|id="setup-form"|id="competition-prediction"|id="daily-submission-limit"/);
  for (const id of ["interview-topics", "summary-dialog", "open-data", "data-dialog", "build-workflow", "download-package", "draft-readme", "new-project"]) assert.ok(html.includes(`id="${id}"`), `${id} remains available`);
  assert.match(html, /Describe the situation, the current difficulty/);
});


test("Older checklist payloads show honest knowledge levels and keep system checks separate", () => {
  const understanding = uiFunction("itemUnderstanding");
  for (const item of [
    { status: "missing", value: "Default: five per day" },
    { status: "deferred", value: "Unknown" },
    { status: "answered", value: "" },
    { status: "partial", value: "Not sure" },
    { id: "difficulty", status: "deferred", value: "Baseline: unknown. I do not know yet." },
    { status: "deferred", value: "The reference method is unknown for now." },
  ]) assert.equal(understanding(item).score, 0);
  for (const item of [
    { status: "partial", value: "Ten years of sensor data" },
    { status: "deferred", value: "The method is a random forest, but the score is unknown." },
    { status: "answered", value: "Predict damage in one day", understanding: { score: 100, label: "Enough to draft" } },
  ]) {
    assert.equal(understanding(item).score, 0, "An old answered flag cannot establish that required decisions are resolved");
    assert.equal(understanding(item).label, "Assessment pending");
  }
  assert.equal(understanding({ id: "trial", status: "answered", value: "A researcher says it ran" }).score, null);
  assert.equal(understanding({ owner: "agent", status: "answered", value: "A system check" }).score, null);
});

test("Requirement counts accept granular progress and exclude application work", () => {
  const harness = interviewHarness({ checklist: [
    { id: "question", value: "An unresolved question", status: "partial", understanding: { score: 33, completed: 1, total: 3, label: "Details needed", detail: "No useful target" } },
    { id: "task", value: "Predict damage", status: "answered", understanding: { score: 100, completed: 1, total: 1 } },
    { id: "data", value: "Sensors", status: "partial", understanding: { score: 0, completed: 0, total: 4 } },
    { id: "trial", owner: "agent", status: "answered", value: "Run" },
    { id: "organizer", status: "missing" },
  ] });
  assert.equal(harness.interviewTopics()[0].understanding.score, 25, "Progress is weighted by requirement count rather than an average of item scores");
  assert.equal(harness.interviewTopics()[0].understanding.completed, 2);
  assert.equal(harness.interviewTopics()[0].understanding.total, 8);
  assert.equal(harness.itemUnderstanding(harness.checklistItems()[0]).score, 33);
  assert.deepEqual(harness.knowledgeGroups().find((group) => group.id === "setup").fields, ["organizer"]);
});

function checklistHarness(conversation) {
  const harness = interviewHarness(conversation); const { $ } = dom();
  const document = { activeElement: null };
  const understandingBar = uiFunction("understandingBar", { element: node, coverageText });
  const renderKnowledge = uiFunction("renderKnowledge", { ...harness, $, element: node, understandingBar, showSummary: noop });
  const calls = { reveal: 0 };
  const renderReadiness = uiFunction("renderReadiness", { state: harness.state, $, coverageText });
  const renderChecklist = uiFunction("renderChecklist", { ...harness, $, element: node, understandingBar, renderReadiness, renderKnowledge, renderSummary: noop, document, setView: (view) => { harness.state.view = view; }, revealKnowledgeQuestion: () => { calls.reveal += 1; } });
  return { ...harness, $, document, renderChecklist, calls };
}

test("Checklist stays visible, follows the next question, and preserves the inspected topic between updates", () => {
  const harness = checklistHarness({
    current_question: { field: "question", text: "What is the scientific goal?" },
    checklist: [{ id: "question", label: "Scientific goal", status: "missing", active: true }, { id: "organizer", label: "Organizer email", status: "missing" }],
    interview: { current_stage: "problem" },
  });
  harness.renderChecklist();
  assert.equal(harness.$("knowledge-topic").textContent, "Problem");
  assert.equal(harness.$("knowledge-items").children[0].children[0].children[0].textContent, "Scientific goal");
  assert.equal(harness.$("interview-topics").children[0].attributes["aria-pressed"], "true");
  harness.state.knowledgeTopic = "setup"; harness.renderChecklist();
  assert.equal(harness.$("knowledge-topic").textContent, "Setup");
  const replacements = harness.$("knowledge-items").replaceCount;
  harness.$("knowledge-items").scrollTop = 31;
  harness.renderChecklist();
  assert.equal(harness.$("knowledge-items").replaceCount, replacements, "Unchanged polling must preserve the existing focused controls");
  assert.equal(harness.$("knowledge-items").scrollTop, 31);
  harness.state.conversation.current_question = { field: "organizer", text: "What is your email?" };
  harness.state.conversation.checklist[0].active = false;
  harness.state.conversation.checklist[1].active = true;
  harness.state.conversation.interview.current_stage = null;
  harness.state.knowledgeTopic = "problem";
  harness.renderChecklist();
  assert.equal(harness.$("knowledge-topic").textContent, "Setup", "An organizer question must automatically show its checklist");
  assert.equal(harness.$("knowledge-items").children[0].className, "knowledge-item active");
});

test("A checklist item exposes accessible score, facts, and unresolved gaps", () => {
  const harness = interviewHarness({ checklist: [{ id: "data", label: "Dataset", value: "Sensor CSV", gap: "License not confirmed", status: "partial", required: true, requirements: [
    { id: "source", label: "Source link", status: "recorded", value: "https://example.org/sensors.csv", evidence: [{ message_id: "user-1", quotes: ["The source is https://example.org/sensors.csv"] }] },
    { id: "permission", label: "Data permission", status: "deferred", reason: "License not confirmed" },
  ] }] });
  harness.state.selectedTopic = "problem"; harness.state.selectedItem = "data";
  const { $ } = dom();
  uiFunction("renderSummary", { ...harness, $, element: node })();
  const flatten = (entry) => [entry.textContent, ...entry.children.map(flatten)].join(" ");
  assert.match(flatten($("summary-content")), /1 of 2 details · Required/);
  assert.match(flatten($("summary-content")), /Source link · Recorded/);
  assert.match(flatten($("summary-content")), /The source is https:\/\/example.org\/sensors.csv/);
  assert.match(flatten($("summary-content")), /Data permission · Unresolved/);
  assert.match(flatten($("summary-content")), /Sensor CSV/);
  assert.match(flatten($("summary-content")), /License not confirmed/);
  const bar = uiFunction("understandingBar", { element: node, coverageText })(50, "Dataset understanding");
  assert.equal(bar.tag, "progress"); assert.equal(bar.value, 50); assert.equal(bar.max, 100);
  assert.equal(bar.attributes["aria-label"], "Dataset understanding");
  assert.equal(bar.attributes["aria-valuetext"], "50% of requirements recorded");
});


test("Topic navigation from the draft reveals the conversation and resets another group's scroll", () => {
  const harness = checklistHarness({ checklist: [
    { id: "question", label: "Scientific question", status: "answered", value: "Predict damage" },
    { id: "methodology", label: "Method", status: "missing" },
  ], interview: { current_stage: null } });
  harness.renderChecklist();
  harness.state.view = "readme";
  harness.$("knowledge-items").scrollTop = 90;
  harness.$("interview-topics").children[1].events.click();
  assert.equal(harness.state.view, "chat");
  assert.equal(harness.$("knowledge-topic").textContent, "Method & deployment");
  assert.equal(harness.$("knowledge-items").scrollTop, 0);
  harness.$("knowledge-items").scrollTop = 35;
  harness.state.conversation.checklist[1].value = "Use any method";
  harness.renderChecklist();
  assert.equal(harness.$("knowledge-items").scrollTop, 35, "Updates in the same group keep the researcher's scroll position");
});

test("A new question in the same topic makes the active checklist item visible", () => {
  const harness = checklistHarness({
    current_question: { field: "methodology", text: "What method?" },
    checklist: [{ id: "methodology", label: "Method", status: "missing", active: true }, { id: "protocol", label: "Protocol", status: "missing" }],
    interview: { current_stage: "approach" },
  });
  harness.renderChecklist();
  const before = harness.calls.reveal;
  harness.renderChecklist();
  assert.equal(harness.calls.reveal, before, "Polling must not reset manual inspection");
  harness.state.conversation.current_question = { field: "protocol", text: "What is the protocol?" };
  harness.state.conversation.checklist[0].active = false;
  harness.state.conversation.checklist[1].active = true;
  harness.renderChecklist();
  assert.equal(harness.calls.reveal, before + 1);
  const root = node(); root.clientHeight = 80; root.scrollTop = 20;
  root.getBoundingClientRect = () => ({ top: 100, bottom: 180 });
  const active = node(); active.getBoundingClientRect = () => ({ top: 190, bottom: 218 });
  root.querySelector = () => active;
  const reveal = uiFunction("revealKnowledgeQuestion", { $: () => root });
  reveal(); assert.equal(root.scrollTop, 58, "Scroll only enough to show the lower active row");
  active.getBoundingClientRect = () => ({ top: 86, bottom: 114 });
  reveal(); assert.equal(root.scrollTop, 44, "The active row above the viewport also becomes visible");
  active.getBoundingClientRect = () => ({ top: 120, bottom: 148 });
  reveal(); assert.equal(root.scrollTop, 44, "A visible row must not move the checklist");
});

test("The private email gate blocks conversation changes without clearing the existing transcript", async () => {
  const { $ } = dom();
  const messages = [{ role: "user", content: "A saved research problem" }];
  const state = { projectId: "p1", view: "chat", conversation: { messages, readme: "# Earlier draft", setup: { organizer_email: "" } } };
  const contactRequired = uiFunction("contactRequired", { state });
  assert.equal(contactRequired(), true);
  const tabs = node();
  uiFunction("renderContact", { state, $, contactRequired, userCount: () => 1, working: () => false, document: { querySelector: () => tabs } })();
  assert.equal($("email-gate").hidden, false);
  assert.equal($("chat-view").hidden, true);
  assert.equal($("readme-view").hidden, true);
  assert.equal(tabs.hidden, true);
  assert.equal($("email-existing-note").hidden, false);
  assert.equal(state.conversation.messages, messages);
  const harness = dispatchHarness(state, () => { throw new Error("No conversation POST before email"); }, { contactRequired });
  await harness.dispatch("messages", "New answer");
  assert.equal(state.pending, undefined);
  state.conversation.setup.organizer_email = "researcher@example.test";
  assert.equal(contactRequired(), false);
});

test("Email save uses the private setup route, preserves a failed input, and opens the existing conversation", async () => {
  const { $ } = dom(); const messages = [{ role: "user", content: "My earlier answer" }];
  const state = { projectId: "p1", conversation: { messages, setup: { organizer_email: "" } } };
  const contactRequired = uiFunction("contactRequired", { state });
  $("organizer-email").value = " researcher@example.test "; $("organizer-email").reportValidity = () => true;
  const requests = []; let fail = true;
  const save = uiFunction("saveOrganizerEmail", { state, $, working: () => false, contactRequired, updateControls: noop, renderConversation: noop, refreshWorkflow: async () => {}, projectPath: () => "/api/projects/p1", base: () => "/conversation", api: async (path, options) => {
    requests.push({ path, method: options.method, body: JSON.parse(options.body) });
    if (fail) throw new Error("Email could not be saved");
    return { conversation: { messages, setup: { organizer_email: "researcher@example.test" } } };
  } });
  await save();
  assert.equal(state.contactError, "Email could not be saved"); assert.equal(state.contactBusy, false);
  assert.equal($("organizer-email").value, "researcher@example.test");
  fail = false; await save();
  assert.deepEqual(requests[1], { path: "/api/projects/p1/setup", method: "PATCH", body: { organizer_email: "researcher@example.test" } });
  assert.equal($("organizer-email").value, ""); assert.equal(state.conversation.messages, messages);
  assert.equal(contactRequired(), false);
});

test("The review hub hides earlier or dirty artifacts and retains truthful draft status", () => {
  const state = { conversation: { readme: "# Draft", setup: { organizer_email: "researcher@example.test" } }, workflow: { status: "draft", version: "v1", download_url: "/api/projects/p1/workflow/package", website_url: "/api/projects/p1/workflow/preview", submission_url: "/api/projects/p1/workflow/preview#submission" } };
  const window = { location: { origin: "http://localhost:8877" } };
  const links = uiFunction("reviewLinks", { state, projectPath: () => "/api/projects/p1", contactRequired: () => false, safeWebLink: uiFunction("safeWebLink", { window }) });
  assert.match(links().package, /\/workflow\/package$/); assert.match(links().submission, /#submission$/);
  state.workflow.status = "stale"; assert.deepEqual(links(), {});
  state.workflow.status = "draft"; state.dataDirty = true; assert.deepEqual(links(), {});
  state.dataDirty = false; state.workflow.website_url = "javascript:alert(1)"; assert.equal(links().website, null);
});

test("Request changes starts a revision only on explicit action and resumes an active review without a new POST", async () => {
  const { $ } = dom(); const state = { conversation: { readme: "# Draft", review: { mode: "interview", can_start: true } } };
  const posts = []; const views = [];
  const start = uiFunction("startRevision", { state, $, working: () => false, contactRequired: () => false, inRevision: uiFunction("inRevision", { state }), reviewAvailable: () => true, setView: (view) => views.push(view), dispatch: async (action) => posts.push(action) });
  assert.equal(posts.length, 0);
  await start(); assert.deepEqual(posts, ["revision"]);
  state.conversation.review = { mode: "revision", status: "clarifying" }; state.conversation.readme = null;
  await start(); assert.equal(posts.length, 1); assert.deepEqual(views, ["chat"]);
  state.conversation.review.status = "draft_ready"; await start(); assert.deepEqual(posts, ["revision", "revision"]);
});

test("Revision requests keep the same request ID after an uncertain response", async () => {
  const state = { projectId: "p1", busy: false, polling: false, pending: null, conversation: { readme: "# Draft", status: "idle", messages: [] } };
  const requests = []; let fail = true;
  const harness = dispatchHarness(state, async (path, options) => {
    if (!options) return state.conversation;
    requests.push({ path, body: JSON.parse(options.body) });
    if (fail) throw new Error("Connection interrupted");
    return { ...state.conversation, review: { mode: "revision", status: "awaiting_request", round: 1 } };
  });
  await harness.dispatch("revision"); assert.equal(state.pending.action, "revision");
  fail = false; await harness.dispatch("revision", undefined, state.pending);
  assert.equal(state.pending, null); assert.deepEqual(requests[1], requests[0]);
  assert.equal(state.conversation.review.round, 1);
});

test("Email and review controls remain separate from the scientific checklist", () => {
  const html = fs.readFileSync(path.join(__dirname, "..", "static", "chat.html"), "utf8");
  for (const id of ["organizer-email-form", "email-gate", "review-view", "review-website", "review-package", "review-submission", "start-revision", "revision-banner"]) assert.ok(html.includes(`id="${id}"`));
  assert.match(html, /type="email" autocomplete="email"/);
  assert.match(html, /Your earlier answers are saved/);
  assert.match(html, /Review does not publish/);
});

test("An active review stays accessible after its first correction clears the old README", () => {
  const { $ } = dom();
  const state = { conversation: { readme: null, review: { mode: "revision", status: "clarifying", can_start: false, round: 1 } } };
  const inRevision = uiFunction("inRevision", { state });
  const reviewAvailable = uiFunction("reviewAvailable", { state, inRevision });
  assert.equal(reviewAvailable(), true);
  uiFunction("renderReviewControls", { state, $, inRevision, reviewAvailable, contactRequired: () => false, working: () => false })();
  assert.equal($("start-revision").disabled, false);
  assert.equal($("start-revision").textContent, "Continue review →");
  assert.equal($("review-build").disabled, true);
});

test("A rebuilt review package asks for inspection instead of another rebuild", () => {
  const { $ } = dom();
  const state = { conversation: { review: { mode: "revision", status: "draft_ready", round: 1, changed_fields: [] } }, workflow: { status: "stale", version: "v1" } };
  const render = uiFunction("renderReview", { state, $, workflowPresentation: uiFunction("workflowPresentation"), reviewLinks: () => ["stale", "not_built"].includes(state.workflow.status) ? {} : { website: "/website", package: "/package", submission: "/submission" }, checklistItems: () => [], inRevision: () => true, renderReviewControls: noop });
  render(); assert.match($("review-feedback-detail").textContent, /Build the package again/);
  state.workflow = { status: "ready_for_review", version: "v2" }; render();
  assert.match($("review-feedback-detail").textContent, /updated package is ready to inspect/);
  assert.doesNotMatch($("review-feedback-detail").textContent, /Build the package again/);
  assert.match($("review-feedback-detail").textContent, /another round/);
  assert.equal($("review-version").textContent, "Version v2");
});


test("Readiness distinguishes working drafts from a complete definition and never blocks on an optional baseline", () => {
  const { $ } = dom();
  const state = { conversation: { readme: "# Working draft", readiness: { definition: "An agent can implement and interpret its score without inventing scientific assumptions.", ready: false, completed: 7, total: 9, blockers: [{ field: "data", requirement_id: "source" }], optional_baseline: { status: "missing" } } } };
  const render = uiFunction("renderReadiness", { state, $, coverageText });
  render();
  assert.equal($("readiness-status").textContent, "Required details open");
  assert.equal($("readiness-count").textContent, "7 of 9 required details recorded");
  assert.match($("draft-readiness-status").textContent, /Working draft.*required details remain open/);
  assert.match($("draft-readiness-detail").textContent, /does not mean the challenge is ready/);
  state.conversation.readiness = { ...state.conversation.readiness, ready: true, completed: 9, blockers: [] };
  render();
  assert.equal($("readiness-status").textContent, "Challenge defined");
  assert.match($("draft-readiness-detail").textContent, /Execution checks are separate/);
  assert.match($("draft-readiness-detail").textContent, /baseline is optional/);
});

test("Unknown required details remain incomplete and a declared inapplicable detail needs a reason", () => {
  const understanding = uiFunction("itemUnderstanding");
  const item = { id: "deployment", required: true, status: "answered", requirements: [
    { id: "setting", status: "recorded" }, { id: "latency", status: "deferred" },
    { id: "network", status: "not_applicable" }, { id: "hardware", status: "not_applicable", reason: "Prediction file; no submitted code runs" },
  ] };
  assert.deepEqual([understanding(item).completed, understanding(item).total, understanding(item).score], [2, 4, 50]);
  assert.equal(understanding({ id: "difficulty", requirements: [], status: "missing" }).required, false);
});

test("Checklist identifies Baseline as optional and exposes required counts to assistive technology", () => {
  const harness = checklistHarness({ checklist: [
    { id: "question", label: "Research question", required: true, requirements: [{ id: "target", status: "recorded" }, { id: "purpose", status: "missing" }] },
    { id: "difficulty", label: "Reference baseline", required: false, requirements: [{ id: "reference", status: "missing" }] },
  ] });
  harness.renderChecklist();
  assert.match(harness.$("interview-topics").children[0].attributes["aria-label"], /1 of 2 required details recorded/);
  assert.match(harness.$("interview-topics").children[2].attributes["aria-label"], /optional reference baseline/);
  harness.$("interview-topics").children[2].events.click();
  assert.match(harness.$("knowledge-update").textContent, /baseline is optional/);
});

test("Notes list missing compulsory requirements even when no answer has been recorded", () => {
  const harness = interviewHarness({ checklist: [
    { id: "data", label: "Data", required: true, value: "", status: "missing", requirements: [{ id: "source", label: "Dataset source link", status: "missing", reason: "A source is needed" }] },
    { id: "difficulty", label: "Reference baseline", required: false, value: "", status: "deferred", gap: "No functional reference is known" },
  ], readiness: { ready: false, completed: 0, total: 1, definition: "No invented scientific assumptions" } });
  const { $ } = dom();
  uiFunction("renderSummary", { ...harness, $, element: node })();
  const flatten = (entry) => [entry.textContent, ...entry.children.map(flatten)].join(" ");
  const text = flatten($("summary-content"));
  assert.match(text, /Dataset source link · Missing/);
  assert.match(text, /A source is needed/);
  assert.match(text, /Reference baseline · Optional/);
  assert.match(text, /No invented scientific assumptions/);
});


test("Continue interview is an explicit action and cannot start during organizer revision", async () => {
  const requests = [];
  const state = { projectId: "p1", pending: null, conversation: { status: "idle", interview: { can_continue: true }, messages: [{ role: "user", content: "Earlier facts" }] } };
  const harness = dispatchHarness(state, async (path, options) => { requests.push({ path, body: JSON.parse(options.body) }); return { ...state.conversation, interview: { can_continue: false }, current_question: { field: "data", text: "Please share the dataset link" } }; });
  assert.equal(requests.length, 0, "Rendering a working draft must not start another interview round");
  await harness.dispatch("continue");
  assert.deepEqual(requests, [{ path: "/conversation/continue", body: { request_id: "new-request-id" } }]);
  await harness.dispatch("continue"); assert.equal(requests.length, 1, "The active round cannot be restarted");
  state.conversation.interview.can_continue = true; state.conversation.review = { mode: "revision" };
  await harness.dispatch("continue"); assert.equal(requests.length, 1, "Revisions have their own bounded workflow");
});

test("Continue interview requests keep their request ID after an uncertain response", async () => {
  const pending = { project_id: "p1", action: "continue", request_id: "continue-request" };
  const state = { projectId: "p1", pending, conversation: { status: "idle", interview: { can_continue: false }, messages: [] } };
  const requests = [];
  const harness = dispatchHarness(state, async (path, options) => { requests.push({ path, body: JSON.parse(options.body) }); return state.conversation; });
  await harness.dispatch("continue", undefined, pending);
  assert.deepEqual(requests, [{ path: "/conversation/continue", body: { request_id: "continue-request" } }]);
  assert.equal(state.pending, null);
  const load = uiFunction("loadPending", { readStorage: () => JSON.stringify(pending), pendingKey: (id) => id });
  assert.deepEqual(load("p1"), pending, "The request must survive a reload");
});


test("Selected requirement notes show each source fact once when values and evidence repeat", () => {
  const fact = "Predict stability for five billion years.";
  const second = "Use collision and ejection as outcomes.";
  const harness = interviewHarness({ checklist: [{ id: "data", label: "Data", required: true, status: "answered", value: `${fact}\n${second}`, requirements: [
    { id: "source", label: "Source", status: "recorded", value: fact, evidence: ["  Predict   stability for five billion years.  ", fact] },
    { id: "outcomes", label: "Outcomes", status: "recorded", value: second, evidence: [{ quotes: [second] }] },
  ] }] });
  harness.state.selectedTopic = "problem"; harness.state.selectedItem = "data";
  const { $ } = dom();
  uiFunction("renderSummary", { ...harness, $, element: node })();
  const all = (entry) => [entry, ...entry.children.flatMap(all)];
  const nodes = all($("summary-content"));
  assert.equal(nodes.filter((entry) => entry.textContent === fact).length, 1);
  assert.equal(nodes.filter((entry) => entry.textContent === second).length, 1);
  assert.equal(nodes.filter((entry) => entry.tag === "blockquote").length, 0);
  assert.equal(nodes.filter((entry) => entry.tag === "details").length, 0, "The complete answer is already represented by the individual requirements");
});

test("Distinct source evidence remains visible and uncovered answer context is available on demand", () => {
  const harness = interviewHarness({ checklist: [{ id: "data", label: "Data", required: true, status: "partial", value: "A source is available. Additional context still needs assessment.", requirements: [
    { id: "source", label: "Source", status: "recorded", value: "A source is available.", evidence: ["The source covers rocky planets.", "The source covers rocky planets."] },
  ] }] });
  harness.state.selectedTopic = "problem"; harness.state.selectedItem = "data";
  const { $ } = dom();
  uiFunction("renderSummary", { ...harness, $, element: node })();
  const all = (entry) => [entry, ...entry.children.flatMap(all)];
  const nodes = all($("summary-content"));
  assert.equal(nodes.filter((entry) => entry.tag === "blockquote").length, 1);
  assert.equal(nodes.find((entry) => entry.tag === "blockquote").textContent, "The source covers rocky planets.");
  const details = nodes.find((entry) => entry.tag === "details");
  assert.ok(details); assert.notEqual(details.open, true);
  assert.equal(details.children[0].textContent, "Recorded answer");
  assert.match(details.children[1].textContent, /Additional context still needs assessment/);
});

function bypassHarness(api = async () => ({ status: "idle", messages: [] })) {
  const { $ } = dom();
  const state = { projectId: "p1", conversation: { status: "idle", messages: [] }, pending: null, bypassDrafts: {}, busy: false };
  const requests = []; let renders = 0;
  const bypassDraft = uiFunction("bypassDraft", { state });
  const dependencies = { state, $, bypassDraft, working: () => state.busy, contactRequired: () => false, renderSummary: () => { renders += 1; },
    rememberPending: (value) => { state.pending = value; }, setBusy: (value) => { state.busy = value; }, renderConversation: noop,
    refreshWorkflow: async () => {}, base: () => "/api/projects/p1/conversation", crypto: { randomUUID: () => "bypass-request-1" },
    api: async (path, options) => { requests.push({ path, options }); return api(path, options); },
  };
  const saveBypass = uiFunction("saveBypass", dependencies);
  const control = uiFunction("bypassControl", { ...dependencies, element: node, saveBypass });
  return { state, $, bypassDraft, saveBypass, control, requests, get renders() { return renders; } };
}
const descendants = (entry) => [entry, ...entry.children.flatMap(descendants)];

test("Manual bypass controls require a reason and preserve text and errors across renders", () => {
  const harness = bypassHarness(); const item = { id: "data" }; const criterion = { id: "permission", status: "missing" };
  let control = harness.control(item, criterion);
  assert.equal(control.children[0].textContent, "Bypass requirement");
  control.children[0].events.click();
  control = harness.control(item, criterion);
  let nodes = descendants(control); let input = nodes.find((entry) => entry.tag === "textarea");
  assert.equal(input.required, true); assert.equal(input.maxLength, 2000);
  assert.equal(nodes.find((entry) => entry.tag === "label").attributes.for, input.id);
  assert.match(nodes.find((entry) => entry.className === "bypass-hint").textContent, /does not add scientific evidence/);
  input.value = "<script> text stays private to this decision"; input.events.input();
  harness.bypassDraft("data", "permission").error = "Try again";
  control = harness.control(item, criterion); nodes = descendants(control);
  assert.equal(nodes.find((entry) => entry.tag === "textarea").value, input.value);
  assert.equal(nodes.find((entry) => entry.attributes.role === "alert").textContent, "Try again");
  nodes.find((entry) => entry.textContent === "Cancel").events.click();
  assert.equal(harness.bypassDraft("data", "permission").open, false);
  assert.equal(harness.bypassDraft("data", "permission").reason, input.value);
});

test("Blank and oversized bypass reasons never reach the server", async () => {
  const harness = bypassHarness(); const draft = harness.bypassDraft("data", "source");
  draft.reason = "   "; await harness.saveBypass("data", "source");
  assert.equal(harness.requests.length, 0); assert.equal(draft.error, "Enter a reason for this bypass.");
  draft.reason = "a".repeat(2001); await harness.saveBypass("data", "source");
  assert.equal(harness.requests.length, 0); assert.equal(draft.error, "Use no more than 2,000 characters.");
});

test("A bypass POST includes the exact requirement, reason and retry ID and prevents repeated clicks", async () => {
  let resolve; const server = new Promise((done) => { resolve = done; });
  const harness = bypassHarness(async () => server);
  harness.bypassDraft("question", "value").reason = " Our pilot accepts this unresolved detail. ";
  const saving = harness.saveBypass("question", "value");
  await harness.saveBypass("question", "value");
  assert.equal(harness.requests.length, 1); assert.equal(harness.state.busy, true);
  assert.deepEqual(JSON.parse(harness.requests[0].options.body), { field: "question", requirement_id: "value", request_id: "bypass-request-1", remove: false, reason: "Our pilot accepts this unresolved detail." });
  assert.equal(harness.requests[0].path, "/api/projects/p1/conversation/requirements/bypass");
  resolve({ status: "idle", readiness: { bypassed: 1 }, messages: [] }); await saving;
  assert.equal(harness.state.pending, null); assert.equal(harness.state.busy, false);
  assert.equal(harness.state.bypassDrafts["question:value"], undefined);
  assert.equal(harness.state.conversation.readiness.bypassed, 1);
});

test("An uncertain bypass keeps its reason and request ID until its own retry succeeds", async () => {
  let fail = true;
  const harness = bypassHarness(async (_path, options) => {
    if (options && fail) throw new Error("Connection interrupted");
    return { status: "idle", messages: [], readiness: { bypassed: 1 } };
  });
  harness.bypassDraft("data", "source").reason = "The archive will be linked after organizer review.";
  await harness.saveBypass("data", "source");
  const pending = harness.state.pending; assert.equal(pending.request_id, "bypass-request-1");
  assert.equal(harness.bypassDraft("data", "source").error, "Connection interrupted");
  const control = harness.control({ id: "data" }, { id: "source", status: "bypassed" });
  assert.ok(descendants(control).some((entry) => entry.textContent === "Retry bypass"));
  assert.ok(descendants(control).some((entry) => entry.textContent === pending.reason));
  const load = uiFunction("loadPending", { readStorage: () => JSON.stringify(pending), pendingKey: (id) => id });
  assert.deepEqual(load("p1"), pending);
  fail = false; await harness.saveBypass("data", "source", false, pending);
  const posts = harness.requests.filter((entry) => entry.options);
  assert.equal(posts.length, 2); assert.equal(posts[0].options.body, posts[1].options.body);
  assert.equal(harness.state.pending, null);
});

test("A rejected bypass keeps the editable reason and inline error", async () => {
  const harness = bypassHarness(async (_path, options) => {
    if (options) { const error = new Error("This requirement cannot be bypassed"); error.status = 422; throw error; }
    return { status: "idle", messages: [] };
  });
  harness.bypassDraft("data", "source").reason = "A reason";
  await harness.saveBypass("data", "source");
  assert.equal(harness.state.pending, null);
  const draft = harness.bypassDraft("data", "source");
  assert.equal(draft.open, true); assert.equal(draft.reason, "A reason"); assert.match(draft.error, /cannot be bypassed/);
});

test("Removal is explicit and does not require another reason", async () => {
  const harness = bypassHarness();
  const control = harness.control({ id: "data" }, { id: "source", status: "bypassed", bypass: { reason: "Existing decision" } });
  assert.deepEqual(control.children.map((entry) => entry.textContent), ["Edit bypass reason", "Remove bypass"]);
  await harness.saveBypass("data", "source", true);
  assert.deepEqual(JSON.parse(harness.requests[0].options.body), { field: "data", requirement_id: "source", request_id: "bypass-request-1", remove: true });
});

test("Only permitted missing criteria expose bypass controls in item details", () => {
  const harness = interviewHarness({ checklist: [{ id: "data", label: "Data", required: true, requirements: [
    { id: "source", label: "Source", status: "missing", can_bypass: true },
    { id: "outcomes", label: "Outcomes", status: "recorded", can_bypass: true },
    { id: "permission", label: "Permission", status: "missing", can_bypass: false },
  ] }] });
  const { $ } = dom(); const called = [];
  const render = uiFunction("renderSummary", { ...harness, $, element: node, bypassControl: (_item, criterion) => { called.push(criterion.id); return node(); } });
  render(); assert.deepEqual(called, []);
  harness.state.selectedTopic = "problem"; harness.state.selectedItem = "data"; render();
  assert.deepEqual(called, ["source"]);
});

test("Bypasses resolve bars while remaining distinct from recorded evidence", () => {
  const harness = checklistHarness({ readiness: { ready: true, completed: 3, total: 3, bypassed: 1 }, checklist: [{ id: "data", label: "Dataset", required: true, requirements: [
    { id: "source", label: "Source", status: "recorded" },
    { id: "outcomes", label: "Outcomes", status: "recorded" },
    { id: "permission", label: "Permission", status: "bypassed", bypass: { reason: "Organizer accepts the unresolved detail." } },
  ] }] });
  harness.renderChecklist();
  assert.equal(harness.itemUnderstanding(harness.checklistItems()[0]).score, 100);
  assert.equal(harness.interviewTopics()[0].understanding.bypassed, 1);
  assert.equal(harness.$("readiness-status").textContent, "Ready with bypasses");
  assert.equal(harness.$("readiness-count").textContent, "3 of 3 required details resolved (2 recorded · 1 bypassed)");
  assert.match(harness.$("knowledge-items").children[0].attributes["aria-label"], /2 recorded · 1 bypassed/);
  harness.state.selectedTopic = "problem"; harness.state.selectedItem = "data";
  uiFunction("renderSummary", { ...harness, element: node })();
  const text = descendants(harness.$("summary-content")).map((entry) => entry.textContent).join(" ");
  assert.match(text, /Permission · Manually bypassed/); assert.match(text, /Organizer accepts the unresolved detail/);
});

test("All bypass edits are disabled while another operation runs", () => {
  const harness = bypassHarness(); harness.state.busy = true;
  let control = harness.control({ id: "data" }, { id: "source", status: "missing" });
  assert.equal(control.children[0].disabled, true);
  control.children[0].events.click(); assert.equal(harness.bypassDraft("data", "source").open, false);
  harness.bypassDraft("data", "source").open = true;
  control = harness.control({ id: "data" }, { id: "source", status: "missing" });
  assert.ok(descendants(control).filter((entry) => entry.attributes["data-bypass-control"]).every((entry) => entry.disabled));
});

test("The global retry control routes bypass recovery through its original payload", async () => {
  const pending = { action: "bypass", field: "data", requirement_id: "source", reason: "Saved reason", remove: false, request_id: "original-id" };
  const calls = [];
  const retry = uiFunction("retry", { state: { conversation: {}, pending }, working: () => false, saveBypass: async (...args) => calls.push(args), dispatch: () => { throw new Error("A bypass must use its own endpoint"); } });
  await retry(); assert.deepEqual(calls, [["data", "source", false, pending]]);
});

test("Sign-out uses fresh CSRF, clears private browser data, and returns to sign-in", async () => {
  const state = { config: { private_mode: true }, signingOut: false }; const calls = []; let cleared = 0; let updateCount = 0;
  const signOut = uiFunction("signOut", { state, updateControls: () => { updateCount += 1; },
    api: async (url, options) => { calls.push({ url, options }); return options ? { redirect: "/login" } : { csrf_token: "fresh" }; },
    clearPrivateBrowserState: () => { cleared += 1; }, writeStorage: (...args) => calls.push({ storage: args }), SESSION_ENDED: "session-ended",
    window: { location: { replace: (url) => calls.push({ redirect: url }) } }, showError: () => { throw new Error("Unexpected sign-out error"); } });
  await signOut(); assert.equal(cleared, 1); assert.equal(updateCount, 1);
  assert.equal(calls[0].url, "/api/access"); assert.equal(calls[1].url, "/api/access/logout");
  assert.equal(calls[1].options.headers["X-CSRF-Token"], "fresh"); assert.equal(calls[1].options.body, "{}");
  assert.equal(calls[2].storage[0], "session-ended"); assert.deepEqual(calls[3], { redirect: "/login" });
});

test("Failed or malformed sign-out preserves current work and permits a retry", async () => {
  for (const result of [null, {}]) {
    const state = { config: { private_mode: true }, signingOut: false }; const errors = [];
    const signOut = uiFunction("signOut", { state, updateControls: noop,
      api: async (_url, options) => { if (!options) return { csrf_token: "fresh" }; if (result === null) throw new Error("Disconnected"); return result; },
      clearPrivateBrowserState: () => { throw new Error("Must preserve local work"); },
      showError: (...args) => errors.push(args) });
    await signOut(); assert.equal(state.signingOut, false); assert.equal(errors.length, 1);
    assert.equal(errors[0][1], "Sign-out was not confirmed");
  }
});

test("Sign-out is not duplicated or offered outside private mode", async () => {
  for (const state of [{ config: { private_mode: false } }, { config: { private_mode: true }, signingOut: true }]) {
    await uiFunction("signOut", { state, api: () => { throw new Error("Must not make a request"); } })();
  }
});

test("Account data is removed from storage and hidden before another sign-in", () => {
  const values = { "autokaggle-chat-last-project": "p1", "autokaggle-chat-compose:p1": "private draft", "autokaggle-chat-pending:p1": "private request", "autokaggle-chat-pending:p1:scope-drafts": "private scope", unrelated: "keep" };
  Object.defineProperty(values, "removeItem", { value: (key) => { delete values[key]; }, enumerable: false });
  const state = { projectId: "p1", conversation: { private: true }, projects: [1], pending: {}, workflow: {}, dataProject: {}, bypassDrafts: { reason: "private" } };
  const { $ } = dom(); $("message-input").value = "draft"; $("organizer-email").value = "researcher@example.org";
  const shell = { hidden: false };
  const clear = uiFunction("clearPrivateBrowserState", { state, $, LAST_PROJECT: "autokaggle-chat-last-project", window: { localStorage: values }, document: { querySelector: () => shell } });
  clear(); assert.deepEqual(values, { unrelated: "keep" }); assert.equal(shell.hidden, true);
  assert.equal(state.conversation, null); assert.equal(state.projectId, null); assert.equal(state.pending, null);
  assert.deepEqual(state.projects, []); assert.deepEqual(state.bypassDrafts, {}); assert.equal($("message-input").value, "");
  assert.equal($("organizer-email").value, "");
});

test("An unauthorized project URL cannot reveal its cached draft or pending text", async () => {
  const { $ } = dom(); $("message-input").value = "previous visible text";
  const state = { bypassDrafts: {}, pending: { message: "private" } };
  const open = uiFunction("openProject", { state, $, window: { location: { search: "" } }, URLSearchParams,
    rememberCompose: noop, setView: noop,
    api: async () => { throw new Error("Challenge not found"); }, base: () => "/conversation",
    loadPending: () => { throw new Error("Must not read pending text before authorization"); },
    readStorage: () => { throw new Error("Must not read drafts before authorization"); },
  });
  await assert.rejects(open("not-owned"), /Challenge not found/);
  assert.equal($("message-input").value, ""); assert.equal(state.pending, null); assert.equal(state.conversation, null);
});

test("A missing or unauthorized challenge gives account guidance instead of a connection error", () => {
  for (const status of [401, 403, 404]) {
    const { $ } = dom(); const errors = [];
    const state = { conversation: null, config: { private_mode: true, can_create_projects: true } };
    const show = uiFunction("showProjectError", { state, $, showError: (...args) => errors.push(args) });
    show({ status, message: "Challenge not found in this organizer session" }, "Could not connect");
    assert.equal(state.projectUnavailable, true); assert.equal($("project-title").textContent, "Challenge unavailable");
    assert.equal(errors[0][1], "Challenge unavailable"); assert.match(errors[0][0], /another account/);
    assert.match(errors[0][0], /Sign out/); assert.match(errors[0][0], /New challenge/);
  }
});

test("Unavailable challenges hide the checklist and Reconnect action without blocking New challenge", () => {
  const { $ } = dom(); const tabs = { hidden: false };
  const state = { projectUnavailable: true, conversation: null, config: { private_mode: true, can_create_projects: true }, view: "chat", localError: { heading: "Challenge unavailable", text: "Use another account" } };
  uiFunction("renderContact", { state, $, contactRequired: () => false, working: () => false, userCount: () => 0, document: { querySelector: () => tabs } })();
  uiFunction("renderError", { state, $, working: () => false })();
  for (const id of ["chat-view", "readme-view", "review-view", "interview-topics", "checklist-toggle", "retry-action"]) assert.equal($(id).hidden, true, id);
  assert.equal(tabs.hidden, true); assert.equal($("error-banner").hidden, false);
});

test("Connection failures still offer recovery and review-only sessions receive no creation suggestion", () => {
  const { $ } = dom(); const errors = [];
  const state = { conversation: null, config: { private_mode: true, can_create_projects: false } };
  const show = uiFunction("showProjectError", { state, $, showError: (...args) => errors.push(args) });
  show({ message: "Network interrupted" }, "Could not connect");
  assert.equal(state.projectUnavailable, undefined); assert.deepEqual(errors.pop(), ["Network interrupted", "Could not connect"]);
  show({ status: 404 }, "Could not connect"); assert.doesNotMatch(errors[0][0], /New challenge/);
});

function scopeHarness(api = async () => ({ status: "idle", messages: [], checklist: [] }), itemExtra = {}) {
  const { $ } = dom(); const cache = new Map(); const requests = [];
  const item = { id: "task", label: "Task", can_accept_scope: true, value: "Predict stability over one million orbits.", requirements: [
    { id: "outcome", label: "Outcome", status: "missing", can_delegate: false },
    { id: "format", label: "Output format", status: "missing", can_delegate: true, delegation_policy: "Choose a supported format and record its schema." },
  ], ...itemExtra };
  const state = { projectId: "p1", conversation: { status: "idle", checklist: [item] }, pending: null, scopeDrafts: {}, busy: false };
  const shared = { state, $, working: () => state.busy, contactRequired: () => false, checklistItems: () => state.conversation.checklist || [],
    pendingKey: (id) => `autokaggle-chat-pending:${id}`, readStorage: (key) => cache.get(key) || null, writeStorage: (key, value) => cache.set(key, value),
    element: node, renderSummary: noop, renderConversation: noop, refreshWorkflow: async () => {},
    rememberPending: (value) => { state.pending = value; }, setBusy: (value) => { state.busy = value; }, base: () => "/api/projects/p1/conversation",
    crypto: { randomUUID: () => "scope-request-1" }, api: async (path, options) => { requests.push({ path, options }); return api(path, options); },
    knowledgeGroups: () => [{ id: "problem", fields: ["task"] }], showSummary: noop,
  };
  shared.scopeCriteria = uiFunction("scopeCriteria"); shared.scopeDraft = uiFunction("scopeDraft", shared);
  shared.rememberScopeDrafts = uiFunction("rememberScopeDrafts", shared); shared.saveScope = uiFunction("saveScope", shared);
  shared.openScope = uiFunction("openScope", shared);
  return { ...shared, item, cache, requests, control: uiFunction("scopeControl", shared), checkpoint: uiFunction("renderScopeCheckpoint", shared) };
}

test("A normal scope acceptance uses one summary for all listed unresolved decisions", async () => {
  const h = scopeHarness(); const draft = h.scopeDraft(h.item); draft.open = true;
  const control = h.control(h.item); const nodes = descendants(control);
  assert.equal(nodes.filter((entry) => entry.tag === "textarea" && entry.className === "scope-summary").length, 1);
  assert.ok(nodes.filter((entry) => entry.className === "scope-decision-detail").every((entry) => entry.hidden));
  await h.saveScope("task"); const payload = JSON.parse(h.requests[0].options.body);
  assert.equal(h.requests[0].path, "/api/projects/p1/conversation/scope");
  assert.equal(payload.summary, "Predict stability over one million orbits.");
  assert.deepEqual(payload.resolutions, [
    { requirement_id: "outcome", mode: "confirmed", detail: payload.summary },
    { requirement_id: "format", mode: "confirmed", detail: payload.summary },
  ]); assert.equal(payload.request_id, "scope-request-1"); assert.equal(h.state.pending, null);
});

test("Scope controls expose delegation only where permitted and require explicit bounds", async () => {
  const h = scopeHarness(); const draft = h.scopeDraft(h.item); draft.open = true;
  const nodes = descendants(h.control(h.item)); const selects = nodes.filter((entry) => entry.tag === "select");
  assert.deepEqual(selects[0].children.map((entry) => entry.value), ["confirmed", "exception", "unresolved"]);
  assert.deepEqual(selects[1].children.map((entry) => entry.value), ["confirmed", "delegated", "exception", "unresolved"]);
  selects[1].value = "delegated"; selects[1].events.change(); await h.saveScope("task");
  assert.equal(h.requests.length, 0); assert.match(draft.error, /specific limit/);
  draft.resolutions.format.detail = "Use CSV with ID and stable_probability columns."; await h.saveScope("task");
  assert.deepEqual(JSON.parse(h.requests[0].options.body).resolutions[1], { requirement_id: "format", mode: "delegated", detail: "Use CSV with ID and stable_probability columns." });
});

test("A forged client delegation cannot be sent for a source decision", async () => {
  const h = scopeHarness(); h.scopeDraft(h.item).resolutions.outcome = { mode: "delegated", detail: "Guess the label." };
  await h.saveScope("task"); assert.equal(h.requests.length, 0); assert.match(h.scopeDraft(h.item).error, /permitted resolution/);
});

test("Exceptions need a reason and Leave unresolved omits that criterion", async () => {
  const h = scopeHarness(); const draft = h.scopeDraft(h.item);
  draft.resolutions = { outcome: { mode: "exception", detail: "" }, format: { mode: "unresolved" } };
  await h.saveScope("task"); assert.equal(h.requests.length, 0); assert.match(draft.error, /specific reason/);
  draft.resolutions.outcome.detail = "This pilot uses the operational definition supplied in the paper.";
  await h.saveScope("task"); assert.equal(JSON.parse(h.requests[0].options.body).resolutions.length, 1);
  assert.equal(JSON.parse(h.requests[0].options.body).resolutions[0].mode, "exception");
});

test("Empty or oversized scope summaries cannot complete a card", async () => {
  const h = scopeHarness(); const draft = h.scopeDraft(h.item);
  for (const value of ["  ", "x".repeat(2001)]) { draft.summary = value; await h.saveScope("task"); }
  assert.equal(h.requests.length, 0); assert.match(draft.error, /1 to 2,000/);
});

test("Already recorded cards accept a summary without artificial unresolved decisions", async () => {
  const h = scopeHarness(undefined, { requirements: [{ id: "outcome", label: "Outcome", status: "recorded" }] });
  await h.saveScope("task"); assert.deepEqual(JSON.parse(h.requests[0].options.body).resolutions, []);
});

test("An uncertain scope save retries the identical payload after a later edit", async () => {
  let fail = true; const h = scopeHarness(async (_path, options) => { if (fail && options) throw new Error("Interrupted"); return h.state.conversation; });
  await h.saveScope("task"); const original = h.state.pending; assert.equal(original.action, "scope");
  h.scopeDraft(h.item).summary = "A later edit must not change this retry."; fail = false;
  await h.saveScope("task", false, original);
  assert.equal(h.requests[0].options.body, h.requests[2].options.body); assert.equal(h.state.pending, null);
});

test("A rejected scope request preserves its editable draft but clears retry identity", async () => {
  const h = scopeHarness(async (_path, options) => { if (options) { const error = new Error("The decision is incomplete."); error.status = 422; throw error; } return h.state.conversation; });
  await h.saveScope("task"); assert.equal(h.state.pending, null);
  assert.equal(h.scopeDraft(h.item).summary, h.item.value); assert.equal(h.scopeDraft(h.item).open, true);
  assert.match(h.scopeDraft(h.item).error, /incomplete/);
});

test("Scope drafts survive reloading and editing another card", () => {
  const h = scopeHarness(); h.cache.set("autokaggle-chat-pending:p1:scope-drafts", JSON.stringify({ question: { summary: "Keep this draft", resolutions: {}, open: true }, task: { summary: "Retained scope", resolutions: {}, open: true } }));
  assert.equal(h.scopeDraft(h.item).summary, "Retained scope"); h.scopeDraft(h.item).summary = "Edited scope"; h.rememberScopeDrafts();
  const stored = JSON.parse(h.cache.get("autokaggle-chat-pending:p1:scope-drafts")); assert.equal(stored.question.summary, "Keep this draft"); assert.equal(stored.task.summary, "Edited scope");
});

test("Removal sends only the field, removal flag, and request identity", async () => {
  const h = scopeHarness(); await h.saveScope("task", true);
  assert.deepEqual(JSON.parse(h.requests[0].options.body), { field: "task", request_id: "scope-request-1", remove: true });
});

test("Checkpoint actions show unaccepted proposals and permitted delegation without sending a request", () => {
  const h = scopeHarness(); h.state.conversation.scope_checkpoint = { field: "task", requirement_id: "format", reason: "This format decision is still open.", proposed_answer: "Use an ID and probability CSV.", can_delegate: true };
  h.checkpoint(); const nodes = descendants(h.$("scope-checkpoint"));
  assert.equal(h.$("scope-checkpoint").hidden, false); assert.ok(nodes.some((entry) => entry.textContent.includes("not yet accepted")));
  assert.deepEqual(nodes.filter((entry) => entry.tag === "button").map((entry) => entry.textContent), ["Review proposal", "Let the agent choose", "Record an exception"]);
  assert.equal(h.requests.length, 0); nodes.find((entry) => entry.textContent === "Review proposal").events.click();
  assert.match(h.scopeDraft(h.item).summary, /Use an ID and probability CSV/); assert.equal(h.requests.length, 0);
});

test("The checkpoint form can target an exception and cannot open protected setup cards", () => {
  const h = scopeHarness(); h.openScope("task", "outcome", "exception");
  assert.equal(h.scopeDraft(h.item).resolutions.outcome.mode, "exception");
  h.item.can_accept_scope = false; h.scopeDraft(h.item).open = false; h.openScope("task"); assert.equal(h.scopeDraft(h.item).open, false);
});

test("Scope provenance stays distinct in checklist coverage", () => {
  const understand = uiFunction("itemUnderstanding"); const result = understand({ id: "task", requirements: [
    { status: "recorded" }, { status: "confirmed" }, { status: "delegated" }, { status: "exception" }, { status: "bypassed" },
  ] });
  assert.equal(result.completed, 5); assert.equal(result.score, 100);
  assert.equal(coverageText(result), "5 of 5 details resolved (1 recorded · 1 confirmed · 1 delegated · 1 exception · 1 bypassed)");
});

test("Global retry routes a pending scope mutation through its exact original request", async () => {
  const pending = { action: "scope", field: "task", remove: false, request_id: "same" }; const calls = [];
  await uiFunction("retry", { state: { conversation: {}, pending }, working: () => false, saveScope: async (...args) => calls.push(args) })();
  assert.deepEqual(calls, [["task", false, pending]]);
});

test("The question rationale is brief, visible in chat, and not repeated when already asked", () => {
  const { $ } = dom(); const state = { view: "chat", conversation: { current_question: { text: "Which target should we predict?", why: "The evaluator needs one target." } } };
  const render = uiFunction("renderQuestionWhy", { state, $ }); render();
  assert.equal($("question-hint").hidden, false); assert.equal($("question-text").textContent, "Why this matters: The evaluator needs one target.");
  state.conversation.current_question.text += " The evaluator needs one target."; render(); assert.equal($("question-hint").hidden, true);
  state.conversation.current_question.text = "Target?"; state.view = "review"; render(); assert.equal($("question-hint").hidden, true);
});

test("Accepted scope text appears once while distinct source facts stay labeled", () => {
  const summary = "Predict stable or unstable over one million orbits.";
  const original = "The initial brief described a long-term stability test.";
  const h = interviewHarness({ checklist: [{ id: "task", label: "Task", required: true, status: "answered", value: original, scope: { summary }, requirements: [
    { id: "first", label: "Outcome", status: "confirmed", value: summary, reason: summary, resolution: { detail: summary }, evidence: [summary, original] },
    { id: "second", label: "Horizon", status: "confirmed", value: summary, resolution: { detail: summary }, evidence: [original] },
  ] }] });
  h.state.selectedTopic = "problem"; h.state.selectedItem = "task"; const { $ } = dom();
  uiFunction("renderSummary", { ...h, $, element: node, scopeControl: (item) => node("p", "scope-saved-summary", item.scope.summary) })();
  const nodes = descendants($("summary-content"));
  assert.equal(nodes.filter((entry) => entry.textContent === summary).length, 1);
  assert.equal(nodes.filter((entry) => entry.textContent === original).length, 1);
  assert.equal(nodes.filter((entry) => entry.textContent === "Underlying source").length, 1);
  assert.equal(nodes.filter((entry) => entry.textContent === "Covered by the accepted summary above.").length, 2);
});

test("A distinct delegated decision is not repeated as value, reason, and evidence", () => {
  const decision = "Use CSV with an ID and probability column.";
  const h = interviewHarness({ checklist: [{ id: "task", label: "Task", required: true, status: "answered", value: decision, requirements: [
    { id: "format", label: "Format", status: "delegated", value: decision, reason: decision, resolution: { detail: decision }, evidence: [decision] },
  ] }] });
  h.state.selectedTopic = "problem"; h.state.selectedItem = "task"; const { $ } = dom();
  uiFunction("renderSummary", { ...h, $, element: node })();
  assert.equal(descendants($("summary-content")).filter((entry) => entry.textContent === decision).length, 1);
});

test("Coverage honors server scope counts and describes accepted details as resolved", () => {
  const understand = uiFunction("itemUnderstanding");
  const count = understand({ id: "task", understanding: { score: 100, completed: 5, total: 5, confirmed: 2, delegated: 1, exception: 1, bypassed: 0 } });
  assert.equal(coverageText(count), "5 of 5 details resolved (1 recorded · 2 confirmed · 1 delegated · 1 exception)");
  assert.equal(coverageText({ completed: 5, total: 9, scope_resolved: 2 }), "5 of 9 details resolved (3 recorded · 2 scope accepted)");
  assert.equal(coverageText({ completed: 2, total: 3, exceptions: 1 }), "2 of 3 details resolved (1 recorded · 1 exception)");
});

test("The visible checklist progress includes organizer decisions in its resolved count", () => {
  const h = checklistHarness({ checklist: [{ id: "question", label: "Question", required: true, active: true, status: "answered", requirements: [
    { id: "a", status: "recorded" }, { id: "b", status: "recorded" }, { id: "c", status: "recorded" },
    { id: "d", status: "confirmed" }, { id: "e", status: "confirmed" },
  ] }] });
  h.renderChecklist(); assert.match(h.$("knowledge-update").textContent, /5 of 5 details resolved \(3 recorded · 2 confirmed\)/);
});
