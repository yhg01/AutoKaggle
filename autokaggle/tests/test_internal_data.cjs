"use strict";
const {test} = require("node:test");
const assert = require("node:assert/strict");
const D = require("../static/internal-data.js");
const fixture = () => ({project: {id: "project", setup: {daily_submission_limit: 5, submissions_confirmed: false},
  conversation: {messages: [{id: "m1", role: "user", content: "每天10次"}, {id: "m2", role: "assistant", content: "Saved text"}],
    items: {submissions: {status: "missing", value: "5", evidence: [{message_id: "m1", quotes: ["每天10次"]}]}},
    _history: [{field: "submissions", before: {value: "old"}, message_id: "m1", operation: "append"}]},
  _model_traces: [{id: "c1", kind: "scope", trigger: {message_id: "m1"}, output: '{"updates":[]}', usage: {input_tokens: 10, output_tokens: 6, reasoning_tokens: 4}}, {id: "legacy", kind: "scope", started_at: "2026-10-31"}]}, review: {field_definitions: [{id: "submissions", label: "Daily submissions", group: "Setup"}]}});

test("exact message IDs connect messages, calls, field evidence and changes", () => {
  const data = fixture(), links = D.related(data, D.rows(data, "messages")[0]);
  assert.deepEqual(links.calls.map(r => r.id), ["c1"]);
  assert.deepEqual(links.fields.map(r => r.id), ["submissions"]);
  assert.equal(links.changes.length, 1);
  assert.equal(D.related(data, D.rows(data, "calls")[1]).messageId, null);
  assert.equal(D.related(data, D.rows(data, "messages")[1]).calls.length, 0);
});
test("truncated captures are not parsed as complete JSON", () => {
  const truncated = D.captured({input: '{"updates":[]\n[truncated]'}, "input");
  assert.equal(truncated.truncated, true); assert.equal(truncated.parsed, undefined);
  assert.deepEqual(D.captured({output: '{"updates":[]}'}, "output").parsed, {updates: []});
  assert.equal(D.captured({input: "text", capture: {input: {original_chars: 50000, truncated: true}}}, "input").originalChars, 50000);
});
test("saved settings, missing values and historical records are not rewritten", () => {
  const data = fixture(), original = structuredClone(data);
  const rows = D.rows(data, "fields");
  assert.equal(rows.find(r => r.id === "submissions").status, "missing");
  assert.equal(rows.find(r => r.id === "setup").value.daily_submission_limit, 5);
  assert.ok(rows.every(r => Number.isInteger(r.index) && r.index > 0));
  assert.equal(D.rows(data, "changes")[0].value.after, undefined);
  assert.equal(D.rows(data, "messages")[0].at, undefined);
  assert.deepEqual(data, original);
});
test("search includes full content and filtering preserves recorded order", () => {
  const rows = D.rows(fixture(), "messages");
  assert.equal(D.select(rows, "每天10次", "user", false)[0].id, "m1");
  assert.deepEqual(D.select(rows, "", "", true).map(r => r.id), ["m2", "m1"]);
  assert.equal(D.select(rows, "missing string", "", false).length, 0);
});
test("usage totals cover only measured retained calls and keep reasoning inside output", () => {
  const total = D.totals(fixture().project._model_traces);
  assert.deepEqual(total, {input: 10, output: 6, reasoning: 4, duration: 0, measured: 1});
});
test("execution and artifact records expose saved absence without fabricating a run", () => {
  const data = fixture();
  const execution = D.rows(data, "execution");
  assert.equal(execution.find(r => r.id === "dataset").value, null);
  assert.equal(execution.find(r => r.id === "analysis").value, null);
  assert.equal(D.rows(data, "artifacts").find(r => r.id === "readme").value, null);
});

test("field relationship panels include each explicit source and never nearby messages", () => {
  const data = fixture();
  data.project.conversation.items.submissions.evidence.push({message_id: "m2", quotes: ["Saved text"]});
  const links = D.related(data, D.rows(data, "fields")[0]);
  assert.deepEqual(links.messageIds, ["m1", "m2"]);
  assert.deepEqual(links.messages.map(r => r.id), ["m1", "m2"]);
  assert.deepEqual(links.calls.map(r => r.id), ["c1"]);
  assert.equal(links.messageId, null);
});

test("requirement status tiles distinguish a saved missing assessment from an absent one", () => {
  const data = fixture();
  data.review.requirement_definitions = {submissions: [{id: "allowance", label: "Daily allowance"}, {id: "confirmation", label: "Confirmation"}]};
  data.project.conversation.items.submissions.requirements = {allowance: {status: "missing", value: "5"}};
  const before = structuredClone(data);
  const cells = D.requirementCells(data, D.rows(data, "fields")[0]);
  assert.equal(cells[0].status, "missing");
  assert.equal(cells[1].status, "not_recorded");
  assert.equal(cells[1].value, null);
  assert.deepEqual(data, before);
});
