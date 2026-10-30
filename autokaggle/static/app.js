/* BOLD AutoKaggle organizer workbench. Remote text is always rendered as text. */
"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const state = { project: null, config: null, busy: false, snapshot: "", adviceDirty: false, seenNotices: new Set() };
  const answerFields = { objective: "objective", prediction_unit: "prediction-unit", success_criterion: "success-criterion", data_origin: "data-origin", labels_public: "labels-public", rights: "rights", compute_budget: "compute-budget", token_budget: "token-budget" };
  const metricNames = { accuracy: "Accuracy", balanced_accuracy: "Balanced accuracy", roc_auc: "ROC AUC", rmse: "Root mean squared error", mae: "Mean absolute error" };
  const stageNames = { scope: "Frame the problem", scoping: "Frame the problem", problem: "Frame the problem", data: "Understand the data", audit: "Check the data and evaluation", analyze: "Check the data and evaluation", evaluation: "Design the evaluation", baseline: "Run the development trial", trial: "Run the development trial", review: "Review the challenge", complete: "Ready for your review", failed: "Needs attention", queued: "Starting the agent", start: "Starting the agent", package: "Prepare the packages" };

  function el(tag, className, content) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (content !== undefined && content !== null) node.textContent = String(content);
    return node;
  }
  function inlineText(parent, text) {
    const pattern = /(`[^`\n]+`|\*\*[^*\n]+\*\*|\[[^\]\n]+\]\(https?:\/\/[^)\s]+\))/g;
    let end = 0;
    for (const match of text.matchAll(pattern)) {
      parent.append(document.createTextNode(text.slice(end, match.index)));
      const value = match[0];
      if (value.startsWith("`")) parent.append(el("code", "", value.slice(1, -1)));
      else if (value.startsWith("**")) parent.append(el("strong", "", value.slice(2, -2)));
      else { const parts = value.match(/^\[([^\]]+)\]\((https?:\/\/[^)]+)\)$/); const link = el("a", "", parts[1]); link.href = parts[2]; link.rel = "noopener noreferrer"; link.target = "_blank"; parent.append(link); }
      end = match.index + value.length;
    }
    parent.append(document.createTextNode(text.slice(end)));
  }
  function markdown(text, title) {
    const container = el("div", "participant-brief");
    const lines = String(text || "").split(/\r?\n/); let paragraph = []; let list = null; let fenced = false; let codeLines = [];
    function flush() { if (paragraph.length) { const p = el("p"); inlineText(p, paragraph.join(" ")); container.append(p); paragraph = []; } }
    for (const line of lines) {
      if (/^\s*```/.test(line)) { flush(); list = null; if (fenced) { const pre = el("pre"); pre.append(el("code", "", codeLines.join("\n"))); container.append(pre); codeLines = []; } fenced = !fenced; continue; }
      if (fenced) { codeLines.push(line); continue; }
      if (!line.trim()) { flush(); list = null; continue; }
      const heading = line.match(/^(#{1,6})\s+(.+)$/);
      if (heading) { flush(); list = null; if (heading[1] === "#" && heading[2].trim() === String(title).trim()) continue; const h = el(`h${Math.min(4, Math.max(2, heading[1].length))}`); inlineText(h, heading[2]); container.append(h); continue; }
      const bullet = line.match(/^\s*(?:[-*]|\d+\.)\s+(.+)$/);
      if (bullet) { flush(); const tag = /^\s*\d+\./.test(line) ? "ol" : "ul"; if (!list || list.tagName.toLowerCase() !== tag) { list = el(tag); container.append(list); } const item = el("li"); inlineText(item, bullet[1]); list.append(item); continue; }
      list = null; paragraph.push(line.trim());
    }
    flush(); if (codeLines.length) { const pre = el("pre"); pre.append(el("code", "", codeLines.join("\n"))); container.append(pre); }
    return container;
  }
  function errorMessage(detail) {
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) return detail.map((item) => item.msg || item.message || "Invalid input").join("; ");
    return "The request could not be completed. Please try again.";
  }
  async function api(path, options = {}) {
    const response = await fetch(path, { credentials: "same-origin", ...options, headers: { ...(options.body ? { "Content-Type": "application/json" } : {}), ...options.headers } });
    const data = (response.headers.get("content-type") || "").includes("application/json") ? await response.json() : null;
    if (!response.ok) throw new Error(errorMessage(data?.detail));
    return data;
  }
  function notice(message, kind = "error", persistent = false) {
    const box = el("div", `notice ${kind}`);
    box.setAttribute("role", kind === "error" ? "alert" : "status");
    box.append(el("span", "", message));
    const close = el("button", "", "×"); close.type = "button"; close.setAttribute("aria-label", "Dismiss notice");
    close.addEventListener("click", () => box.remove()); box.append(close); $("notice-region").append(box);
    if (!persistent) window.setTimeout(() => box.remove(), kind === "error" ? 14000 : 6500);
  }
  function locked() { return state.busy || state.project?.harness?.status === "running"; }
  function updateControls() {
    const disabled = locked();
    document.querySelectorAll("#organizer-app button, #organizer-app input, #organizer-app textarea, #organizer-app select").forEach((node) => { node.disabled = disabled; });
    if (!disabled) {
      $("prepare-project").disabled = isDirty() || !$("acknowledge-review").checked || !state.project?.analysis || !!state.project.analysis.summary?.blockers || state.project.analysis.baseline?.status !== "complete";
      $("analyze-project").disabled = !state.project?.dataset;
      $("save-project").disabled = !isDirty();
      for (const id of ["target", "group-column", "time-column"]) $(id).disabled = !state.project?.dataset;
      document.querySelectorAll("#exclude-columns input").forEach((node) => { node.disabled = node.value === $("target").value; });
    }
    $("busy-status").hidden = !disabled; $("workspace").setAttribute("aria-busy", String(disabled));
  }
  function setBusy(busy, label = "Working…") { state.busy = busy; $("busy-text").textContent = label; updateControls(); }
  async function run(label, action) {
    if (locked()) return;
    setBusy(true, label);
    try { await action(); } catch (error) { notice(error.message || "The request failed. Please try again."); }
    finally { setBusy(false); }
  }
  function collectForm() {
    const answers = {};
    for (const [key, id] of Object.entries(answerFields)) answers[key] = $(id).value.trim();
    return { title: $("title").value.trim(), brief: $("brief").value.trim(), answers, design: { target: $("target").value, task: $("task").value, metric: $("metric").value, split: $("split").value, group_column: $("group-column").value, time_column: $("time-column").value, exclude_columns: [...document.querySelectorAll("#exclude-columns input:checked")].map((node) => node.value), test_fraction: 0.2 } };
  }
  function isDirty() { return !!state.project && JSON.stringify(collectForm()) !== state.snapshot; }
  function updateDirty() {
    const dirty = isDirty(); $("save-state").textContent = dirty ? "Unsaved changes" : "Saved"; $("save-state").classList.toggle("unsaved", dirty);
    if (dirty) { $("packages").hidden = true; $("acknowledge-review").checked = false; $("prepare-help").textContent = "Save changes and review the updated design before preparing packages."; }
    if (state.project && state.adviceDirty !== dirty) { renderAdvice(state.project.advice || [], state.project.revision, dirty); state.adviceDirty = dirty; }
    updateControls();
  }
  async function saveIfNeeded() {
    if (!state.project || !isDirty()) return;
    state.project = await api(`/api/projects/${encodeURIComponent(state.project.id)}`, { method: "PATCH", body: JSON.stringify(collectForm()) }); renderProject();
  }
  async function refreshProjects() {
    const data = await api("/api/projects"); const select = $("project-switch"); select.replaceChildren(new Option("Recent challenges", ""));
    for (const project of data.projects || []) select.append(new Option(project.title || "Untitled challenge", project.id));
    select.value = state.project?.id || ""; return data.projects || [];
  }
  function optionList(id, columns, value, placeholder) {
    const select = $(id); select.replaceChildren(new Option(placeholder, ""));
    for (const column of columns) select.append(new Option(column.name, column.name)); select.value = value || "";
  }
  function updateMetrics(value) {
    const options = $("task").value === "regression" ? ["rmse", "mae"] : ["accuracy", "balanced_accuracy", "roc_auc"];
    $("metric").replaceChildren(...options.map((metric) => new Option(metricNames[metric], metric))); $("metric").value = options.includes(value) ? value : options[0];
  }
  function updateSplitFields() {
    const split = $("split").value; $("group-field").hidden = split !== "group"; $("time-field").hidden = split !== "time";
    $("split-help").textContent = { random: "Use random rows only when observations are independent.", group: "Separate related observations to test generalization to new groups.", time: "Use the past for training and later observations for the hidden test." }[split];
  }
  function renderChecklist(checklist) {
    const list = $("checklist"); list.replaceChildren(); const complete = checklist.filter((item) => item.status === "complete").length;
    $("checklist-count").textContent = `${complete} / ${checklist.length} complete`; $("checklist-progress").style.width = `${checklist.length ? complete / checklist.length * 100 : 0}%`;
    for (const item of checklist) {
      const li = el("li", ["complete", "attention", "missing"].includes(item.status) ? item.status : "missing");
      const icon = el("span", "check-icon", item.status === "complete" ? "✓" : item.status === "attention" ? "!" : ""); icon.setAttribute("aria-hidden", "true");
      const copy = el("span", "", item.label); copy.append(el("small", "", item.detail)); li.append(icon, copy); list.append(li);
    }
  }
  function number(value) { return typeof value === "number" && Number.isFinite(value) ? value.toLocaleString() : "—"; }
  function bytes(value) { if (!Number.isFinite(value)) return ""; return value >= 1048576 ? `${(value / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(value / 1024))} KB`; }
  function score(value) { return typeof value === "number" && Number.isFinite(value) ? value.toLocaleString(undefined, { maximumFractionDigits: 4 }) : "—"; }
  function renderDataset(dataset) {
    const target = $("dataset-summary"); target.replaceChildren(); target.hidden = !dataset; $("upload-heading").textContent = dataset ? "Replace the dataset" : "Add a dataset"; if (!dataset) return;
    const card = el("div", "dataset-card"); const heading = el("div", "dataset-card-header"); heading.append(el("strong", "dataset-filename", dataset.filename), el("span", "status-badge", "CSV loaded")); card.append(heading);
    const stats = el("div", "dataset-stats");
    for (const [value, label] of [[number(dataset.rows), "rows"], [number(dataset.columns.length), "columns"], [bytes(dataset.size_bytes), ""]]) { const stat = el("span"); stat.append(el("strong", "", value), document.createTextNode(` ${label}`)); stats.append(stat); } card.append(stats);
    const details = el("details", "sample-details"); details.append(el("summary", "", "Inspect column summary")); const wrapper = el("div", "columns-table-wrap"); const table = el("table", "columns-table");
    const head = el("thead"); const row = el("tr"); for (const text of ["Column", "Type", "Missing", "Unique"]) { const cell = el("th", "", text); cell.scope = "col"; row.append(cell); } head.append(row); table.append(head);
    const body = el("tbody"); for (const column of dataset.columns) { const tr = el("tr"); for (const value of [column.name, column.dtype, number(column.missing), number(column.unique)]) tr.append(el("td", "", value)); body.append(tr); } table.append(body); wrapper.append(table); details.append(wrapper); card.append(details); target.append(card);
  }
  function renderColumns(project) {
    const columns = project.dataset?.columns || []; const design = project.design || {};
    optionList("target", columns, design.target, columns.length ? "Select a target" : "Add a dataset first"); optionList("group-column", columns, design.group_column, "Select a column"); optionList("time-column", columns, design.time_column, "Select a column");
    const excluded = new Set(design.exclude_columns || []); const container = $("exclude-columns"); container.replaceChildren(); if (!columns.length) container.append(el("span", "muted", "Add a dataset to select columns."));
    for (const [index, column] of columns.entries()) { const label = el("label", "column-option"); const check = el("input"); check.type = "checkbox"; check.value = column.name; check.id = `exclude-${index}`; check.checked = excluded.has(column.name) && column.name !== design.target; label.htmlFor = check.id; label.append(check, document.createTextNode(column.name)); container.append(label); }
  }
  function renderAnalysis(analysis) {
    $("analysis-empty").hidden = !!analysis; $("analysis-results").hidden = !analysis; if (!analysis) return;
    $("audit-summary").replaceChildren(); const checks = analysis.checks || [];
    for (const [key, label, severity] of [["blockers", "Blocking checks", "blocker"], ["warnings", "Need review", "warning"], ["passed", "Checks passed", "pass"]]) { const value = analysis.summary?.[key] ?? checks.filter((item) => item.severity === severity).length; const node = el("div", `audit-stat ${value && key !== "passed" ? `has-${key}` : ""}`); node.append(el("strong", "", number(value)), el("span", "", label)); $("audit-summary").append(node); }
    const baselineTarget = $("baseline-result"); baselineTarget.replaceChildren();
    if (analysis.baseline) {
      const baseline = analysis.baseline; const card = el("div", "baseline-card"); const heading = el("div", "baseline-heading"); heading.append(el("h3", "", "Development baseline"), el("span", "", metricNames[baseline.metric] || baseline.metric || "Not run")); card.append(heading);
      if (typeof baseline.score === "number") { const values = el("div", "baseline-values"); for (const [label, value, cls] of [["Simple model", baseline.score, ""], ["Dummy reference", baseline.dummy_score, "reference"]]) { const stat = el("div", `baseline-value ${cls}`); stat.append(el("small", "", label), el("strong", "", score(value))); values.append(stat); } card.append(values); card.append(el("p", "", `Measured on ${number(baseline.validation_rows)} validation rows within the training set. The final hidden test is not scored here.`)); }
      if (baseline.detail) card.append(el("p", "", baseline.detail)); if (typeof baseline.score !== "number" && !baseline.detail) card.append(el("p", "", "The baseline did not run. Review the checks below.")); baselineTarget.append(card);
    }
    $("split-result").replaceChildren(); if (analysis.split) { const split = el("div", "split-result"); for (const [count, label] of [[analysis.split.train_rows, "training rows"], [analysis.split.test_rows, "hidden test rows"]]) { const span = el("span"); span.append(el("strong", "", number(count)), document.createTextNode(` ${label}`)); split.append(span); } $("split-result").append(split); }
    $("audit-checks").replaceChildren();
    for (const [severity, name] of [["blocker", "Resolve before release"], ["warning", "Review before release"], ["pass", "Checks passed"]]) {
      const items = checks.filter((item) => item.severity === severity); if (!items.length) continue; const group = el(severity === "pass" ? "details" : "div", `check-group ${severity}`); const title = el("h3", "", name); title.append(el("span", "", `${items.length}`)); if (severity === "pass") { const summary = el("summary"); summary.append(title); group.append(summary); } else group.append(title);
      for (const item of items) { const card = el("article", `check-card ${severity}`); card.append(el("h4", "", item.title), el("p", "", item.detail)); if (item.action) { const action = el("p", "check-action"); action.append(el("strong", "", "Next step: "), document.createTextNode(item.action)); card.append(action); } group.append(card); } $("audit-checks").append(group);
    }
    $("analysis-limitations").replaceChildren(); if (analysis.limitations?.length) { const details = el("details", "analysis-limitations"); details.append(el("summary", "", "What these checks do not establish")); const list = el("ul"); for (const item of analysis.limitations) list.append(el("li", "", item)); details.append(list); $("analysis-limitations").append(details); }
  }
  function adviceNode(item) {
    const box = el("article", "advice-item"); const meta = el("div", "advice-item-meta"); meta.append(el("strong", "", item.kind === "review" ? "Design review" : "Next step"), el("span", "", item.mode === "model" ? "Model advice" : "Rules advice")); box.append(meta);
    const questions = Array.isArray(item.next_questions) ? item.next_questions.filter((question) => typeof question === "string" && question.trim()).slice(0, 3) : [];
    if (questions.length) { const section = el("section", "advice-questions"); section.append(el("h3", "", "Next questions")); const list = el("ol"); for (const question of questions) list.append(el("li", "", question)); section.append(list); box.append(section); }
    box.append(el("div", "advice-body", typeof item.content === "string" ? item.content : JSON.stringify(item.content, null, 2)));
    const labels = { objective: "scientific objective", prediction_unit: "prediction unit", success_criterion: "useful result", compute_budget: "compute estimate", token_budget: "token estimate", target: "target column", task: "prediction task", metric: "evaluation metric", split: "holdout strategy", group_column: "group column", time_column: "time column" };
    const fields = [...new Set((Array.isArray(item.applied) ? item.applied : []).map((update) => update.field).filter((field) => typeof field === "string"))];
    if (fields.length) box.append(el("p", "advice-applied", `Filled from your brief: ${fields.map((field) => labels[field] || field.replaceAll("_", " ")).join(", ")}.`));
    return box;
  }
  function renderAdvice(advice, revision, dirty = false) {
    const container = $("advice-content"); container.replaceChildren(); if (!advice.length) { const empty = el("div", "advice-empty"); empty.append(el("span", "eyebrow", "A USEFUL STARTING POINT"), el("p", "", "What must a model predict, and what would that prediction change for a scientist?"), el("span", "", "Write the problem in your own words. The adviser can help make it precise.")); container.append(empty); return; }
    const latest = advice[advice.length - 1]; const current = !dirty && latest.revision !== undefined && latest.revision === revision;
    if (current) container.append(adviceNode(latest));
    else container.append(el("p", "advice-outdated", dirty ? "The design has unsaved changes. Save them and request a new review." : "The design has changed since this advice. Request a new review of the current design."));
    const history = current ? advice.slice(0, -1) : advice;
    if (history.length) { const details = el("details", "advice-history"); details.append(el("summary", "", current ? `${history.length} earlier ${history.length === 1 ? "note" : "notes"}` : "Advice from an earlier design")); for (const item of history.slice().reverse()) details.append(adviceNode(item)); container.append(details); }
  }
  function renderHarness(project) {
    const harness = project.harness; $("agent-progress").hidden = !harness || harness.status === "idle"; if (!harness) return;
    const status = { running: "Running", complete: "Complete", failed: "Needs attention", idle: "Ready" }[harness.status] || harness.status; const stage = stageNames[harness.stage] || harness.stage || "Ready";
    $("agent-status").textContent = status; $("agent-status").classList.toggle("warning", harness.status === "failed"); $("agent-stage").textContent = harness.status === "complete" ? "Agent pass complete — review the evidence below" : harness.status === "failed" ? (harness.error || "The run stopped. Review the activity below.") : stage;
    $("agent-events").replaceChildren();
    for (const event of project.events || []) { const item = el("li", `agent-event ${["complete", "failed", "running", "warning", "started"].includes(event.status) ? event.status : ""}`); const marker = el("span", "event-marker", event.status === "failed" ? "!" : ["complete", "completed", "pass"].includes(event.status) ? "✓" : "·"); marker.setAttribute("aria-hidden", "true"); const copy = el("div"); copy.append(el("strong", "", stageNames[event.stage] || event.stage), el("p", "", event.detail)); item.append(marker, copy); $("agent-events").append(item); }
    if (harness.status === "running") $("busy-text").textContent = `Onboarding agent: ${stage.toLowerCase()}…`;
  }
  function renderProject() {
    const project = state.project; if (!project) return; $("welcome").hidden = true; $("workspace").hidden = false;
    $("workspace-title").textContent = project.title || "Untitled challenge"; document.title = `${project.title || "Untitled challenge"} · BOLD AutoKaggle`; $("title").value = project.title || ""; $("brief").value = project.brief || "";
    for (const [key, id] of Object.entries(answerFields)) $(id).value = project.answers?.[key] || (["data_origin", "labels_public", "rights"].includes(key) ? "unknown" : "");
    $("task").value = project.design?.task || "classification"; updateMetrics(project.design?.metric); $("split").value = project.design?.split || "random"; updateSplitFields(); renderColumns(project);
    renderChecklist(project.checklist || []); renderDataset(project.dataset); renderAnalysis(project.analysis); renderAdvice(project.advice || [], project.revision); state.adviceDirty = false; renderHarness(project);
    $("packages").hidden = !project.prepared; $("acknowledge-review").checked = false; $("prepare-help").textContent = !project.analysis ? "Run the trial and review its results before preparing packages." : project.analysis.summary?.blockers ? "Resolve the blocking checks and rerun the trial before preparing packages." : project.analysis.baseline?.status !== "complete" ? "Complete the development baseline before preparing packages." : "Complete the review checkbox to prepare. Blocking checks must pass.";
    const root = `/api/projects/${encodeURIComponent(project.id)}`; $("brief-download").href = `${root}/brief.md`; $("researcher-download").href = `${root}/download/researcher`; $("organizer-download").href = `${root}/download/organizer`;
    state.snapshot = JSON.stringify(collectForm()); updateDirty(); try { window.localStorage.setItem("autokaggle-project", project.id); } catch (_) { /* Optional convenience. */ }
    for (const item of project.notices || []) { const text = typeof item === "string" ? item : item.message || item.detail || JSON.stringify(item); const key = `${project.id}:${text}`; if (!state.seenNotices.has(key)) { state.seenNotices.add(key); notice(text, "warning", true); } }
  }
  async function newProject(example) {
    await saveIfNeeded(); state.project = await api("/api/projects", { method: "POST", body: JSON.stringify({ title: "Untitled challenge", brief: "" }) }); renderProject();
    if (example) { state.project = await api(`/api/projects/${encodeURIComponent(state.project.id)}/example`, { method: "POST", body: JSON.stringify({ name: example }) }); renderProject(); }
    await refreshProjects(); window.scrollTo({ top: 0, behavior: "smooth" });
  }
  async function actOnProject(endpoint, payload = {}) { await saveIfNeeded(); state.project = await api(`/api/projects/${encodeURIComponent(state.project.id)}/${endpoint}`, { method: "POST", body: JSON.stringify(payload) }); renderProject(); await refreshProjects(); }
  async function pollHarness() {
    let failures = 0;
    while (state.project?.harness?.status === "running") {
      await new Promise((resolve) => window.setTimeout(resolve, 1000));
      try { state.project = await api(`/api/projects/${encodeURIComponent(state.project.id)}`); renderProject(); failures = 0; }
      catch (error) { failures += 1; if (failures >= 3) { notice("The agent status connection was interrupted. Reload the page to reconnect. The server may still be working.", "error", true); break; } }
    }
    await refreshProjects();
  }
  function upload(file) {
    if (!file || locked()) return; const limit = state.config?.max_upload_mb || 200;
    if (!file.name.toLowerCase().endsWith(".csv")) { notice("Choose a CSV file."); return; } if (file.size > (state.config?.max_upload_bytes || limit * 1024 * 1024)) { notice(`Choose a CSV file no larger than ${limit} MB. For larger files, paste a Google Drive link in the interview with access set to "Anyone with the link" and the role set to "Viewer".`); return; }
    run("Uploading and checking the dataset…", async () => {
      await saveIfNeeded(); $("upload-progress-wrap").hidden = false; $("upload-progress").value = 0; $("upload-percent").textContent = "0%"; $("upload-status").textContent = "Uploading dataset…";
      try {
        state.project = await new Promise((resolve, reject) => {
          const request = new XMLHttpRequest(); request.open("POST", `/api/projects/${encodeURIComponent(state.project.id)}/dataset`); request.responseType = "json"; request.timeout = 30 * 60 * 1000;
          request.upload.addEventListener("progress", (event) => { if (!event.lengthComputable) return; const percent = Math.round(event.loaded / event.total * 100); $("upload-progress").value = percent; $("upload-percent").textContent = `${percent}%`; if (percent === 100) $("upload-status").textContent = "Upload complete. Reading the columns…"; });
          request.addEventListener("load", () => { if (request.status >= 200 && request.status < 300 && request.response) resolve(request.response); else reject(new Error(errorMessage(request.response?.detail))); });
          request.addEventListener("error", () => reject(new Error("The upload connection failed. Please try again."))); request.addEventListener("timeout", () => reject(new Error("The upload took too long. Please try again."))); const body = new FormData(); body.append("file", file); request.send(body);
        });
        renderProject(); notice("Dataset loaded. Select the target and review the evaluation design.", "success");
      } finally { $("upload-progress-wrap").hidden = true; $("dataset-file").value = ""; }
    });
  }
  function bindOrganizer() {
    document.querySelector(".readiness").open = window.innerWidth > 720;
    document.querySelectorAll(".stage-link").forEach((link, index) => link.setAttribute("aria-label", `${index + 1}. ${["Frame the problem", "Understand the data", "Design the evaluation", "Run a trial", "Review and package"][index]}`));
    $("challenge-form").addEventListener("submit", (event) => event.preventDefault()); $("challenge-form").addEventListener("input", updateDirty); $("challenge-form").addEventListener("change", updateDirty);
    $("task").addEventListener("change", () => { updateMetrics($("metric").value); updateDirty(); }); $("split").addEventListener("change", () => { updateSplitFields(); updateDirty(); });
    $("target").addEventListener("change", () => { for (const check of document.querySelectorAll("#exclude-columns input")) if (check.value === $("target").value) check.checked = false; updateDirty(); });
    for (const id of ["new-project", "start-project"]) $(id).addEventListener("click", () => run("Creating a challenge…", () => newProject()));
    document.querySelectorAll("[data-example]").forEach((button) => button.addEventListener("click", () => run("Loading the synthetic example…", () => newProject(button.dataset.example))));
    $("save-project").addEventListener("click", () => run("Saving your changes…", async () => { await saveIfNeeded(); await refreshProjects(); notice("Changes saved.", "success"); }));
    $("project-switch").addEventListener("change", () => { const id = $("project-switch").value; if (!id) return; run("Opening the challenge…", async () => { await saveIfNeeded(); state.project = await api(`/api/projects/${encodeURIComponent(id)}`); renderProject(); if (state.project.harness?.status === "running") await pollHarness(); }); });
    $("analyze-project").addEventListener("click", () => run("Running data checks and the development baseline…", async () => { await actOnProject("analyze"); $("trial").scrollIntoView({ behavior: "smooth", block: "start" }); }));
    $("advise-project").addEventListener("click", () => run("Preparing focused advice…", () => actOnProject("advise", { kind: "conversation" })));
    $("review-project").addEventListener("click", () => run("Reviewing the challenge design…", async () => { await actOnProject("advise", { kind: "review" }); if (window.innerWidth < 980) document.querySelector(".adviser-column").scrollIntoView({ behavior: "smooth", block: "start" }); }));
    $("run-agent").addEventListener("click", () => run("Starting the onboarding agent…", async () => { await actOnProject("run"); await pollHarness(); if (state.project.harness?.status === "complete") notice("The agent pass is complete. Review the evidence and remaining questions.", "success"); }));
    $("acknowledge-review").addEventListener("change", updateControls);
    $("prepare-project").addEventListener("click", () => { if (!$("acknowledge-review").checked) return; run("Preparing the challenge packages…", async () => { await actOnProject("prepare", { acknowledge_review: true }); $("packages").scrollIntoView({ behavior: "smooth", block: "nearest" }); }); });
    $("brief-download").addEventListener("click", (event) => { event.preventDefault(); run("Saving the challenge brief…", async () => { await saveIfNeeded(); window.location.assign(`/api/projects/${encodeURIComponent(state.project.id)}/brief.md`); }); });
    $("participant-link").addEventListener("click", () => run("Opening the participant preview…", async () => { const link = await api(`/api/projects/${encodeURIComponent(state.project.id)}/participant-link`); if (typeof link.url !== "string" || !/^\/challenge\/[a-zA-Z0-9_-]+$/.test(link.url)) throw new Error("The participant link is not available."); window.location.assign(link.url); }));
    $("dataset-file").addEventListener("change", (event) => upload(event.target.files[0]));
    $("upload-box").addEventListener("dragover", (event) => { event.preventDefault(); if (!locked()) $("upload-box").classList.add("dragover"); }); $("upload-box").addEventListener("dragleave", () => $("upload-box").classList.remove("dragover"));
    $("upload-box").addEventListener("drop", (event) => { event.preventDefault(); $("upload-box").classList.remove("dragover"); if (event.dataTransfer.files.length > 1) notice("Choose one CSV file at a time."); else upload(event.dataTransfer.files[0]); });
    window.addEventListener("beforeunload", (event) => { if (isDirty()) { event.preventDefault(); event.returnValue = ""; } });
    if ("IntersectionObserver" in window) { const observer = new IntersectionObserver((entries) => { for (const entry of entries) if (entry.isIntersecting) document.querySelectorAll(".stage-link").forEach((link) => link.classList.toggle("active", link.hash === `#${entry.target.id}`)); }, { rootMargin: "-8% 0px -65% 0px", threshold: 0 }); for (const id of ["problem", "data", "evaluation", "trial", "review"]) observer.observe($(id)); }
  }
  async function participant(token) {
    $("organizer-app").hidden = true; $("participant-app").hidden = false; document.querySelector(".skip-link").href = "#participant-app"; const container = $("participant-app"); container.append(el("p", "muted", "Loading the challenge…"));
    try {
      const challenge = await api(`/api/challenges/${encodeURIComponent(token)}`); container.replaceChildren(); document.title = `${challenge.title} · BOLD AutoKaggle`; const brand = el("div", "brand"); const mark = el("img", "brand-mark"); mark.src = "/static/bold-butterfly.svg"; mark.alt = ""; mark.width = 40; mark.height = 40; brand.append(mark, document.createTextNode("BOLD AutoKaggle")); container.append(brand);
      const hero = el("section", "participant-hero"); hero.append(el("span", "eyebrow", "RESEARCH CHALLENGE"), el("h1", "", challenge.title), markdown(challenge.brief, challenge.title));
      const stats = el("div", "participant-stats"); for (const [label, value] of [["Training observations", number(challenge.train_rows)], ["Evaluation metric", metricNames[challenge.metric] || challenge.metric]]) { const stat = el("div"); stat.append(el("span", "", label), el("strong", "", value)); stats.append(stat); } hero.append(stats);
      const download = el("section", "participant-download"); const copy = el("div"); copy.append(el("h2", "", "Start with the training data"), el("p", "", "Download the dataset and challenge instructions.")); download.append(copy);
      const link = el("a", "button button-primary", "Download training package ↓"); link.href = `/api/challenges/${encodeURIComponent(token)}/download`; download.append(link); hero.append(download); container.append(hero);
      if (challenge.limitations?.length) { const note = el("div", "participant-limitations"); note.append(el("strong", "", "Challenge notes")); const list = el("ul"); for (const item of challenge.limitations) list.append(el("li", "", item)); note.append(list); container.append(note); }
    } catch (error) { container.replaceChildren(); const box = el("div", "participant-error"); box.append(el("span", "eyebrow", "BOLD AUTOKAGGLE"), el("h1", "", "This challenge is not available"), el("p", "", error.message)); container.append(box); }
  }
  async function init() {
    const match = window.location.pathname.match(/^\/challenge\/([^/]+)\/?$/); if (match) { await participant(match[1]); return; }
    bindOrganizer(); setBusy(true, "Opening the workbench…");
    try {
      const results = await Promise.allSettled([api("/api/config"), refreshProjects()]);
      if (results[0].status === "fulfilled") { state.config = results[0].value; $("adviser-mode").textContent = state.config.mode === "model" ? `${state.config.model} · Model connected` : "Rules mode · No model configured"; $("upload-help").textContent = `CSV format · up to ${state.config.max_upload_mb || 200} MB`; } else { $("adviser-mode").textContent = "Adviser status unavailable"; notice(results[0].reason.message); }
      if (results[1].status === "fulfilled" && results[1].value.length) {
        const projects = results[1].value; let saved; try { saved = window.localStorage.getItem("autokaggle-project"); } catch (_) { /* Optional. */ }
        const requested = new URLSearchParams(window.location.search).get("project");
        const id = projects.some((item) => item.id === requested) ? requested : projects.some((item) => item.id === saved) ? saved : projects[0].id; state.project = await api(`/api/projects/${encodeURIComponent(id)}`); renderProject(); $("project-switch").value = id; if (state.project.harness?.status === "running") await pollHarness();
      } else if (results[1].status === "rejected") notice(results[1].reason.message);
    } catch (error) { notice(error.message); } finally { setBusy(false); }
  }
  init();
})();
