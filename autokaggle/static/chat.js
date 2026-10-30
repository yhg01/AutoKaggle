/* Conversation-first BOLD AutoKaggle. Remote content is rendered with DOM text nodes. */
"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const LAST_PROJECT = "autokaggle-chat-last-project";
  const SESSION_ENDED = "autokaggle-session-ended";
  const state = { projectId: null, conversation: null, config: null, projects: [], busy: false, polling: false, view: "chat", pending: null, localError: null, dismissedError: null, messageKey: "", selectedTopic: null, selectedItem: null, knowledgeTopic: null, knowledgeQuestion: null, renderedKnowledgeTopic: null, checklistKey: "", workflow: null, workflowLoading: false, workflowBusy: false, workflowUncertain: false, workflowError: null, dataProject: null, dataLoading: false, dataBusy: false, dataDirty: false, dataSnapshot: "", contactBusy: false, contactError: null, bypassDrafts: {}, scopeDrafts: {}, scopeDraftsLoaded: false, signingOut: false, projectUnavailable: false };
  const topics = [
    { id: "problem", label: "Problem", fields: ["question", "task", "data", "evaluation", "leakage"] },
    { id: "approach", label: "Method & deployment", fields: ["methodology", "deployment", "protocol"] },
    { id: "baseline", label: "Baseline", fields: ["difficulty"] },
    { id: "setup", label: "Setup", fields: [] }
  ];
  const statusLabels = { answered: "Recorded", partial: "In progress", missing: "To discuss", deferred: "Open question" };

  function element(tag, className, text) { const node = document.createElement(tag); if (className) node.className = className; if (text !== undefined && text !== null) node.textContent = String(text); return node; }
  function readStorage(key) { try { return window.localStorage.getItem(key); } catch (_) { return null; } }
  function writeStorage(key, value) { try { if (value === null) window.localStorage.removeItem(key); else window.localStorage.setItem(key, value); } catch (_) { /* The conversation still works without local storage. */ } }
  function draftKey(id) { return `autokaggle-chat-compose:${id}`; }
  function pendingKey(id) { return `autokaggle-chat-pending:${id}`; }
  function rememberCompose() { if (state.projectId) writeStorage(draftKey(state.projectId), $("message-input").value); }
  function rememberPending(value) { state.pending = value; if (state.projectId) writeStorage(pendingKey(state.projectId), value ? JSON.stringify(value) : null); }
  function loadPending(id) {
    try { const value = JSON.parse(readStorage(pendingKey(id)) || "null"); return value && value.project_id === id && ["messages", "skip", "draft", "retry", "revision", "continue", "bypass", "scope"].includes(value.action) && typeof value.request_id === "string" ? value : null; } catch (_) { return null; }
  }
  function readableError(detail) { if (typeof detail === "string") return detail; if (Array.isArray(detail)) return detail.map((item) => item.msg || "Invalid input").join("; "); return "The request could not be completed. Please try again."; }
  async function api(path, options = {}) {
    const controller = new AbortController(); const timeout = window.setTimeout(() => controller.abort(), options.method === "POST" && path.endsWith("/workflow") ? 600000 : 150000);
    try {
      const response = await fetch(path, { credentials: "same-origin", ...options, signal: controller.signal, headers: { ...(options.body ? { "Content-Type": "application/json" } : {}), ...options.headers } });
      const data = (response.headers.get("content-type") || "").includes("application/json") ? await response.json() : null;
      if (!response.ok) { const error = new Error(readableError(data?.detail)); error.status = response.status; throw error; }
      if (!data) throw new Error("The server returned an unexpected response. Please try again.");
      return data;
    } catch (error) { if (error.name === "AbortError") throw new Error("The connection timed out. Your request may still be running. Retry to recover its result."); if (error instanceof TypeError) throw new Error("The connection was interrupted. Your text is saved here. Retry when the connection returns."); throw error; }
    finally { window.clearTimeout(timeout); }
  }
  function base(id = state.projectId) { return `/api/projects/${encodeURIComponent(id)}/conversation`; }
  function projectPath(id = state.projectId) { return `/api/projects/${encodeURIComponent(id)}`; }
  function working() { return state.signingOut || state.busy || state.contactBusy || state.polling || state.workflowLoading || state.workflowBusy || state.dataLoading || state.dataBusy || state.conversation?.status === "working"; }
  function contactRequired() { return !!state.conversation && (state.conversation.contact_required ?? !state.conversation.setup?.organizer_email); }
  function inRevision() { return state.conversation?.review?.mode === "revision"; }
  function reviewAvailable() { return !!state.conversation?.readme || inRevision() || !!state.workflow?.version; }
  function renderContact() {
    const required = contactRequired(); const unavailable = !!state.projectUnavailable;
    $("email-gate").hidden = !required || unavailable;
    $("chat-view").hidden = unavailable || required || state.view !== "chat";
    $("readme-view").hidden = unavailable || required || state.view !== "readme";
    $("review-view").hidden = unavailable || required || state.view !== "review";
    $("interview-topics").hidden = required || unavailable;
    $("checklist-toggle").hidden = required || unavailable;
    document.querySelector(".view-tabs").hidden = required || unavailable;
    $("email-existing-note").hidden = userCount() === 0;
    $("email-error").textContent = state.contactError || ""; $("email-error").hidden = !state.contactError;
    $("organizer-email").disabled = working(); $("save-organizer-email").disabled = working() || !state.conversation;
    $("save-organizer-email").textContent = state.contactBusy ? "Saving…" : userCount() ? "Save email and continue →" : "Continue to interview →";
    $("organizer-email-form").setAttribute("aria-busy", String(state.contactBusy));
  }
  async function saveOrganizerEmail() {
    if (working() || !state.projectId || !state.conversation) return;
    const input = $("organizer-email"); const email = input.value.trim(); input.value = email;
    if (!input.reportValidity()) return;
    state.contactBusy = true; state.contactError = null; updateControls();
    try {
      const result = await api(`${projectPath()}/setup`, { method: "PATCH", body: JSON.stringify({ organizer_email: email }) });
      state.conversation = result.conversation || await api(base());
      input.value = ""; renderConversation({ scroll: true }); await refreshWorkflow();
    } catch (error) { state.contactError = error.message; }
    finally { state.contactBusy = false; updateControls(); if (!contactRequired()) $("message-input").focus(); }
  }
  function userCount() { return (state.conversation?.messages || []).filter((message) => message.role === "user").length; }
  function setBusy(value, label = "Thinking through your challenge…") { state.busy = value; $("thinking-text").textContent = label; updateControls(); if (state.pending?.action === "messages") renderMessages(true); }
  function updateControls() {
    const busy = working(); const ready = !!state.projectId && !!state.conversation && !contactRequired(); const uncertain = !!state.pending && !busy; const blockedByError = state.conversation?.status === "error";
    const canCreate = state.config?.can_create_projects !== false;
    $("sign-out").hidden = !state.config?.private_mode; $("sign-out").disabled = !!state.signingOut; $("sign-out").textContent = state.signingOut ? "Signing out…" : "Sign out";
    $("new-project").hidden = !canCreate; $("new-project").disabled = busy || !canCreate; $("message-input").disabled = busy || !ready;
    $("send-message").disabled = busy || !ready || uncertain || blockedByError || !$("message-input").value.trim();
    $("skip-question").hidden = !state.conversation?.current_question || !!state.conversation?.scope_checkpoint; $("skip-question").disabled = busy || !ready || uncertain || blockedByError;
    $("draft-readme").disabled = busy || !ready || uncertain || userCount() === 0;
    const canContinue = state.conversation?.interview?.can_continue === true && state.conversation?.review?.mode !== "revision";
    for (const id of ["continue-interview", "draft-continue-interview"]) { $(id).hidden = !canContinue; $(id).disabled = busy || !ready || uncertain || blockedByError; $(id).title = `Continue with up to ${state.conversation?.interview?.followups_limit || 8} focused questions. Earlier answers are kept.`; }
    $("readme-tab").disabled = !ready || !state.conversation?.readme; $("review-tab").disabled = !ready || !reviewAvailable(); $("open-data").disabled = busy || !ready || uncertain;
    $("download-readme").disabled = !state.conversation?.readme || busy;
    $("thinking-message").hidden = !busy; $("message-form").setAttribute("aria-busy", String(busy));
    $("retry-action").disabled = busy;
    $("answer-in-chat").disabled = busy || !ready;
    updateWorkflowControls(); updateDataControls(); renderContact(); renderReviewControls(); updateBypassControls();
    renderError();
  }
  function showError(text, heading = "Something needs attention") { state.localError = { text, heading }; state.dismissedError = null; renderError(); }
  function renderError() {
    let error = state.localError;
    if (!error && state.conversation?.status === "error") error = { heading: "We could not finish that step", text: state.conversation.error || "Please retry, or draft a README from the answers already recorded." };
    if (!error && state.pending && !working()) error = { heading: "A previous request needs to be checked", text: "Retry to recover the result. The same request ID prevents a duplicate message." };
    const key = error ? `${error.heading}:${error.text}` : null;
    $("error-banner").hidden = !error || state.dismissedError === key;
    if (error) { $("error-heading").textContent = error.heading; $("error-text").textContent = error.text; }
    $("retry-action").hidden = !!state.projectUnavailable || (!state.pending && !state.conversation?.can_retry && !!state.conversation);
    $("retry-action").textContent = !state.conversation ? "Reconnect" : "Retry";
  }
  function decodeReferences(text) {
    const names = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: "\u00a0" };
    return String(text).replace(/&(#x[\da-f]+|#\d+|amp|lt|gt|quot|apos|nbsp);/gi, (whole, value) => {
      if (!value.startsWith("#")) return names[value.toLowerCase()] || whole;
      const hex = value[1].toLowerCase() === "x"; const point = Number.parseInt(value.slice(hex ? 2 : 1), hex ? 16 : 10);
      return Number.isFinite(point) && point > 0 && point <= 0x10ffff && !(point >= 0xd800 && point <= 0xdfff) ? String.fromCodePoint(point) : whole;
    });
  }
  function inline(parent, text) {
    text = decodeReferences(text);
    const pattern = /(`[^`\n]+`|\*\*[^*\n]+\*\*|\[[^\]\n]+\]\(https?:\/\/[^)\s]+\))/g; let end = 0;
    for (const match of text.matchAll(pattern)) {
      parent.append(document.createTextNode(text.slice(end, match.index))); const value = match[0];
      if (value.startsWith("`")) parent.append(element("code", "", value.slice(1, -1)));
      else if (value.startsWith("**")) parent.append(element("strong", "", value.slice(2, -2)));
      else { const parts = value.match(/^\[([^\]]+)\]\((https?:\/\/[^)]+)\)$/); const link = element("a", "", parts[1]); link.href = parts[2]; link.target = "_blank"; link.rel = "noopener noreferrer"; parent.append(link); }
      end = match.index + value.length;
    }
    parent.append(document.createTextNode(text.slice(end)));
  }
  function markdown(text, className = "") {
    const container = element("div", className); let paragraph = []; let list = null; let fenced = false; let code = [];
    function flush() { if (paragraph.length) { const p = element("p"); inline(p, paragraph.join(" ")); container.append(p); paragraph = []; } }
    for (const line of String(text || "").split(/\r?\n/)) {
      if (/^\s*```/.test(line)) { flush(); list = null; if (fenced) { const pre = element("pre"); pre.append(element("code", "", code.join("\n"))); container.append(pre); code = []; } fenced = !fenced; continue; }
      if (fenced) { code.push(line); continue; }
      if (!line.trim()) { flush(); list = null; continue; }
      const heading = line.match(/^(#{1,6})\s+(.+)$/);
      if (heading) { flush(); list = null; const node = element(`h${Math.min(4, heading[1].length)}`); inline(node, heading[2]); container.append(node); continue; }
      if (/^\s*(?:---+|\*\*\*+)\s*$/.test(line)) { flush(); list = null; container.append(element("hr")); continue; }
      const quote = line.match(/^>\s?(.*)$/); if (quote) { flush(); list = null; const node = element("blockquote"); inline(node, quote[1]); container.append(node); continue; }
      const bullet = line.match(/^\s*(?:[-*]|\d+\.)\s+(.+)$/);
      if (bullet) { flush(); const tag = /^\s*\d+\./.test(line) ? "ol" : "ul"; if (!list || list.tagName.toLowerCase() !== tag) { list = element(tag); container.append(list); } const item = element("li"); inline(item, bullet[1]); list.append(item); continue; }
      list = null; paragraph.push(line.trim());
    }
    flush(); if (code.length) { const pre = element("pre"); pre.append(element("code", "", code.join("\n"))); container.append(pre); } return container;
  }
  function checklistItems() { return state.conversation?.checklist || []; }
  function itemUnderstanding(item) {
    const required = item.required ?? item.id !== "difficulty";
    if (item.owner === "agent" || item.id === "trial") return { score: null, label: "Pending system check", detail: item.understanding?.detail || "The application must run this check. An interview answer cannot complete it.", completed: 0, total: 0, required: false };
    const scopedCounts = Object.fromEntries(["confirmed", "delegated", "exception"].map((status) => [status, (item.requirements || []).filter((entry) => entry.status === status).length]));
    const supplied = item.understanding;
    if (supplied && Number.isFinite(supplied.score) && Number.isInteger(supplied.completed) && Number.isInteger(supplied.total) && supplied.total >= 0) {
      const total = supplied.total; const completed = Math.max(0, Math.min(total, supplied.completed)); const bypassed = Math.max(0, Math.min(completed, Number.isInteger(supplied.bypassed) ? supplied.bypassed : 0));
      for (const mode of ["confirmed", "delegated", "exception"]) if (Number.isInteger(supplied[mode]) && supplied[mode] >= 0) scopedCounts[mode] = Math.min(completed, supplied[mode]);
      return { ...supplied, ...scopedCounts, bypassed, score: total ? Math.round(100 * completed / total) : 0, completed, total, required };
    }
    if (Array.isArray(item.requirements)) {
      const total = item.requirements.length;
      const bypassed = item.requirements.filter((entry) => entry.status === "bypassed").length;
      const completed = bypassed + item.requirements.filter((entry) => ["recorded", "confirmed", "delegated", "exception"].includes(entry.status) || (entry.status === "not_applicable" && entry.reason)).length;
      return { score: total ? Math.round(100 * completed / total) : 0, completed, total, required, bypassed, ...scopedCounts,
        label: total && completed === total ? bypassed ? "Resolved with bypasses" : "Requirements recorded" : "Details needed",
        detail: required ? `${completed} of ${total} required details are ${bypassed ? "resolved" : "recorded"}.${bypassed ? ` ${completed - bypassed} recorded · ${bypassed} bypassed.` : ""}` : "A reference baseline is optional. Its absence does not block the challenge." };
    }
    return { score: 0, completed: 0, total: 0, required, label: "Assessment pending", detail: "The saved answer is kept. Its individual requirements have not yet been assessed." };
  }
  function interviewTopics() {
    const items = checklistItems(); const supplied = state.conversation?.interview?.stages || [];
    const assignedFields = new Set(topics.filter((topic) => topic.id !== "setup").flatMap((topic) => supplied.find((entry) => entry.id === topic.id)?.fields || topic.fields));
    return topics.map((topic) => {
      const server = supplied.find((entry) => entry.id === topic.id);
      const fieldIds = topic.id === "setup" ? items.filter((item) => item.owner !== "agent" && item.id !== "trial" && !assignedFields.has(item.id)).map((item) => item.id) : Array.isArray(server?.fields) ? server.fields : topic.fields;
      const fields = items.filter((item) => fieldIds.includes(item.id) && item.owner !== "agent" && item.id !== "trial");
      const answered = fields.filter((item) => item.status === "answered").length;
      const status = fields.length && answered === fields.length ? "answered" : fields.some((item) => ["answered", "partial"].includes(item.status)) ? "partial" : fields.some((item) => item.status === "deferred") ? "deferred" : "missing";
      const requiredFields = fields.filter((item) => itemUnderstanding(item).required);
      const measured = (topic.id === "baseline" ? fields : requiredFields).map(itemUnderstanding);
      const completed = measured.reduce((sum, item) => sum + item.completed, 0); const total = measured.reduce((sum, item) => sum + item.total, 0); const bypassed = measured.reduce((sum, item) => sum + (item.bypassed || 0), 0);
      const recorded = server?.understanding;
      const understanding = Number.isInteger(recorded?.completed) && Number.isInteger(recorded?.total) && recorded.total >= 0
        ? { ...recorded, bypassed: Number.isInteger(recorded.bypassed) ? recorded.bypassed : bypassed, completed: Math.max(0, Math.min(recorded.total, recorded.completed)), score: recorded.total ? Math.round(100 * Math.max(0, Math.min(recorded.total, recorded.completed)) / recorded.total) : 0 }
        : { score: total ? Math.round(100 * completed / total) : 0, completed, total, bypassed };
      for (const status of ["confirmed", "delegated", "exception"]) understanding[status] = measured.reduce((sum, item) => sum + (item[status] || 0), 0);
      return { ...topic, fields: fieldIds, status: Object.hasOwn(statusLabels, server?.status) ? server.status : status, answered: server?.answered ?? answered, total: server?.total ?? fields.length, understanding };
    });
  }
  function understandingBar(score, label, className = "", count = null) {
    const bar = element("progress", `understanding-bar ${className}`); bar.max = 100; bar.value = score;
    bar.setAttribute("aria-label", label); bar.setAttribute("aria-valuetext", count ? coverageText(count) : `${score}% of requirements recorded`); return bar;
  }
  function coverageText(count, required = false) {
    const bypassed = Math.max(0, Math.min(count.completed, count.bypassed || 0));
    const confirmed = count.confirmed || 0; const delegated = count.delegated || 0; const exception = count.exception || count.exceptions || 0;
    const scopeOnly = Math.max(0, (count.scope_resolved || 0) - confirmed - delegated - exception);
    if (confirmed || delegated || exception || scopeOnly) {
      const parts = [[count.completed - bypassed - confirmed - delegated - exception - scopeOnly, "recorded"], [confirmed, "confirmed"], [delegated, "delegated"], [exception, "exception"], [scopeOnly, "scope accepted"], [bypassed, "bypassed"]].filter(([value]) => value > 0).map(([value, label]) => `${value} ${label}`);
      return `${count.completed} of ${count.total} ${required ? "required " : ""}details resolved (${parts.join(" · ")})`;
    }
    return `${count.completed} of ${count.total} ${required ? "required " : ""}details ${bypassed ? "resolved" : "recorded"}${bypassed ? ` (${count.completed - bypassed} recorded · ${bypassed} bypassed)` : ""}`;
  }
  function bypassDraft(field, requirementId) {
    state.bypassDrafts ||= {};
    const key = `${field}:${requirementId}`;
    const pending = state.pending?.action === "bypass" && state.pending.field === field && state.pending.requirement_id === requirementId ? state.pending : null;
    if (!state.bypassDrafts[key]) state.bypassDrafts[key] = { open: !!pending, reason: pending?.reason || "", error: pending ? "This change was not confirmed. Retry to check its result." : null };
    return state.bypassDrafts[key];
  }
  function updateBypassControls() {
    const blocked = working() || !state.projectId || !state.conversation || contactRequired();
    for (const control of document.querySelectorAll("[data-bypass-control], [data-scope-control]")) {
      const scope = control.getAttribute("data-scope-control"); const retry = (scope || control.getAttribute("data-bypass-control")) === "retry";
      control.disabled = blocked || (!!state.pending && !(retry && state.pending.action === (scope ? "scope" : "bypass")));
    }
  }
  function bypassControl(item, criterion) {
    const root = element("div", "requirement-bypass"); const draft = bypassDraft(item.id, criterion.id);
    const pending = state.pending?.action === "bypass" && state.pending.field === item.id && state.pending.requirement_id === criterion.id ? state.pending : null;
    const blocked = working() || !!state.pending || contactRequired();
    const prefix = `bypass-${item.id}-${criterion.id}`;
    const control = (label, action, callback) => {
      const button = element("button", "text-button", label); button.type = "button"; button.id = `${prefix}-${action}`;
      button.setAttribute("data-bypass-control", action); button.disabled = blocked;
      button.addEventListener("click", callback); return button;
    };
    if (pending) {
      const message = element("p", "bypass-feedback", draft.error || "Saving your change…"); message.setAttribute("role", "status"); root.append(message);
      if (!pending.remove) root.append(element("p", "bypass-pending-reason", pending.reason));
      const retry = control(pending.remove ? "Retry removal" : "Retry bypass", "retry", () => saveBypass(item.id, criterion.id, pending.remove, pending));
      retry.disabled = working() || contactRequired(); root.append(retry); return root;
    }
    if (!draft.open) {
      const open = control(criterion.status === "bypassed" ? "Edit bypass reason" : "Bypass requirement", "open", () => {
        if (working() || state.pending || contactRequired()) return;
        draft.open = true; if (!draft.reason) draft.reason = criterion.bypass?.reason || "";
        renderSummary(); $(`${prefix}-reason`)?.focus();
      });
      open.setAttribute("aria-expanded", "false"); root.append(open);
      if (criterion.status === "bypassed") root.append(control("Remove bypass", "remove", () => saveBypass(item.id, criterion.id, true)));
      if (draft.error) { const error = element("p", "bypass-feedback error", draft.error); error.setAttribute("role", "alert"); root.append(error); }
      return root;
    }
    const form = element("form", "bypass-form"); const reasonId = `${prefix}-reason`; const hintId = `${prefix}-hint`; const errorId = `${prefix}-error`;
    const label = element("label", "", "Reason for bypass (required)"); label.setAttribute("for", reasonId);
    const input = element("textarea", "bypass-reason"); input.id = reasonId; input.value = draft.reason; input.rows = 3; input.required = true; input.maxLength = 2000; input.disabled = blocked;
    input.setAttribute("data-bypass-control", "reason"); input.setAttribute("aria-describedby", `${hintId} ${errorId}`);
    const hint = element("p", "bypass-hint", "This accepts an unresolved detail. It does not add scientific evidence. Your reason stays with the challenge. Maximum 2,000 characters."); hint.id = hintId;
    const error = element("p", "bypass-feedback error", draft.error || ""); error.id = errorId; error.hidden = !draft.error; error.setAttribute("role", "alert");
    input.addEventListener("input", () => { draft.reason = input.value; draft.error = null; error.textContent = ""; error.hidden = true; });
    const actions = element("div", "bypass-actions"); const save = element("button", "button button-secondary button-small", "Save bypass"); save.type = "submit"; save.id = `${prefix}-save`; save.disabled = blocked; save.setAttribute("data-bypass-control", "save");
    const cancel = control("Cancel", "cancel", () => { if (working() || state.pending) return; draft.open = false; draft.error = null; renderSummary(); $(`${prefix}-open`)?.focus(); });
    actions.append(save, cancel); form.append(label, input, hint, error, actions);
    form.addEventListener("submit", (event) => { event.preventDefault(); draft.reason = input.value; saveBypass(item.id, criterion.id, false); });
    root.append(form); return root;
  }
  async function saveBypass(field, requirementId, remove = false, recovered = null) {
    if (working() || !state.projectId || !state.conversation || contactRequired() || (state.pending && !recovered)) return;
    const draft = bypassDraft(field, requirementId); const reason = draft.reason.trim();
    if (!recovered && !remove && (!reason || reason.length > 2000)) { draft.error = !reason ? "Enter a reason for this bypass." : "Use no more than 2,000 characters."; draft.open = true; renderSummary(); return; }
    const request = recovered || { project_id: state.projectId, action: "bypass", field, requirement_id: requirementId, reason, remove, request_id: crypto.randomUUID() };
    rememberPending(request); draft.error = null; state.localError = null; state.dismissedError = null;
    setBusy(true, remove ? "Removing the bypass…" : "Saving the bypass…"); renderSummary();
    try {
      const payload = { field: request.field, requirement_id: request.requirement_id, request_id: request.request_id, remove: !!request.remove, ...(!request.remove ? { reason: request.reason } : {}) };
      state.conversation = await api(`${base()}/requirements/bypass`, { method: "POST", body: JSON.stringify(payload) });
      rememberPending(null); delete state.bypassDrafts[`${field}:${requirementId}`]; renderConversation(); renderSummary();
      await refreshWorkflow();
    } catch (error) {
      if (error.status && error.status >= 400 && error.status < 500 && ![408, 409, 429].includes(error.status)) rememberPending(null);
      draft.error = error.message; draft.open = true;
      try { state.conversation = await api(base()); renderConversation(); } catch (_) { /* Keep the request ID until its own POST is confirmed. */ }
      renderSummary();
    } finally { setBusy(false); }
  }
  function scopeDraft(item) {
    state.scopeDrafts ||= {};
    if (!state.scopeDraftsLoaded) {
      try { const saved = JSON.parse(readStorage(`${pendingKey(state.projectId)}:scope-drafts`) || "{}"); if (saved && typeof saved === "object" && !Array.isArray(saved)) state.scopeDrafts = { ...saved, ...state.scopeDrafts }; } catch (_) { /* Use the current server record. */ }
      state.scopeDraftsLoaded = true;
    }
    const saved = state.scopeDrafts[item.id];
    if (!saved || typeof saved !== "object" || typeof saved.summary !== "string" || !saved.resolutions || typeof saved.resolutions !== "object") {
      const pending = state.pending?.action === "scope" && state.pending.field === item.id ? state.pending : null;
      const prior = pending || item.scope || {};
      const resolutions = {};
      for (const value of Array.isArray(prior.resolutions) ? prior.resolutions : []) resolutions[value.requirement_id] = { mode: value.mode, detail: value.detail || "" };
      state.scopeDrafts[item.id] = saved && typeof saved === "object" && typeof saved.summary === "string" && saved.resolutions && typeof saved.resolutions === "object"
        ? saved : { open: !!pending, summary: prior.summary || (typeof item.value === "string" ? item.value : ""), resolutions, error: null };
    }
    return state.scopeDrafts[item.id];
  }
  function rememberScopeDrafts() { if (state.projectId) writeStorage(`${pendingKey(state.projectId)}:scope-drafts`, JSON.stringify(state.scopeDrafts || {})); }
  function scopeCriteria(item) {
    return (item.requirements || []).filter((criterion) => ["confirmed", "delegated", "exception"].includes(criterion.status) || !["recorded", "bypassed"].includes(criterion.status) && !(criterion.status === "not_applicable" && criterion.reason));
  }
  function openScope(field, requirementId = null, mode = "confirmed", proposal = "") {
    if (working() || state.pending || contactRequired()) return;
    const item = checklistItems().find((entry) => entry.id === field);
    if (!item?.can_accept_scope) return;
    const draft = scopeDraft(item); draft.open = true; draft.error = null;
    const criterion = item.requirements?.find((entry) => entry.id === requirementId);
    if (criterion) {
      const chosen = mode === "delegated" && !criterion.can_delegate ? "confirmed" : mode;
      draft.resolutions[criterion.id] = { mode: chosen, detail: draft.resolutions[criterion.id]?.detail || "" };
      if (chosen === "confirmed" && proposal && !draft.summary.includes(proposal)) draft.summary = draft.summary ? `${draft.summary}\n\nProposed decision to review: ${proposal}` : proposal;
    }
    rememberScopeDrafts();
    const group = knowledgeGroups().find((entry) => entry.fields.includes(field)); showSummary(group?.id || null, field);
    const target = requirementId && mode !== "confirmed" ? `scope-${field}-${requirementId}-detail` : `scope-${field}-summary`;
    $(target)?.focus();
  }
  function scopeControl(item) {
    const root = element("section", "scope-control"); const draft = scopeDraft(item);
    const pending = state.pending?.action === "scope" && state.pending.field === item.id ? state.pending : null;
    const blocked = working() || !!state.pending || contactRequired();
    const button = (label, action, callback) => {
      const control = element("button", action === "open" || action === "save" ? "button button-secondary button-small" : "text-button", label); control.type = "button";
      control.id = `scope-${item.id}-${action}`; control.setAttribute("data-scope-control", action); control.disabled = blocked; control.addEventListener("click", callback); return control;
    };
    if (item.scope) {
      root.append(element("strong", "scope-status", item.scope.stale ? "Accepted scope needs review" : "Scope accepted by organizer"));
      root.append(element("p", "scope-saved-summary", item.scope.summary));
      root.append(element("p", "scope-hint", "The acceptance records your decisions. It does not verify scientific evidence or application checks."));
    }
    if (pending) {
      root.append(element("p", "scope-feedback", draft.error || "Saving the scope…"));
      const retry = button(pending.remove ? "Retry removal" : "Retry acceptance", "retry", () => saveScope(item.id, !!pending.remove, pending)); retry.disabled = working() || contactRequired(); root.append(retry); return root;
    }
    if (!draft.open) {
      root.append(button(item.scope ? "Edit accepted scope" : "Accept this scope", "open", () => openScope(item.id)));
      if (item.scope) root.append(button("Remove scope acceptance", "remove", () => saveScope(item.id, true)));
      if (draft.error) root.append(element("p", "scope-feedback error", draft.error));
      return root;
    }
    const form = element("form", "scope-form"); const prefix = `scope-${item.id}`;
    const label = element("label", "", "What should this part of the challenge mean?"); label.setAttribute("for", `${prefix}-summary`);
    const summary = element("textarea", "scope-summary"); summary.id = `${prefix}-summary`; summary.rows = 4; summary.maxLength = 2000; summary.required = true; summary.value = draft.summary; summary.disabled = blocked; summary.setAttribute("data-scope-control", "summary");
    summary.setAttribute("aria-describedby", `${prefix}-help`);
    const help = element("p", "scope-hint", "Edit this summary to state the decisions you accept. Items marked Covered by this summary will use this text. Unknown assumptions are not evidence. Maximum 2,000 characters."); help.id = `${prefix}-help`;
    summary.addEventListener("input", () => { draft.summary = summary.value; draft.error = null; rememberScopeDrafts(); });
    form.append(label, summary, help);
    const criteria = scopeCriteria(item);
    if (criteria.length) form.append(element("h4", "scope-decisions-heading", "Decisions this summary will cover"));
    for (const criterion of criteria) {
      const selection = draft.resolutions[criterion.id] ||= { mode: "confirmed", detail: "" };
      const row = element("div", "scope-decision"); row.id = `${prefix}-${criterion.id}`;
      const name = element("label", "", criterion.label); name.setAttribute("for", `${row.id}-mode`);
      row.append(name, element("p", "scope-current", criterion.value ? `Current record: ${criterion.value}` : "Unknown: no decision is recorded yet."));
      const select = element("select"); select.id = `${row.id}-mode`; select.setAttribute("data-scope-control", "mode"); select.disabled = blocked;
      for (const [value, text] of [["confirmed", "Covered by this summary"], ...(criterion.can_delegate ? [["delegated", "Let the agent choose"]] : []), ["exception", "Record an exception"], ["unresolved", "Leave unresolved"]]) { const option = element("option", "", text); option.value = value; select.append(option); }
      if (selection.mode === "delegated" && !criterion.can_delegate) selection.mode = "unresolved";
      select.value = selection.mode;
      const detailWrap = element("div", "scope-decision-detail"); detailWrap.hidden = !["delegated", "exception"].includes(selection.mode);
      const detailLabel = element("label", "", selection.mode === "exception" ? "Why is this exception acceptable?" : "What limits must the agent follow?"); detailLabel.setAttribute("for", `${row.id}-detail`);
      const detail = element("textarea", "scope-detail"); detail.id = `${row.id}-detail`; detail.rows = 2; detail.maxLength = 2000; detail.value = selection.detail || ""; detail.disabled = blocked; detail.required = !detailWrap.hidden; detail.setAttribute("data-scope-control", "detail");
      detail.addEventListener("input", () => { selection.detail = detail.value; draft.error = null; rememberScopeDrafts(); });
      const policy = element("p", "scope-hint", criterion.delegation_policy || "Specify the allowed choice and its limits. A delegation does not establish missing source facts.");
      policy.hidden = selection.mode !== "delegated"; detailWrap.append(detailLabel, detail, policy);
      select.addEventListener("change", () => { selection.mode = select.value; draft.error = null; rememberScopeDrafts(); detailWrap.hidden = !["delegated", "exception"].includes(selection.mode); detail.required = !detailWrap.hidden; detailLabel.textContent = selection.mode === "exception" ? "Why is this exception acceptable?" : "What limits must the agent follow?"; policy.hidden = selection.mode !== "delegated"; if (!detailWrap.hidden) detail.focus(); });
      row.append(select, detailWrap); form.append(row);
    }
    const error = element("p", "scope-feedback error", draft.error || ""); error.setAttribute("role", "alert"); error.hidden = !draft.error; form.append(error);
    const actions = element("div", "scope-actions"); const save = button("Accept this scope", "save", () => {}); save.type = "submit";
    const cancel = button("Cancel", "cancel", () => { if (working() || state.pending) return; draft.open = false; draft.error = null; rememberScopeDrafts(); renderSummary(); });
    actions.append(save, cancel); form.append(actions);
    form.addEventListener("submit", (event) => { event.preventDefault(); draft.summary = summary.value; saveScope(item.id); });
    root.append(form); return root;
  }
  async function saveScope(field, remove = false, recovered = null) {
    if (working() || !state.projectId || !state.conversation || contactRequired() || (state.pending && !recovered)) return;
    const item = checklistItems().find((entry) => entry.id === field); if (!item || (!item.can_accept_scope && !recovered)) return;
    const draft = scopeDraft(item); const summary = draft.summary.trim(); const resolutions = [];
    if (!remove && !recovered) {
      if (!summary || summary.length > 2000) draft.error = "Enter a scope summary of 1 to 2,000 characters.";
      else {
        draft.error = null;
        for (const criterion of scopeCriteria(item)) {
          const choice = draft.resolutions[criterion.id] || { mode: "confirmed" };
          if (choice.mode === "unresolved") continue;
          const detail = choice.mode === "confirmed" ? summary : String(choice.detail || "").trim();
          if (!["confirmed", "delegated", "exception"].includes(choice.mode) || choice.mode === "delegated" && !criterion.can_delegate) { draft.error = `Choose a permitted resolution for ${criterion.label}.`; break; }
          if (!detail || detail.length > 2000) { draft.error = `Add a specific ${choice.mode === "delegated" ? "limit" : "reason"} for ${criterion.label}, up to 2,000 characters.`; break; }
          resolutions.push({ requirement_id: criterion.id, mode: choice.mode, detail });
        }
      }
      if (draft.error) { draft.open = true; rememberScopeDrafts(); renderSummary(); return; }
    }
    const request = recovered || { project_id: state.projectId, action: "scope", field, summary, resolutions, remove, request_id: crypto.randomUUID() };
    rememberPending(request); draft.error = null; state.localError = null; state.dismissedError = null;
    setBusy(true, remove ? "Removing scope acceptance…" : "Recording your scope decisions…"); renderSummary();
    try {
      const payload = { field: request.field, request_id: request.request_id, remove: !!request.remove, ...(!request.remove ? { summary: request.summary, resolutions: request.resolutions } : {}) };
      state.conversation = await api(`${base()}/scope`, { method: "POST", body: JSON.stringify(payload) });
      rememberPending(null); delete state.scopeDrafts[field]; rememberScopeDrafts(); renderConversation(); renderSummary(); await refreshWorkflow();
    } catch (error) {
      if (error.status && error.status >= 400 && error.status < 500 && ![408, 409, 429].includes(error.status)) rememberPending(null);
      draft.error = error.message; draft.open = true; rememberScopeDrafts();
      try { state.conversation = await api(base()); renderConversation(); } catch (_) { /* Preserve the exact payload until its POST is confirmed. */ }
      renderSummary();
    } finally { setBusy(false); }
  }
  function renderScopeCheckpoint() {
    const root = $("scope-checkpoint"); root.replaceChildren(); const checkpoint = state.conversation?.scope_checkpoint;
    const item = checkpoint && checklistItems().find((entry) => entry.id === checkpoint.field);
    root.hidden = !checkpoint || !item || contactRequired(); if (root.hidden) return;
    root.append(element("strong", "", "Let’s make this decision explicit"));
    root.append(element("p", "", checkpoint.reason || "We have asked about this detail twice. Review a decision, delegate an allowed choice, or record an exception."));
    const proposal = typeof checkpoint.proposed_answer === "string" ? checkpoint.proposed_answer : "";
    if (proposal) root.append(element("p", "scope-proposal", `Agent proposal · not yet accepted: ${proposal}`));
    const actions = element("div", "scope-checkpoint-actions");
    for (const [mode, label] of [["confirmed", proposal ? "Review proposal" : "Review this decision"], ...(checkpoint.can_delegate ? [["delegated", "Let the agent choose"]] : []), ["exception", "Record an exception"]]) {
      const button = element("button", "text-button", label); button.type = "button"; button.setAttribute("data-scope-control", "checkpoint"); button.disabled = working() || !!state.pending || !item.can_accept_scope;
      button.addEventListener("click", () => openScope(item.id, checkpoint.requirement_id, mode, proposal)); actions.append(button);
    }
    root.append(actions);
  }
  function renderReadiness() {
    const readiness = state.conversation?.readiness;
    const ready = readiness?.ready === true; const total = readiness?.total || 0; const completed = readiness?.completed || 0;
    const label = readiness ? ready ? readiness.bypassed ? "Ready with bypasses" : "Challenge defined" : "Required details open" : "Assessment pending";
    const count = readiness ? coverageText({ ...readiness, completed, total }, true) : "Your recorded answers are kept.";
    $("readiness-status").textContent = label; $("readiness-count").textContent = count;
    $("readiness-summary").className = `readiness-summary${ready ? " complete" : ""}`;
    $("readiness-summary").title = readiness?.definition || "A research agent must be able to implement an attempt and interpret its score without inventing scientific assumptions.";
    $("readiness-details").textContent = ready ? "View requirements" : "View missing details";
    $("readiness-details").disabled = !readiness;
    $("draft-readiness-status").textContent = readiness ? ready ? readiness.bypassed ? "Ready with bypasses" : "Challenge definition complete" : "Working draft · required details remain open" : "Working draft · assessment pending";
    $("draft-readiness-detail").textContent = readiness ? `${count}. ${ready ? "Execution checks are separate." : "A draft does not mean the challenge is ready for review."} A reference baseline is optional.` : "Return to the interview to review the required details.";
    $("draft-readiness").className = `draft-readiness${ready ? " complete" : ""}`;
  }
  function knowledgeGroups() {
    return interviewTopics();
  }
  function renderChecklist() {
    renderReadiness();
    const stages = interviewTopics();
    const active = checklistItems().find((item) => item.active)?.id || state.conversation?.current_question?.field;
    const activeGroup = stages.find((group) => group.fields.includes(active))?.id;
    const current = state.conversation?.interview?.current_stage || activeGroup || (Object.hasOwn(state.conversation?.interview || {}, "current_stage") ? null : stages.find((item) => item.status !== "answered")?.id);
    const questionKey = JSON.stringify(state.conversation?.current_question || null);
    const questionChanged = state.knowledgeQuestion !== questionKey;
    if (questionChanged) { state.knowledgeQuestion = questionKey; state.knowledgeTopic = null; }
    const selected = state.knowledgeTopic || activeGroup || current || "problem";
    const key = JSON.stringify([state.projectId, stages, checklistItems(), selected, current, questionKey, state.conversation?.readiness]);
    if (key === state.checklistKey) return;
    state.checklistKey = key;
    const focusedId = document.activeElement?.id; const scrollTop = state.renderedKnowledgeTopic === selected ? $("knowledge-items").scrollTop : 0;
    const root = $("interview-topics"); root.replaceChildren();
    for (const [index, topic] of stages.entries()) {
      const score = topic.understanding.score; const count = topic.understanding; const optional = topic.id === "baseline";
      const progress = optional ? "Optional" : count.total ? `${count.completed}/${count.total}` : "Pending";
      const button = element("button", `topic-button ${topic.status}${count.bypassed ? " has-bypass" : ""}${current === topic.id ? " current" : ""}${selected === topic.id ? " selected" : ""}`); button.type = "button"; button.id = `topic-${topic.id}`;
      button.setAttribute("aria-pressed", String(selected === topic.id)); button.setAttribute("aria-controls", "knowledge-items");
      button.setAttribute("aria-label", `${topic.label}: ${optional ? "optional reference baseline" : coverageText(count, true)}. Show checklist`);
      if (current === topic.id) button.setAttribute("aria-current", "step");
      const icon = element("span", "topic-number", score === 100 ? "✓" : String(index + 1)); icon.setAttribute("aria-hidden", "true");
      const label = element("span", "topic-copy"); const heading = element("span", "topic-heading"); heading.append(element("strong", "", topic.label), element("span", "topic-score", progress)); label.append(heading, understandingBar(score, `${topic.label} requirements`, "", count)); button.append(icon, label);
      button.addEventListener("click", () => { state.knowledgeTopic = topic.id; setView("chat"); renderChecklist(); }); root.append(button);
    }
    renderKnowledge(selected);
    $("knowledge-items").scrollTop = scrollTop; state.renderedKnowledgeTopic = selected;
    if (questionChanged) revealKnowledgeQuestion();
    if (focusedId && (focusedId.startsWith("topic-") || focusedId.startsWith("knowledge-item-"))) $(focusedId)?.focus({ preventScroll: true });
    if ($("summary-dialog").open) renderSummary();
  }
  function revealKnowledgeQuestion() {
    const root = $("knowledge-items"); const active = root.querySelector(".knowledge-item.active");
    if (!active || !root.clientHeight) return;
    const bounds = root.getBoundingClientRect(); const row = active.getBoundingClientRect();
    if (row.top < bounds.top) root.scrollTop -= bounds.top - row.top;
    else if (row.bottom > bounds.bottom) root.scrollTop += row.bottom - bounds.bottom;
  }
  function renderKnowledge(selected) {
    const group = knowledgeGroups().find((entry) => entry.id === selected) || knowledgeGroups()[0];
    const items = checklistItems().filter((item) => group.fields.includes(item.id) || (group.id === "baseline" && (item.owner === "agent" || item.id === "trial")));
    $("knowledge-topic").textContent = group.label;
    $("knowledge-note").title = state.conversation?.interview?.understanding_note || "Counts show evidence and explicit manual bypasses. They do not measure scientific accuracy or completed execution checks.";
    const root = $("knowledge-items"); root.replaceChildren();
    for (const item of items) {
      const understanding = itemUnderstanding(item); const agentOwned = understanding.score === null;
      const button = element("button", `knowledge-item${understanding.bypassed ? " has-bypass" : ""}${item.active ? " active" : ""}${agentOwned ? " system-check" : ""}`); button.type = "button"; button.id = `knowledge-item-${item.id}`; button.setAttribute("aria-haspopup", "dialog");
      button.setAttribute("aria-label", `${item.label}: ${agentOwned ? "Pending system check" : `${coverageText(understanding)}${understanding.required ? ", required" : ", optional"}`}${item.active ? ". Current question" : ""}. View facts and gaps`);
      const heading = element("span", "knowledge-item-heading"); heading.append(element("span", "knowledge-item-name", item.label), element("span", "knowledge-item-score", agentOwned ? "Pending" : understanding.total ? `${understanding.completed}/${understanding.total}${understanding.bypassed ? ` · ${understanding.bypassed} bypassed` : ""}` : "Pending"));
      button.append(heading);
      if (!agentOwned) button.append(understandingBar(understanding.score, `${item.label} requirements`, "", understanding));
      button.append(element("span", "knowledge-item-state", understanding.bypassed ? `${understanding.completed - understanding.bypassed} recorded · ${understanding.bypassed} bypassed` : item.scope ? item.scope.stale ? "Accepted scope needs review" : "Scope accepted by organizer" : item.active ? "Current question" : agentOwned ? "Application check" : !understanding.required ? "Optional reference" : item.status === "deferred" ? "Required · unresolved" : understanding.label));
      button.addEventListener("click", () => showSummary(group.id, item.id)); root.append(button);
    }
    if (!items.length) root.append(element("p", "knowledge-empty", state.conversation ? "No items in this topic." : "Loading the checklist…"));
    const measured = items.map(itemUnderstanding).filter((item) => item.score !== null);
    const defined = measured.reduce((sum, item) => sum + item.completed, 0); const total = measured.reduce((sum, item) => sum + item.total, 0);
    const bypassed = measured.reduce((sum, item) => sum + (item.bypassed || 0), 0);
    const scopeCounts = Object.fromEntries(["confirmed", "delegated", "exception"].map((mode) => [mode, measured.reduce((sum, item) => sum + (item[mode] || 0), 0)]));
    $("knowledge-update").textContent = `${group.label}: ${coverageText({ completed: defined, total, bypassed, ...scopeCounts })}.${group.id === "baseline" ? " A reference baseline is optional." : ""}`;
  }
  function renderSummary() {
    const groups = knowledgeGroups();
    const selected = groups.find((topic) => topic.id === state.selectedTopic);
    const items = checklistItems(); const selectedItem = items.find((item) => item.id === state.selectedItem);
    $("summary-title").textContent = selectedItem ? selectedItem.label : selected ? selected.label : "Your challenge so far";
    const root = $("summary-content"); const scrollTop = root.scrollTop; const focused = typeof document !== "undefined" ? document.activeElement : null; const focusId = (focused?.id?.startsWith("bypass-") || focused?.id?.startsWith("scope-")) ? focused.id : null; const selection = focusId ? [focused.selectionStart, focused.selectionEnd] : null; root.replaceChildren();
    if (!selectedItem && !selected && state.conversation?.readiness) {
      const readiness = state.conversation.readiness; const section = element("section", "summary-readiness");
      section.append(element("h3", "", readiness.ready ? readiness.bypassed ? "Ready with bypasses" : "Challenge defined" : "Required details remain open"), element("p", "", readiness.definition), element("p", "", `${coverageText(readiness, true)}. A reference baseline is optional.`));
      root.append(section);
    }
    for (const group of selected ? [selected] : groups) {
      const recorded = items.filter((item) => (selectedItem ? item.id === selectedItem.id : group.fields.includes(item.id) && (item.value || item.status === "deferred" || item.required === true)));
      if (group.id === "setup" && !recorded.length) continue;
      const section = element("section", "summary-section"); if (!selectedItem) section.append(element("h3", "", group.label));
      if (!recorded.length) section.append(element("p", "summary-empty", "We have not recorded an answer for this topic yet."));
      for (const item of recorded) {
        const row = element("div", "summary-answer"); const understanding = itemUnderstanding(item);
        row.append(element("h4", "", selectedItem ? understanding.score === null ? "Application check" : `${understanding.total ? `${understanding.completed} of ${understanding.total} details` : "Assessment pending"} · ${understanding.required ? "Required" : "Optional"}` : `${item.label}${understanding.required ? "" : " · Optional"}`));
        if (selectedItem) row.append(element("p", "summary-understanding", understanding.detail));
        if (selectedItem && (item.can_accept_scope || item.scope || state.pending?.action === "scope" && state.pending.field === item.id)) row.append(scopeControl(item));
        const normalized = (text) => typeof text === "string" ? text.replace(/\s+/g, " ").trim() : "";
        const displayedFacts = []; const displayedScope = selectedItem && item.scope?.summary ? [normalized(item.scope.summary)] : [];
        if (Array.isArray(item.requirements) && item.requirements.length) {
          const requirements = element("ul", "requirement-list");
          for (const criterion of item.requirements) {
            const scoped = ["confirmed", "delegated", "exception"].includes(criterion.status);
            const recorded = scoped || criterion.status === "recorded" || (criterion.status === "not_applicable" && criterion.reason);
            const bypassed = criterion.status === "bypassed";
            if (!selectedItem && recorded) continue;
            const entry = element("li", `requirement ${scoped ? criterion.status : bypassed ? "bypassed" : recorded ? "recorded" : "missing"}`);
            const status = scoped ? ({ confirmed: "Confirmed by organizer", delegated: "Delegated to agent", exception: "Organizer exception" }[criterion.status]) : bypassed ? "Manually bypassed" : criterion.status === "not_applicable" && criterion.reason ? "Not applicable" : recorded ? "Recorded" : criterion.status === "deferred" ? "Unresolved" : "Missing";
            entry.append(element("strong", "", `${criterion.label} · ${status}`));
            const decision = scoped ? criterion.resolution?.detail || criterion.value : "";
            const displayedEvidence = [];
            if (decision) {
              const text = normalized(decision);
              if (!displayedScope.includes(text)) { entry.append(element("p", "requirement-resolution", decision)); displayedScope.push(text); }
              else entry.append(element("p", "requirement-resolution-reference", normalized(item.scope?.summary) === text ? "Covered by the accepted summary above." : "Uses the scope decision recorded above."));
              displayedEvidence.push(text); displayedFacts.push(text);
            }
            if (criterion.value && !displayedEvidence.includes(normalized(criterion.value))) {
              entry.append(element("p", scoped ? "requirement-underlying-fact" : "", scoped ? `Underlying fact: ${criterion.value}` : criterion.value));
              displayedFacts.push(normalized(criterion.value)); displayedEvidence.push(normalized(criterion.value));
            }
            const reason = bypassed ? criterion.bypass?.reason : criterion.reason;
            if (reason && !displayedEvidence.includes(normalized(reason)) && !(scoped && displayedScope.includes(normalized(reason)))) {
              entry.append(element("p", bypassed ? "requirement-bypass-reason" : "requirement-reason", scoped ? `${criterion.resolution?.policy ? "Delegation policy" : "Recorded reason"}: ${reason}` : reason));
              displayedEvidence.push(normalized(reason)); displayedFacts.push(normalized(reason));
            }
            let underlyingLabelShown = false;
            for (const evidence of selectedItem ? criterion.evidence || [] : []) {
              const quotes = typeof evidence === "string" ? [evidence] : Array.isArray(evidence?.quotes) ? evidence.quotes : [evidence?.quote || evidence?.excerpt || evidence?.text];
              for (const text of quotes) {
                const quote = normalized(text);
                if (quote && !displayedEvidence.some((shown) => shown.includes(quote)) && !(scoped && [...displayedScope, ...displayedFacts].some((shown) => shown.includes(quote)))) {
                  if (scoped && !underlyingLabelShown) { entry.append(element("span", "requirement-source-label", "Underlying source")); underlyingLabelShown = true; }
                  entry.append(element("blockquote", "requirement-evidence", text));
                  displayedEvidence.push(quote); displayedFacts.push(quote);
                }
              }
            }
            if (selectedItem && criterion.can_bypass && (!recorded || bypassed)) entry.append(bypassControl(item, criterion));
            requirements.append(entry);
          }
          if (requirements.children.length) row.append(requirements);
        }
        if (item.value) {
          const value = typeof item.value === "string" ? item.value : JSON.stringify(item.value);
          if (selectedItem && item.requirements?.length) {
            const original = normalized(value);
            const remaining = displayedFacts.some((fact) => fact.includes(original)) ? "" : displayedFacts.filter(Boolean).sort((a, b) => b.length - a.length).reduce((text, fact) => text.split(fact).join(" "), original).trim();
            if (remaining) { const details = element("details", "summary-recorded-answer"); details.append(element("summary", "", "Recorded answer"), element("p", "", value)); row.append(details); }
          } else row.append(element("p", "", value));
        } else if (selectedItem) row.append(element("p", "summary-empty", "No answer has been recorded yet."));
        if (item.status === "deferred") row.append(element("p", "summary-open", "Open question" + (item.gap ? `: ${item.gap}` : ".")));
        else if (item.gap && (selectedItem || item.status === "partial")) row.append(element("p", "summary-open", `To clarify: ${item.gap}`));
        section.append(row);
      }
      root.append(section);
    }
    root.scrollTop = scrollTop;
    if (focusId) { const replacement = $(focusId); if (replacement) { replacement.focus({ preventScroll: true }); if (selection && replacement.setSelectionRange && selection.every(Number.isInteger)) replacement.setSelectionRange(...selection); } }
  }
  function showSummary(topicId = null, itemId = null) {
    state.selectedTopic = topicId; state.selectedItem = itemId; renderSummary();
    if (!$("summary-dialog").open) $("summary-dialog").showModal();
    updateControls();
  }
  function safeWebLink(value) {
    if (typeof value !== "string" || !value) return null;
    try { const url = new URL(value, window.location.origin); return ["http:", "https:"].includes(url.protocol) ? url.href : null; } catch (_) { return null; }
  }
  function workflowPresentation(workflow) {
    const descriptions = {
      not_built: ["Not built", "Build draft files and check what is ready for organizer review."],
      draft: ["Draft files", "Draft files are available. Some checks are still pending."],
      ready_for_review: ["Ready for review", "The required checks passed. The organizer still needs to review the package."],
      needs_changes: ["Changes needed", "Check the blocked items before the challenge can proceed."],
      stale: ["Earlier version", "The challenge has changed. Build the package again to include the latest answers."]
    };
    const status = workflow?.status || "not_built"; return { status, text: descriptions[status] || ["Status unavailable", "Check the package status before you continue."] };
  }
  function updateWorkflowControls() {
    const blocked = working() || !!state.pending || !state.projectId || !state.conversation || contactRequired();
    $("build-workflow").disabled = blocked || state.workflowLoading || state.workflowUncertain || state.dataDirty || !state.conversation?.readme;
    $("build-workflow").textContent = state.workflowBusy ? "Working…" : state.workflow?.status && state.workflow.status !== "not_built" ? "Build again" : "Build review package";
    $("refresh-workflow").disabled = blocked || state.workflowLoading; $("refresh-workflow").textContent = state.workflowLoading ? "Checking…" : "Check status";
    $("retry-notification").disabled = blocked || state.workflowLoading || state.workflowUncertain || state.dataDirty;
    $("data-workbench").disabled = blocked;
    $("download-package").setAttribute("aria-disabled", String(blocked)); $("download-package").tabIndex = blocked ? -1 : 0;
    $("workflow-details").setAttribute("aria-busy", String(!!state.workflowLoading || !!state.workflowBusy));
  }
  function renderWorkflow() {
    const workflow = state.workflow; const presentation = workflowPresentation(workflow);
    $("workflow-status").textContent = presentation.text[0]; $("workflow-status").className = `workflow-status ${["draft", "ready_for_review", "needs_changes", "stale"].includes(presentation.status) ? presentation.status : ""}`;
    $("workflow-summary").textContent = state.dataDirty ? "Data settings have unsaved changes. Open Data and baseline checks and save them before building the package." : presentation.text[1]; $("workflow-error").textContent = state.workflowError || ""; $("workflow-error").hidden = !state.workflowError;
    const checks = $("workflow-checks"); checks.replaceChildren();
    for (const check of workflow?.checks || []) {
      const status = ["pass", "pending", "blocked"].includes(check.status) ? check.status : "pending"; const row = element("div", `workflow-check ${status}`); const icon = element("span", "check-marker", status === "pass" ? "✓" : status === "blocked" ? "!" : "·"); icon.setAttribute("aria-hidden", "true"); const body = element("div"); const heading = element("strong", "", check.label || check.id || "Check"); heading.append(element("span", "check-state", status === "pass" ? "Passed" : status === "blocked" ? "Blocked" : "Pending")); body.append(heading, element("p", "", check.detail || "")); row.append(icon, body); checks.append(row);
    }
    if (!workflow?.checks?.length) checks.append(element("p", "workflow-empty", "Checks appear after you build the draft."));
    const artifacts = $("workflow-artifacts"); artifacts.replaceChildren();
    if (workflow?.artifacts?.length) { artifacts.append(element("h3", "", "Files in the package")); for (const artifact of workflow.artifacts) { const row = element("p"); row.append(element("strong", "", artifact.name), document.createTextNode(artifact.description ? ` — ${artifact.description}` : "")); artifacts.append(row); } }
    const notification = workflow?.notification || {}; const notificationLabels = { not_ready: "Email not sent", not_configured: "Email is not configured", pending: "Email pending", sent: "Email sent", failed: "Email delivery failed" };
    $("notification-status").textContent = notificationLabels[notification.status] || "Email status unavailable"; $("notification-detail").textContent = notification.detail || "Build the draft first.";
    $("retry-notification").hidden = !["failed", "not_configured", "sent"].includes(notification.status) || presentation.status === "stale";
    $("retry-notification").textContent = notification.status === "sent" ? "Send a new review link" : "Retry email delivery";
    $("download-package").hidden = !workflow?.download_url || !!state.dataDirty; $("download-package").href = `${projectPath()}/workflow/package`; $("download-package").download = "challenge-review.zip";
    const review = reviewAvailable() ? `${window.location.origin}/?project=${encodeURIComponent(state.projectId)}&view=review` : null; $("review-link").hidden = !review || !!state.dataDirty; if (review) $("review-link").href = review;
    updateWorkflowControls(); renderReview();
  }
  function reviewLinks() {
    const workflow = state.workflow;
    if (!workflow || ["not_built", "stale"].includes(workflow.status) || state.dataDirty || contactRequired()) return {};
    const preview = `${projectPath()}/workflow/preview`;
    return {
      website: safeWebLink(workflow.website_url || (workflow.download_url ? preview : null)),
      package: safeWebLink(workflow.download_url),
      submission: safeWebLink(workflow.submission_url || (workflow.download_url ? `${preview}#submission` : null))
    };
  }
  function renderReviewControls() {
    const review = state.conversation?.review || {};
    const blocked = working() || !!state.pending || contactRequired() || !reviewAvailable();
    $("start-revision").disabled = blocked || (!inRevision() && review.can_start === false);
    $("start-revision").textContent = inRevision() && review.status !== "draft_ready" ? "Continue review →" : "Request changes →";
    $("review-build").disabled = !state.conversation?.readme || contactRequired();
    for (const id of ["review-website", "review-package", "review-submission"]) { $(id).setAttribute("aria-disabled", String(working() || !!state.pending)); $(id).tabIndex = working() || state.pending ? -1 : 0; }
  }
  function renderReview() {
    const workflow = state.workflow; const review = state.conversation?.review || {}; const presentation = workflowPresentation(workflow); const links = reviewLinks();
    $("review-version").textContent = workflow?.version ? `Version ${workflow.version}` : "No package yet";
    $("review-summary").textContent = state.workflowError ? state.workflowError : state.workflowLoading ? "Checking the draft package…" : presentation.text[1];
    for (const kind of ["website", "package", "submission"]) {
      const link = $(`review-${kind}`); link.hidden = !links[kind];
      if (links[kind]) link.href = links[kind];
      $(`review-${kind}-status`).textContent = links[kind] ? (kind === "submission" ? "Check evaluator readiness in the submission portal." : "Private draft") : presentation.status === "stale" ? "Build again to include your changes." : "Build the package to make this available.";
    }
    $("review-package").download = "challenge-review.zip";
    const changed = (review.changed_fields || []).map((field) => checklistItems().find((item) => item.id === field)?.label || field);
    $("review-change-summary").hidden = !inRevision();
    $("review-changes").textContent = changed.length ? `Round ${review.round || 1}: ${changed.join(", ")}.` : `Round ${review.round || 1}: No changed details recorded yet.`;
    const updatedPackage = !!(links.website && links.package && links.submission);
    $("review-feedback-detail").textContent = review.status === "draft_ready" ? (updatedPackage ? "The updated package is ready to inspect. Open the website, ZIP, and submission test above. You can request another round of changes." : "The revised draft is ready. Build the package again to refresh the website, ZIP, and submission test. You can request another round of changes.") : "Start a review conversation about the problem definition, method and deployment, or baseline reproduction. The agent keeps the earlier context and asks for specific details where needed.";
    $("review-pending").textContent = presentation.status === "ready_for_review" ? "The required checks passed. This remains a private draft until publication is approved." : "This is a private draft. Open checks must be resolved before the full workflow is ready. Review does not publish the challenge.";
    renderReviewControls();
  }
  async function startRevision() {
    const review = state.conversation?.review || {};
    if (working() || state.pending || contactRequired() || !reviewAvailable()) return;
    if (inRevision() && review.status !== "draft_ready") { setView("chat"); $("message-input").focus(); return; }
    await dispatch("revision");
    if (!state.pending && !state.localError) $("message-input").focus();
  }
  async function refreshWorkflow() {
    if (!state.projectId || state.workflowLoading) return;
    const id = state.projectId; state.workflowLoading = true; updateControls();
    try { const result = await api(`${projectPath(id)}/workflow`); if (id === state.projectId) { state.workflow = result; state.workflowError = null; state.workflowUncertain = false; } }
    catch (error) { if (id === state.projectId) state.workflowError = error.message; }
    finally { if (id === state.projectId) { state.workflowLoading = false; renderWorkflow(); updateControls(); } }
  }
  async function runWorkflow(action = "build") {
    if (working() || state.pending || contactRequired() || state.workflowLoading || state.workflowUncertain || state.dataDirty || !state.conversation?.readme) return;
    state.workflowBusy = true; state.workflowError = null; $("thinking-text").textContent = action === "notify" ? "Checking email delivery…" : "Building the review package…"; updateControls();
    try { state.workflow = await api(`${projectPath()}/workflow${action === "notify" ? "/notify" : ""}`, { method: "POST", body: "{}" }); }
    catch (error) { state.workflowUncertain = true; state.workflowError = `${error.message} Check status to confirm the result.`; }
    finally { state.workflowBusy = false; renderWorkflow(); updateControls(); }
  }
  function dataDefaults(project) {
    const design = project.design || {}; const answers = project.answers || {}; const names = (project.dataset?.columns || []).map((column) => column.name);
    return { design: { target: names.includes(design.target) ? design.target : "", task: design.task || "classification", metric: design.metric || "accuracy", split: design.split || "random", group_column: names.includes(design.group_column) ? design.group_column : "", time_column: names.includes(design.time_column) ? design.time_column : "", exclude_columns: [...new Set(design.exclude_columns || [])].filter((name) => names.includes(name) && name !== design.target).sort(), test_fraction: 0.2 }, answers: { data_origin: answers.data_origin || "unknown", labels_public: answers.labels_public || "unknown", rights: answers.rights || "unknown", compute_budget: answers.compute_budget || "", token_budget: answers.token_budget || "" } };
  }
  function collectDataForm() {
    const target = $("data-target").value;
    return { design: { target, task: $("data-task").value, metric: $("data-metric").value, split: $("data-split").value, group_column: $("data-group-column").value, time_column: $("data-time-column").value, exclude_columns: [...document.querySelectorAll("#data-exclude-columns input:checked")].map((input) => input.value).filter((name) => name !== target).sort(), test_fraction: 0.2 }, answers: { data_origin: $("data-origin-choice").value, labels_public: $("data-labels-public").value, rights: $("data-rights").value, compute_budget: $("data-compute-budget").value.trim(), token_budget: $("data-token-budget").value.trim() } };
  }
  function dataOptions(id, columns, selected, placeholder) {
    const select = $(id); select.replaceChildren(new Option(placeholder, "")); for (const column of columns) select.append(new Option(column.name, column.name)); select.value = selected || "";
  }
  function dataMetrics(selected) {
    const names = { accuracy: "Accuracy", balanced_accuracy: "Balanced accuracy", roc_auc: "ROC AUC", rmse: "Root mean squared error", mae: "Mean absolute error" };
    const allowed = $("data-task").value === "regression" ? ["rmse", "mae"] : ["accuracy", "balanced_accuracy", "roc_auc"];
    $("data-metric").replaceChildren(...allowed.map((name) => new Option(names[name], name))); $("data-metric").value = allowed.includes(selected) ? selected : allowed[0];
  }
  function dataSplitFields() {
    const split = $("data-split").value; $("data-group-field").hidden = split !== "group"; $("data-time-field").hidden = split !== "time";
    $("data-group-column").required = split === "group"; $("data-time-column").required = split === "time";
    $("data-split-help").textContent = { random: "Random rows require independent observations.", group: "Keep related observations together, such as samples from one patient or site.", time: "Use earlier observations for training and later observations for the hidden test." }[split] || "Choose a split.";
  }
  function dataMessage(text, error = false) { const id = error ? "data-error" : "data-notice"; $(id).textContent = text || ""; $(id).hidden = !text; }
  function updateDataControls() {
    const blocked = working() || !!state.pending || !state.dataProject; const dataset = state.dataProject?.dataset;
    document.querySelectorAll("#data-form input, #data-form select, #data-file, #data-example-confirm").forEach((input) => { input.disabled = blocked; });
    $("data-target").disabled = blocked || !dataset; $("data-group-column").disabled = blocked || !dataset || $("data-split").value !== "group"; $("data-time-column").disabled = blocked || !dataset || $("data-split").value !== "time";
    document.querySelectorAll("#data-exclude-columns input").forEach((input) => { input.disabled = blocked || input.value === $("data-target").value; if (input.value === $("data-target").value) input.checked = false; });
    $("save-data").disabled = blocked || !state.dataDirty; $("analyze-data").disabled = blocked || !dataset;
    $("load-data-example").disabled = blocked || !!dataset || !$("data-example-confirm").checked;
    $("reload-data").disabled = working(); $("data-save-state").textContent = state.dataLoading ? "Loading…" : state.dataBusy ? "Working…" : state.dataDirty ? "Unsaved changes" : state.dataProject ? "Saved" : "Not loaded";
    $("data-form").setAttribute("aria-busy", String(!!state.dataBusy || !!state.dataLoading));
    $("data-result-status").textContent = state.dataProject?.analysis ? state.dataDirty ? "Earlier result" : state.dataProject.analysis.summary?.blockers ? "Changes needed" : "Checked" : "Not run";
  }
  function markDataDirty() { if (!state.dataProject) return; state.dataDirty = JSON.stringify(collectDataForm()) !== state.dataSnapshot; updateDataControls(); renderWorkflow(); }
  function renderDataForm(project, draft = null) {
    state.dataProject = project; const defaults = dataDefaults(project); const values = draft || defaults; const columns = project.dataset?.columns || [];
    dataOptions("data-target", columns, values.design.target, columns.length ? "Select a target" : "Add a CSV first"); dataOptions("data-group-column", columns, values.design.group_column, "Select a column"); dataOptions("data-time-column", columns, values.design.time_column, "Select a column");
    $("data-task").value = values.design.task; dataMetrics(values.design.metric); $("data-split").value = values.design.split; dataSplitFields();
    for (const [key, id] of [["data_origin", "data-origin-choice"], ["labels_public", "data-labels-public"], ["rights", "data-rights"], ["compute_budget", "data-compute-budget"], ["token_budget", "data-token-budget"]]) $(id).value = values.answers[key] || (key.endsWith("budget") ? "" : "unknown");
    const excluded = $("data-exclude-columns"); excluded.replaceChildren();
    for (const column of columns) { const label = element("label", "data-checkbox"); const input = element("input"); input.type = "checkbox"; input.value = column.name; input.checked = values.design.exclude_columns.includes(column.name) && column.name !== values.design.target; label.append(input, document.createTextNode(column.name)); excluded.append(label); }
    if (!columns.length) excluded.append(element("p", "data-help", "Add a CSV to choose columns."));
    const profile = $("data-profile"); profile.replaceChildren();
    if (project.dataset) { const dataset = project.dataset; profile.append(element("strong", "", dataset.filename), element("span", "", `${Number(dataset.rows).toLocaleString()} rows · ${columns.length} columns${Number.isFinite(dataset.size_bytes) ? ` · ${(dataset.size_bytes / 1048576).toFixed(2)} MB` : ""}`)); }
    $("data-example").hidden = !!project.dataset; $("data-example-confirm").checked = false;
    $("data-upload-help").textContent = `CSV format · up to ${state.config?.max_upload_mb || 200} MB.${project.dataset ? " A new file replaces this dataset and clears its audit." : ""}`;
    state.dataSnapshot = JSON.stringify(defaults); state.dataDirty = JSON.stringify(collectDataForm()) !== state.dataSnapshot;
    renderDataAnalysis(project.analysis); updateDataControls();
  }
  function displayScore(value) { return typeof value === "number" && Number.isFinite(value) ? value.toLocaleString(undefined, { maximumFractionDigits: 4 }) : "—"; }
  function renderDataAnalysis(analysis) {
    $("data-audit-summary").textContent = analysis ? `${analysis.summary?.blockers ?? 0} blocking checks · ${analysis.summary?.warnings ?? 0} warnings · ${analysis.summary?.passed ?? 0} passed` : "Add a dataset, then run the checks. Results are measured from this dataset.";
    const baseline = $("data-baseline"); baseline.replaceChildren();
    if (analysis?.baseline) { const result = analysis.baseline; const card = element("div", "data-baseline-card"); card.append(element("strong", "", `Development baseline${result.metric ? ` · ${result.metric.replaceAll("_", " ")}` : ""}`));
      if (typeof result.score === "number" && Number.isFinite(result.score)) { const scores = element("div", "data-baseline-scores"); for (const [label, score] of [["Simple model", result.score], ["Dummy reference", result.dummy_score]]) { const item = element("div"); item.append(element("span", "", label), element("strong", "", displayScore(score))); scores.append(item); } card.append(scores, element("p", "", `Measured on ${result.validation_rows ?? "—"} validation rows within the training set. The final hidden test was not scored here.`)); }
      else card.append(element("p", "", "The baseline has not completed.")); if (result.detail) card.append(element("p", "", result.detail));
      if (analysis.split) card.append(element("p", "", `${analysis.split.train_rows ?? "—"} training rows · ${analysis.split.test_rows ?? "—"} hidden test rows`)); baseline.append(card);
    }
    const checks = $("data-audit-checks"); checks.replaceChildren();
    for (const [severity, title] of [["blocker", "Resolve these checks"], ["warning", "Review these warnings"], ["pass", "Passed checks"]]) { const items = (analysis?.checks || []).filter((check) => check.severity === severity); if (!items.length) continue; const group = element("details", `data-check-group ${severity}`); group.open = severity !== "pass"; group.append(element("summary", "", `${title} (${items.length})`)); for (const check of items) { const row = element("div", "data-check"); row.append(element("strong", "", check.title || check.id), element("p", "", check.detail || "")); if (check.action) row.append(element("p", "check-action", `Next step: ${check.action}`)); group.append(row); } checks.append(group); }
    const limits = $("data-audit-limitations"); limits.replaceChildren(); if (analysis?.limitations?.length) { const detail = element("details", "data-check-group"); detail.append(element("summary", "", "Limits of these checks")); for (const line of analysis.limitations) detail.append(element("p", "data-help", line)); limits.append(detail); }
  }
  async function openData() {
    if (working() || state.pending || !state.projectId) return;
    const draft = state.dataProject?.id === state.projectId && state.dataDirty ? collectDataForm() : null;
    state.dataLoading = true; dataMessage("Loading the dataset and design…"); dataMessage("", true); $("reload-data").hidden = true; if (!$("data-dialog").open) $("data-dialog").showModal(); updateControls();
    try { renderDataForm(await api(projectPath()), draft); dataMessage(""); }
    catch (error) { dataMessage("", false); dataMessage(error.message, true); $("reload-data").hidden = false; }
    finally { state.dataLoading = false; updateControls(); }
  }
  function invalidateWorkflow() {
    if (state.workflow && state.workflow.status !== "not_built") { state.workflow = { ...state.workflow, status: "stale", download_url: null, review_url: null, notification: { status: "not_ready", detail: "The data or evaluation changed. Build the package again before requesting review." } }; renderWorkflow(); }
  }
  async function saveDataIfNeeded() {
    if (!state.dataDirty) return;
    const project = await api(projectPath(), { method: "PATCH", body: JSON.stringify(collectDataForm()) }); renderDataForm(project); invalidateWorkflow();
  }
  function uploadDataFile(file) {
    return new Promise((resolve, reject) => {
      const request = new XMLHttpRequest(); request.open("POST", `${projectPath()}/dataset`); request.responseType = "json"; request.timeout = 30 * 60 * 1000;
      request.upload.addEventListener("progress", (event) => { if (!event.lengthComputable) return; const percent = Math.round(event.loaded / event.total * 100); $("data-upload-progress").value = percent; $("data-upload-percent").textContent = `${percent}%`; $("data-upload-state").textContent = percent === 100 ? "Upload complete. Reading the columns…" : "Uploading…"; });
      request.addEventListener("load", () => { if (request.status >= 200 && request.status < 300 && request.response) resolve(request.response); else reject(new Error(readableError(request.response?.detail))); });
      request.addEventListener("error", () => reject(new Error("The upload connection failed. Retry the file upload when the connection returns."))); request.addEventListener("timeout", () => reject(new Error("The upload timed out. Reopen this dialog to check whether the file arrived.")));
      const body = new FormData(); body.append("file", file); request.send(body);
    });
  }
  async function runDataAction(action, file) {
    if (working() || state.pending || !state.dataProject) return;
    if (["save", "analyze"].includes(action) && !$("data-form").reportValidity()) return;
    if (action === "example" && (state.dataProject.dataset || !$("data-example-confirm").checked)) return;
    if (action === "upload") {
      if (!file || !file.name.toLowerCase().endsWith(".csv")) { dataMessage("Choose a CSV file.", true); $("data-file").value = ""; return; }
      if (file.size > (state.config?.max_upload_bytes || (state.config?.max_upload_mb || 200) * 1048576)) { dataMessage(`Choose a CSV file no larger than ${state.config?.max_upload_mb || 200} MB. For larger files, paste a Google Drive link in the conversation with access set to "Anyone with the link" and the role set to "Viewer".`, true); $("data-file").value = ""; return; }
    }
    state.dataBusy = true; dataMessage("", true); dataMessage(action === "analyze" ? "Saving details and running the audit and baseline…" : action === "upload" ? "Uploading the dataset…" : action === "example" ? "Loading the synthetic example…" : "Saving the data details…"); $("thinking-text").textContent = "Working on data and baseline checks…"; updateControls();
    try {
      let project;
      if (action === "example") project = await api(`${projectPath()}/example`, { method: "POST", body: JSON.stringify({ name: "materials" }) });
      else { await saveDataIfNeeded(); if (action === "analyze") project = await api(`${projectPath()}/analyze`, { method: "POST", body: "{}" }); else if (action === "upload") { $("data-progress-wrap").hidden = false; $("data-upload-progress").value = 0; $("data-upload-percent").textContent = "0%"; $("data-upload-state").textContent = "Uploading…"; project = await uploadDataFile(file); } }
      if (project) { renderDataForm(project); invalidateWorkflow(); if (state.conversation) { state.conversation.title = project.title; $("project-title").textContent = project.title || "New challenge"; } }
      dataMessage(action === "analyze" ? "Checks finished. Review the measured results below." : action === "upload" ? "CSV loaded. Select the target and review the design." : action === "example" ? "Synthetic materials data and demo metadata loaded. Review the design, then run checks." : "Data details saved.");
      await refreshWorkflow();
    } catch (error) { dataMessage("", false); dataMessage(error.message, true); }
    finally { state.dataBusy = false; $("data-file").value = ""; $("data-progress-wrap").hidden = true; updateControls(); }
  }
  function renderMessages(forceScroll = false) {
    const started = userCount() > 0 || state.pending?.action === "messages";
    const messages = [...(state.conversation?.messages || [])];
    const pendingVisibleInHistory = state.pending?.action === "messages" && messages.filter((message) => message.role === "user").slice(state.pending.before_user_count ?? userCount()).some((message) => message.content === state.pending.message);
    if (state.pending?.action === "messages" && !pendingVisibleInHistory) messages.push({ id: `pending:${state.pending.request_id}`, role: "user", content: state.pending.message, pending: true });
    const key = `${state.projectId}:${JSON.stringify(messages)}:${working()}`; $("welcome").hidden = started || messages.length > 0;
    if (key === state.messageKey) return; state.messageKey = key;
    const root = $("messages"); const transcript = $("transcript"); const nearBottom = transcript.scrollHeight - transcript.scrollTop - transcript.clientHeight < 120;
    root.replaceChildren();
    for (const message of messages) {
      if (!["user", "assistant"].includes(message.role)) continue;
      const block = element("article", `message ${message.role}`); const role = element("div", "message-role");
      if (message.role === "assistant") { const mark = element("img", "assistant-mark"); mark.src = "/static/bold-butterfly.svg"; mark.alt = ""; mark.width = 24; mark.height = 24; mark.setAttribute("aria-hidden", "true"); role.append(mark, document.createTextNode("BOLD AutoKaggle")); } else role.textContent = message.pending ? (working() ? "You · sending" : "You · awaiting confirmation") : "You";
      block.append(role, message.role === "user" ? element("div", "message-content", message.content) : markdown(message.content, "message-content")); root.append(block);
    }
    if (nearBottom || forceScroll) window.requestAnimationFrame(() => { transcript.scrollTop = transcript.scrollHeight; });
  }
  function renderQuestionWhy() {
    const why = state.conversation?.current_question?.why;
    const question = state.conversation?.interview?.next_question || state.conversation?.current_question?.text || "";
    const normalize = (text) => String(text).replace(/\s+/g, " ").trim().toLowerCase();
    $("question-hint").hidden = state.view !== "chat" || !why || normalize(question).includes(normalize(why));
    $("question-text").textContent = why ? `Why this matters: ${why}` : "";
  }
  function renderConversation({ scroll = false } = {}) {
    const conversation = state.conversation; if (!conversation) { renderChecklist(); updateControls(); return; }
    $("project-title").textContent = conversation.title || "New challenge"; document.title = `${conversation.title || "New challenge"} · BOLD AutoKaggle`;
    $("workspace-label").textContent = inRevision() ? "ORGANIZER REVIEW" : "RESEARCH INTERVIEW";
    $("mode-label").textContent = contactRequired() ? "Add your private correspondence email" : inRevision() ? `Review round ${conversation.review.round || 1} · earlier context kept` : conversation.mode === "model" ? "Agent interview · answers saved" : "Guided interview · rules mode";
    $("revision-banner").hidden = !inRevision();
    $("revision-heading").textContent = `Review round ${conversation.review?.round || 1}`;
    $("revision-detail").textContent = conversation.review?.previous_version ? `Based on version ${conversation.review.previous_version}. Your earlier answers are kept.` : "Your earlier answers are kept. Describe what you want to change.";
    const question = conversation.interview?.next_question || conversation.current_question?.text;
    $("opening-question").textContent = question || "Describe the situation, the current difficulty, and what you want to predict, explain, improve, or optimize.";
    renderQuestionWhy(); renderScopeCheckpoint();
    $("message-input").placeholder = inRevision() ? "Describe what you want to change and why…" : userCount() ? "Add an answer, a correction, or a detail…" : "We are studying… The difficulty is… We want to find out…";
    renderChecklist(); renderMessages(scroll); renderReview();
    if (conversation.readme) { $("readme-content").replaceChildren(markdown(conversation.readme)); $("readme-dot").hidden = state.view === "readme"; document.querySelector(".readme-toolbar p").textContent = conversation.phase === "draft" ? "Review the working draft and its required open details." : "Earlier working draft. Create it again to include your latest answers."; }
    else if (state.view === "readme") setView("chat");
    updateControls();
  }
  function setView(view) {
    if (view === "readme" && !state.conversation?.readme) return; if (view === "review" && !reviewAvailable()) return; state.view = view;
    $("chat-view").hidden = view !== "chat"; $("readme-view").hidden = view !== "readme"; $("review-view").hidden = view !== "review";
    $("chat-tab").setAttribute("aria-selected", String(view === "chat")); $("readme-tab").setAttribute("aria-selected", String(view === "readme"));
    $("chat-tab").tabIndex = view === "chat" ? 0 : -1; $("readme-tab").tabIndex = view === "readme" ? 0 : -1;
    $("review-tab").setAttribute("aria-selected", String(view === "review")); $("review-tab").tabIndex = view === "review" ? 0 : -1;
    if (view === "readme") { $("readme-dot").hidden = true; $("readme-scroll").scrollTop = 0; }
    renderQuestionWhy();
    renderContact();
    try { const url = new URL(window.location.href); if (view === "review") url.searchParams.set("view", "review"); else url.searchParams.delete("view"); window.history.replaceState(null, "", url); } catch (_) {}
  }
  async function refreshProjects() {
    const result = await api("/api/projects"); state.projects = result.projects || [];
  }
  function clearDeliveredCompose(request) {
    if (request.action === "messages" && $("message-input").value.trim() === String(request.message || "").trim()) { $("message-input").value = ""; rememberCompose(); }
  }
  async function pollWorking() {
    if (state.polling) return; state.polling = true; updateControls(); let failures = 0; let completed = false;
    try {
      while (state.conversation?.status === "working") {
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
        try { state.conversation = await api(base()); failures = 0; renderConversation({ scroll: true }); }
        catch (error) { failures += 1; if (failures >= 3) { showError("The status connection was interrupted. Reconnect to check the current request.", "Connection interrupted"); break; } }
      }
      completed = state.conversation?.status !== "working";
      // GET reports project activity, not acknowledgement of this tab's request.
      // Keep the pending payload and ID until its own POST returns successfully.
    } finally { state.polling = false; if (!completed && state.conversation) state.conversation = { ...state.conversation, status: "error", error: "The connection needs to be checked. The server may still be working.", can_retry: true }; updateControls(); }
  }
  async function openProject(id) {
    const requestedView = new URLSearchParams(window.location.search).get("view");
    rememberCompose(); state.contactError = null; state.projectUnavailable = false; $("organizer-email").value = ""; state.projectId = id; state.bypassDrafts = {}; state.scopeDrafts = {}; state.scopeDraftsLoaded = false; state.conversation = null; state.localError = null; state.dismissedError = null; state.pending = null; state.messageKey = ""; state.selectedTopic = null; state.selectedItem = null; state.knowledgeTopic = null; state.knowledgeQuestion = null; state.renderedKnowledgeTopic = null; state.checklistKey = ""; state.workflow = null; state.workflowError = null; state.workflowLoading = false; state.workflowUncertain = false; state.dataProject = null; state.dataDirty = false; state.dataSnapshot = ""; setView("chat");
    for (const name of ["summary-dialog", "data-dialog"]) if ($(name).open) $(name).close();
    $("message-input").value = "";
    state.conversation = await api(base());
    state.pending = loadPending(id); $("message-input").value = readStorage(draftKey(id)) || ""; writeStorage(LAST_PROJECT, id);
    renderConversation({ scroll: true }); if (state.conversation.status === "working") await pollWorking();
    await refreshWorkflow(); if (requestedView === "review" && reviewAvailable()) setView("review");
    try { const url = new URL(window.location.href); url.searchParams.set("project", id); window.history.replaceState(null, "", url); } catch (_) { /* Local storage still records the current conversation. */ }
  }
  function clearPrivateBrowserState() {
    try {
      const storage = window.localStorage;
      for (const key of Object.keys(storage)) {
        if (key === LAST_PROJECT || key.startsWith("autokaggle-chat-compose:") || key.startsWith("autokaggle-chat-pending:")) storage.removeItem(key);
      }
    } catch (_) { /* Sign-out also works when browser storage is unavailable. */ }
    state.projectId = null; state.conversation = null; state.projects = []; state.pending = null; state.workflow = null; state.dataProject = null; state.bypassDrafts = {}; state.scopeDrafts = {}; state.scopeDraftsLoaded = false;
    $("message-input").value = ""; $("organizer-email").value = "";
    document.querySelector(".shell").hidden = true;
    for (const id of ["summary-dialog", "data-dialog"]) if ($(id).open) $(id).close();
  }
  async function signOut() {
    if (state.signingOut || !state.config?.private_mode) return;
    state.signingOut = true; updateControls();
    try {
      const access = await api("/api/access");
      if (typeof access.csrf_token !== "string" || !access.csrf_token) throw new Error("Sign-out could not start. Reload this page, then try again.");
      const result = await api("/api/access/logout", { method: "POST", headers: { "X-CSRF-Token": access.csrf_token }, body: "{}" });
      if (result.redirect !== "/login") throw new Error("Sign-out could not be confirmed. Reload this page, then try again.");
      clearPrivateBrowserState(); writeStorage(SESSION_ENDED, String(Date.now())); window.location.replace("/login");
    } catch (error) { state.signingOut = false; showError(error.message, "Sign-out was not confirmed"); updateControls(); }
  }
  async function createProject() {
    if (state.config?.can_create_projects === false) throw new Error("Sign in with your email to create a challenge.");
    const project = await api("/api/projects", { method: "POST", body: JSON.stringify({ title: "New challenge" }) }); await openProject(project.id);
  }
  function showProjectError(error, heading) {
    if (!state.conversation && [401, 403, 404].includes(error.status)) {
      state.projectUnavailable = true;
      $("project-title").textContent = "Challenge unavailable";
      $("mode-label").textContent = "This account cannot open this challenge.";
      const action = state.config?.private_mode ? "Select Sign out to use another account." : "Check that the challenge link is correct.";
      const create = state.config?.can_create_projects !== false ? " Or select New challenge to start your own." : "";
      showError(`This link may belong to another account or may no longer be valid. ${action}${create}`, "Challenge unavailable");
      return;
    }
    showError(error.message, heading);
  }
  async function runNavigation(action) {
    if (working()) return; setBusy(true, "Opening the conversation…");
    try { await action(); } catch (error) { showProjectError(error, "Could not open the conversation"); }
    finally { setBusy(false); }
  }
  async function dispatch(action, message, recovered) {
    if (working() || !state.projectId || !state.conversation || contactRequired()) return;
    if (state.pending && !recovered) return;
    if (action === "continue" && !recovered && (state.conversation.interview?.can_continue !== true || state.conversation.review?.mode === "revision")) return;
    const request = recovered || { project_id: state.projectId, action, request_id: crypto.randomUUID(), ...(action === "messages" ? { message, before_user_count: userCount() } : {}) };
    rememberPending(request); state.localError = null; state.dismissedError = null; setView("chat");
    if (!recovered && request.action === "messages") { $("message-input").value = ""; rememberCompose(); }
    setBusy(true, request.action === "draft" ? "Writing your challenge README…" : "Thinking through your challenge…");
    window.requestAnimationFrame(() => { $("transcript").scrollTop = $("transcript").scrollHeight; });
    try {
      const payload = { request_id: request.request_id, ...(request.action === "messages" ? { message: request.message } : {}) };
      state.conversation = await api(`${base()}/${request.action}`, { method: "POST", body: JSON.stringify(payload) });
      clearDeliveredCompose(request); rememberPending(null); renderConversation({ scroll: true });
      if (state.conversation.status === "working") await pollWorking();
      if (request.action === "draft" && state.conversation.readme && state.conversation.status !== "error") setView("readme");
      await refreshWorkflow();
    } catch (error) {
      if (error.status && error.status >= 400 && error.status < 500 && ![408, 409, 429].includes(error.status)) { rememberPending(null); if (request.action === "messages" && !$("message-input").value) { $("message-input").value = request.message; rememberCompose(); } }
      showError(error.message, "This step was not confirmed");
      try { const current = await api(base()); state.conversation = current; renderConversation({ scroll: true }); if (current.status === "working") { state.localError = null; await pollWorking(); } } catch (_) { /* Keep the original request ID for a safe retry. */ }
    } finally { setBusy(false); }
  }
  async function retry() {
    if (working()) return;
    if (!state.conversation) { await runNavigation(async () => { if (state.projectId) await openProject(state.projectId); else await initializeProject(); }); return; }
    if (state.pending?.action === "scope") { await saveScope(state.pending.field, state.pending.remove, state.pending); return; }
    if (state.pending?.action === "bypass") { await saveBypass(state.pending.field, state.pending.requirement_id, state.pending.remove, state.pending); return; }
    if (state.pending) { await dispatch(state.pending.action, state.pending.message, state.pending); return; }
    await dispatch("retry");
  }
  function bind() {
    $("organizer-email-form").addEventListener("submit", (event) => { event.preventDefault(); saveOrganizerEmail(); });
    $("organizer-email").addEventListener("input", () => { if (state.contactError) { state.contactError = null; renderContact(); } });
    $("review-tab").addEventListener("click", () => setView("review"));
    $("start-revision").addEventListener("click", startRevision); $("revision-outputs").addEventListener("click", () => setView("review"));
    $("review-back-to-chat").addEventListener("click", () => setView("chat")); $("review-build").addEventListener("click", () => setView("readme"));
    $("review-link").addEventListener("click", (event) => { event.preventDefault(); setView("review"); });
    for (const id of ["review-website", "review-package", "review-submission"]) $(id).addEventListener("click", (event) => { if (working() || state.pending) event.preventDefault(); });
    $("message-input").addEventListener("input", () => { rememberCompose(); updateControls(); });
    $("message-input").addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); if (!$("send-message").disabled) $("message-form").requestSubmit(); } });
    $("message-form").addEventListener("submit", (event) => { event.preventDefault(); const text = $("message-input").value.trim(); if (text) dispatch("messages", text); });
    $("new-project").addEventListener("click", () => runNavigation(createProject));
    $("sign-out").addEventListener("click", signOut);
    window.addEventListener("storage", (event) => { if (event.key === SESSION_ENDED && event.newValue && state.config?.private_mode) { clearPrivateBrowserState(); window.location.replace("/login"); } });
    window.addEventListener("pageshow", (event) => { if (event.persisted && state.config?.private_mode) window.location.reload(); });
    $("build-workflow").addEventListener("click", () => runWorkflow()); $("refresh-workflow").addEventListener("click", refreshWorkflow); $("retry-notification").addEventListener("click", () => runWorkflow("notify"));
    $("download-package").addEventListener("click", (event) => { if (working() || state.pending) event.preventDefault(); });
    $("open-data").addEventListener("click", openData); $("data-workbench").addEventListener("click", openData); $("close-data").addEventListener("click", () => $("data-dialog").close()); $("reload-data").addEventListener("click", openData);
    $("data-form").addEventListener("submit", (event) => { event.preventDefault(); runDataAction("save"); }); $("data-form").addEventListener("input", markDataDirty);
    $("data-task").addEventListener("change", () => { dataMetrics(); markDataDirty(); }); $("data-split").addEventListener("change", () => { dataSplitFields(); markDataDirty(); }); $("data-target").addEventListener("change", () => { updateDataControls(); markDataDirty(); });
    $("data-example-confirm").addEventListener("change", updateDataControls); $("load-data-example").addEventListener("click", () => runDataAction("example"));
    $("save-data").addEventListener("click", () => runDataAction("save")); $("analyze-data").addEventListener("click", () => runDataAction("analyze")); $("data-file").addEventListener("change", (event) => runDataAction("upload", event.target.files?.[0]));
    $("continue-interview").addEventListener("click", () => dispatch("continue")); $("draft-continue-interview").addEventListener("click", () => dispatch("continue"));
    $("skip-question").addEventListener("click", () => dispatch("skip")); $("draft-readme").addEventListener("click", () => dispatch("draft")); $("retry-action").addEventListener("click", retry);
    $("dismiss-error").addEventListener("click", () => { state.dismissedError = `${$("error-heading").textContent}:${$("error-text").textContent}`; renderError(); });
    $("chat-tab").addEventListener("click", () => setView("chat")); $("readme-tab").addEventListener("click", () => setView("readme")); $("back-to-chat").addEventListener("click", () => { setView("chat"); $("message-input").focus(); });
    for (const id of ["chat-tab", "readme-tab", "review-tab"]) $(id).addEventListener("keydown", (event) => { if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return; event.preventDefault(); const views = ["chat", ...(state.conversation?.readme ? ["readme"] : []), ...(reviewAvailable() ? ["review"] : [])]; const current = views.indexOf(state.view); const index = event.key === "Home" ? 0 : event.key === "End" ? views.length - 1 : (current + (event.key === "ArrowRight" ? 1 : -1) + views.length) % views.length; setView(views[index]); $(`${views[index]}-tab`).focus(); });
    $("download-readme").addEventListener("click", () => { if (!state.conversation?.readme) return; const link = element("a"); link.href = `${base()}/readme.md`; link.download = "README.md"; document.body.append(link); link.click(); link.remove(); });
    $("readiness-details").addEventListener("click", () => showSummary()); $("draft-readiness-details").addEventListener("click", () => showSummary());
    $("checklist-toggle").addEventListener("click", () => showSummary()); $("close-summary").addEventListener("click", () => $("summary-dialog").close());
    $("answer-in-chat").addEventListener("click", () => { $("summary-dialog").close(); setView("chat"); const topic = topics.find((entry) => entry.id === state.selectedTopic); if (!$("message-input").value.trim() && topic) $("message-input").value = `About ${topic.label.toLowerCase()}, `; rememberCompose(); updateControls(); $("message-input").focus(); });
    for (const id of ["summary-dialog", "data-dialog"]) $(id).addEventListener("click", (event) => { if (event.target !== $(id)) return; const bounds = $(id).getBoundingClientRect(); if (event.clientX < bounds.left || event.clientY < bounds.top || event.clientX > bounds.right || event.clientY > bounds.bottom) $(id).close(); });
  }
  async function initializeProject() {
    const requested = new URLSearchParams(window.location.search).get("project");
    if (requested) { await openProject(requested); return; }
    await refreshProjects(); const saved = readStorage(LAST_PROJECT);
    if (saved && state.projects.some((project) => project.id === saved)) await openProject(saved);
    else if (state.projects.length) await openProject(state.projects[0].id);
    else if (state.config?.can_create_projects === false) window.location.replace("/login");
    else await createProject();
  }
  async function init() {
    bind(); renderChecklist(); setBusy(true, "Opening the conversation…");
    try { const config = await api("/api/config"); state.config = config; } catch (_) { /* Conversation mode is also returned in its state. */ }
    try { await initializeProject(); } catch (error) { showProjectError(error, "Could not connect to BOLD AutoKaggle"); }
    finally { setBusy(false); }
  }
  init();
})();
