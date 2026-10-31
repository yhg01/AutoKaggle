/* Saved-data adapters shared by the review UI and tests. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.InternalData = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  const array = value => Array.isArray(value) ? value : [];
  const object = value => value && typeof value === "object" && !Array.isArray(value) ? value : {};
  const pretty = value => typeof value === "string" ? value : JSON.stringify(value, null, 2);
  const short = value => String(pretty(value) ?? "Not recorded").replace(/\s+/g, " ").slice(0, 180);
  function captured(trace, key) {
    const text = trace[key], metadata = trace.capture?.[key];
    const truncated = metadata?.truncated === true || (typeof text === "string" && text.endsWith("\n[truncated]"));
    let parsed;
    if (typeof text === "string" && !truncated) { try { parsed = JSON.parse(text); } catch (_) { /* Keep plain text. */ } }
    return {text, parsed, truncated, originalChars: metadata?.original_chars ?? null, storedChars: typeof text === "string" ? text.length : null};
  }
  function rows(data, section) {
    const p = data.project || {}, c = p.conversation || {}, review = data.review || {};
    const definitions = Object.fromEntries(array(review.field_definitions).map(d => [d.id, d]));
    if (section === "messages") return array(c.messages).map((value, i) => ({id: value.id || `message-${i}`, label: value.role || "Message", subtitle: short(value.content ?? value.text), status: value.role, at: value.at || value.created_at, index: i + 1, value, path: `conversation.messages[${i}]`, type: "message"}));
    if (section === "calls") return array(p._model_traces).map((value, i) => ({id: value.id || `call-${i}`, label: value.kind || "Model call", subtitle: value.model || "Model not recorded", status: value.status, at: value.started_at, index: i + 1, value, path: `_model_traces[${i}]`, type: "call"}));
    if (section === "fields") {
      const fields = Object.entries(object(c.items)).map(([key, value], i) => ({id: key, label: definitions[key]?.label || key, subtitle: short(value.value), status: value.status, index: i + 1, value, path: `conversation.items.${key}`, group: definitions[key]?.group || "Recorded fields", type: "field"}));
      for (const key of ["setup", "design", "answers"]) if (p[key] !== undefined) fields.push({id: key, label: key === "setup" ? "Validated organizer settings" : key === "design" ? "Evaluator configuration" : "Legacy answers", subtitle: short(p[key]), value: p[key], path: key, group: "Application settings", type: "settings"});
      return fields.map((r, i) => ({...r, index: i + 1}));
    }
    if (section === "changes") {
      const changes = [];
      for (const key of ["_history", "_scope_audit", "_bypass_audit", "_response_diagnostics"]) array(c[key]).forEach((value, i) => changes.push({id: `${key}-${i}`, label: value.field ? `${definitions[value.field]?.label || value.field} · ${value.operation || value.action || "change"}` : value.code || "Validation record", subtitle: short(value.replacement_evidence || value.reason || value.code || value.after), status: value.operation || value.action || value.kind, at: value.at, index: changes.length + 1, value, path: `conversation.${key}[${i}]`, group: key, type: "change"}));
      return changes;
    }
    if (section === "execution") {
      const records = [];
      const controls = ["status", "phase", "followups", "current_question", "scope_checkpoint", "error", "can_retry", "_pending", "_inflight", "_unprocessed", "_last_response_failure", "_criterion_asks", "_interview_round", "_revision_rounds"];
      records.push({id: "interview-runtime", label: "Interview runtime", subtitle: `${c.status ?? "not recorded"} · ${c.phase ?? "phase not recorded"}`, status: c.status, value: Object.fromEntries(controls.filter(k => k in c).map(k => [k, c[k]])), path: "conversation (control fields)", type: "execution"});
      for (const key of ["harness", "dataset", "analysis", "workflow"]) records.push({id: key, label: {harness: "Harness state", dataset: "Dataset metadata", analysis: "Data analysis", workflow: "Workflow and checks"}[key], subtitle: short(p[key]), status: p[key]?.status, value: p[key] ?? null, path: key, type: "execution"});
      array(p.events).forEach((value, i) => records.push({id: `event-${i}`, label: value.stage || "Execution event", subtitle: value.detail, status: value.status, at: value.at, value, path: `events[${i}]`, type: "event"}));
      array(review.submissions?.records).forEach((value, i) => records.push({id: `submission-${i}`, label: "Development submission", subtitle: `${value.day} · ${value.version}`, status: value.result?.status, value, path: `review.submissions.records[${i}]`, type: "submission"}));
      array(review.review_invitations?.records).forEach((value, i) => records.push({id: `invitation-${i}`, label: "Review invitation metadata", subtitle: `${value.version} · expires ${value.expires}`, status: value.used ? "used" : "unused", value, path: `review.review_invitations.records[${i}]`, type: "invitation"}));
      return records.map((r, i) => ({...r, index: i + 1}));
    }
    if (section === "artifacts") {
      const records = [{id: "readme", label: "Saved challenge README", value: c.readme ?? null, path: "conversation.readme", type: "draft"}, {id: "draft_meta", label: "Model draft metadata", value: c._draft_meta ?? null, path: "conversation._draft_meta", type: "artifact"}];
      array(p.workflow?.artifacts).forEach((value, i) => records.push({id: `artifact-${i}`, label: value.name || "Artifact", subtitle: value.description, value, path: `workflow.artifacts[${i}]`, type: "artifact"}));
      array(p.advice).forEach((value, i) => records.push({id: `advice-${i}`, label: `Advice · ${value.kind || i + 1}`, subtitle: short(value.content), value, at: value.created_at, path: `advice[${i}]`, type: "advice"}));
      return records.map((r, i) => ({...r, index: i + 1, subtitle: r.subtitle || short(r.value)}));
    }
    return [...Object.entries(p), ["review", review]].map(([key, value], i) => ({id: key, label: key, subtitle: short(value), index: i + 1, value, path: key, type: "raw"}));
  }
  function related(data, row) {
    const ids = [...new Set((row.type === "message" ? [row.value.id] : row.type === "field" ? array(row.value.evidence).map(e => e.message_id) : [row.value?.trigger?.message_id || row.value?.message_id]).filter(Boolean))];
    return {messageId: ids.length === 1 ? ids[0] : null, messageIds: ids,
      messages: rows(data, "messages").filter(r => ids.includes(r.value.id)),
      calls: rows(data, "calls").filter(r => ids.includes(r.value.trigger?.message_id)),
      changes: rows(data, "changes").filter(r => ids.includes(r.value.message_id)),
      fields: rows(data, "fields").filter(r => array(r.value?.evidence).some(e => ids.includes(e.message_id)))};
  }
  function requirementCells(data, row) {
    const definitions = array(data.review?.requirement_definitions?.[row.id]), saved = object(row.value?.requirements);
    return [...new Set([...definitions.map(d => d.id), ...Object.keys(saved)])].map(id => ({id,
      label: definitions.find(d => d.id === id)?.label || id,
      description: definitions.find(d => d.id === id)?.description || "",
      status: saved[id]?.status || "not_recorded", value: saved[id] ?? null}));
  }
  function select(records, query, filter, reverse) {
    const result = records.filter(r => (!filter || r.status === filter || r.type === filter) && (!query || `${r.label} ${r.path} ${pretty(r.value)}`.toLowerCase().includes(query.toLowerCase())));
    return reverse ? result.slice().reverse() : result;
  }
  function totals(traces) {
    const total = {input: 0, output: 0, reasoning: 0, duration: 0, measured: 0};
    for (const t of array(traces)) {
      if (typeof t.usage?.input_tokens === "number" && typeof t.usage?.output_tokens === "number") {total.input += t.usage.input_tokens; total.output += t.usage.output_tokens; total.measured++;}
      if (typeof t.usage?.reasoning_tokens === "number") total.reasoning += t.usage.reasoning_tokens;
      if (typeof t.duration_ms === "number") total.duration += t.duration_ms;
    }
    return total;
  }
  return {array, object, pretty, short, captured, rows, related, requirementCells, select, totals};
});
