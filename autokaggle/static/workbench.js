"use strict";
(() => {
  const $ = id => document.getElementById(id);
  const id = new URLSearchParams(location.search).get("project");
  const interview = id ? "/?project=" + encodeURIComponent(id) : "/";
  const root = "/api/projects/" + encodeURIComponent(id || "");
  const canonical = "/workbench?project=" + encodeURIComponent(id || "") + "&view=review";
  const state = { data: null, loading: false, busy: false, auth: false, retryId: null, generation: 0 };
  const tabNames = ["overview", "definition", "checks", "attempts"];
  const node = (tag, text, className) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = String(text); if (className) n.className = className; return n; };
  $("interview-link").href = interview;
  function notice(text, kind = "") { $("notice").textContent = text; $("notice").className = "notice " + kind; }
  function controls() {
    $("refresh").disabled = state.loading || state.busy;
    const c = state.data?.conversation;
    $("request-changes").disabled = !c || state.loading || state.busy || state.auth || c.status !== "idle" || !!c.storage?.required || !!c.contact_required || (!c.readme && c.review?.mode !== "revision");
    $("request-changes").textContent = state.busy ? "Opening the review agent…" : c?.review?.mode === "revision" && c.review.status !== "draft_ready" ? "Continue with the review agent →" : "Discuss changes with the agent →";
  }
  async function api(url, options = {}) {
    const response = await fetch(url, { credentials: "same-origin", cache: "no-store", signal: AbortSignal.timeout(options.method ? 150000 : 20000), ...options });
    const result = await response.json();
    if (!response.ok) { const e = new Error(typeof result.detail === "string" ? result.detail : `Request failed (${response.status}). Try again.`); e.status = response.status; throw e; }
    return result;
  }
  async function failure(error) {
    if ([401, 403, 404].includes(error.status)) clearPrivate();
    if (error.status === 401 || error.status === 404) {
      try { const access = await api("/api/access"); state.auth = access.auth_kind === "anonymous"; } catch (_) { state.auth = error.status === 401; }
      if (state.auth) { $("sign-in").hidden = false; $("sign-in").href = "/login?next=" + encodeURIComponent(canonical); notice("Sign in again to reopen this review. Your saved work is retained.", "error"); return; }
    }
    notice(error.status === 428 ? "Review data storage in the agent before requesting changes." : error.message || "The connection stopped. Try again.", "error");
  }
  function clearPrivate() {
    state.generation += 1; state.data = null; state.loading = false;
    $("challenge-title").textContent = "Review unavailable"; $("version").textContent = "";
    document.title = "Review workbench · BOLD AutoKaggle";
    for (const name of ["setup-summary", "first-result", "definition", "checks", "attempts"]) $(name).replaceChildren();
    for (const kind of ["website", "package", "submission"]) { $(kind + "-link").hidden = true; $(kind + "-link").removeAttribute("href"); $(kind + "-state").textContent = "Sign in to check availability."; }
  }
  function safeLink(value) {
    if (typeof value !== "string") return null;
    try { const url = new URL(value, location.origin); return url.origin === location.origin && !url.username && !url.password && url.pathname.startsWith(root + "/workflow/") ? url.pathname + url.search + url.hash : null; } catch (_) { return null; }
  }
  function pair(list, label, value) { list.append(node("dt", label), node("dd", value === undefined || value === null || value === "" ? "Not recorded" : value)); }
  function record(title, text, status) {
    const row = node("article", undefined, "record"); row.append(node("h3", title));
    if (status) row.append(node("span", status.replaceAll("_", " "), "status" + (["pass", "scored", "recorded", "answered"].includes(status) ? "" : " warning")));
    row.append(node("p", text || "No detail recorded.")); return row;
  }
  function render() {
    const { project, conversation: c, workflow: w, attempts } = state.data;
    $("challenge-title").textContent = project.title || "Your challenge";
    document.title = `${project.title || "Your challenge"} · Review workbench`;
    $("version").textContent = "Version " + w.version; $("version").title = "Version " + w.version;
    const stale = w.status === "stale", summary = {
      ready_for_review: "The required build checks passed. Inspect this private draft before requesting changes.",
      awaiting_approval: "Waiting for administrator approval. You can inspect your files; no review email has been sent yet.",
      needs_changes: "The first version has open checks. Review them before treating the challenge as ready.",
      draft: "Draft files are available. Some checks are still pending.",
      stale: "This package is out of date. Return to the agent and build it again before downloading or testing it."
    };
    notice(summary[w.status] || "Review the saved version and its open checks.", w.status === "ready_for_review" ? "" : "warning");
    for (const [kind, value] of [["website", w.website_url], ["package", w.download_url], ["submission", w.submission_url]]) {
      const link = $(kind + "-link"), target = !stale && safeLink(value);
      link.hidden = !target; if (target) link.href = target; else link.removeAttribute("href");
      $(kind + "-state").textContent = target ? "Private draft · version " + w.version : stale ? "Rebuild required." : "Not available in this draft.";
    }
    const setup = $("setup-summary"); setup.replaceChildren();
    const environment = c.setup?.competition_type === "environment";
    pair(setup, "Submission", { prediction: "Prediction file", code: "Code on hidden inputs", environment: "Environment policy repository" }[c.setup?.competition_type]);
    const metricLabels = { accuracy: "Accuracy", balanced_accuracy: "Balanced accuracy", roc_auc: "ROC AUC", mae: "Mean absolute error", rmse: "Root mean squared error" };
    pair(setup, "Metric", environment ? "Success rate and mean score" : metricLabels[project.design?.metric] || project.design?.metric);
    pair(setup, "Target", environment ? "Episode outcomes" : project.design?.target);
    pair(setup, "Evaluation split", environment ? "Reserved evaluation seeds" : ({ random: "Random rows", group: "Grouped samples", time: "Chronological" }[project.design?.split] || project.design?.split));
    pair(setup, "Daily allowance", c.setup?.submissions_confirmed ? c.setup.daily_submission_limit : "Not confirmed");
    const first = $("first-result"), result = w.first_result; first.replaceChildren();
    if (result) {
      const values = node("dl"); pair(values, "Metric", metricLabels[result.metric] || result.metric); pair(values, "Score", result.score); first.append(values);
      first.append(node("p", result.kind === "environment_mechanism_test" ? "A constant policy was tested in a built-in toy environment. The challenge environment and submitted policy were not run." : "This is a submission pipeline check on training-derived validation. It is separate from a reproduced scientific baseline or a final test score."));
    } else first.append(node("p", "No measured first-test result has been recorded."));
    const definition = $("definition"); definition.replaceChildren();
    for (const item of c.checklist || []) {
      if (item.id === "organizer" || item.owner === "agent") continue;
      const section = node("details", undefined, "record"); section.append(node("summary", item.label));
      section.append(node("p", item.value || "No researcher answer recorded."));
      for (const requirement of item.requirements || []) {
        const row = record(requirement.label, requirement.value || requirement.reason || requirement.description, requirement.status);
        if (requirement.bypass?.reason) row.append(node("p", "Organizer bypass: " + requirement.bypass.reason));
        section.append(row);
      }
      definition.append(section);
    }
    const checks = $("checks"); checks.replaceChildren();
    for (const check of w.checks || []) checks.append(record(check.label || check.id, check.detail, check.status));
    if (!checks.children.length) checks.append(node("p", "No checks have been recorded.", "empty"));
    const trials = $("attempts"); trials.replaceChildren();
    for (const attempt of attempts.attempts || []) {
      const r = attempt.result || {}, row = record(`${attempt.day || "Saved trial"} · version ${attempt.version || "not recorded"}`, r.detail, r.status);
      if (r.score !== undefined && r.score !== null) { const values = node("dl"); pair(values, "Metric", metricLabels[r.metric] || r.metric); pair(values, "Score", r.score); row.append(values); }
      if (r.review) {
        row.append(node("p", `Code review: ${r.review.status}. ${r.review.summary}`));
        for (const finding of r.review.findings || []) row.append(node("pre", `${finding.file}: ${finding.reason}\nEvidence: ${finding.evidence}`));
      }
      if (r.status === "review_pending" && r.review_attempts < 3 && r.artifact_id) {
        const retry = node("button", "Retry code review"); retry.type = "button";
        retry.addEventListener("click", async () => {
          retry.disabled = true;
          try { await api(root + `/attempts/${r.artifact_id}/review`, {method: "POST"}); await load(); }
          catch (error) { await failure(error); retry.disabled = false; }
        });
        row.append(retry);
      }
      if (r.artifact_id) {
        for (const file of ["code.zip", "predictions.csv"]) {
          const link = node("a", "Download " + file);
          link.href = `/api/projects/${project.id}` + `/attempts/${r.artifact_id}/${file}`;
          row.append(link, node("span", " "));
        }
      }
      trials.append(row);
    }
    if (!trials.children.length) trials.append(node("p", "No development submissions have been scored. Use the submission test above to try one.", "empty"));
    $("feedback-detail").textContent = c.status !== "idle" ? "Return to the agent to finish or retry the saved response before starting a new review round." : c.storage?.required ? "Open the agent to review the storage notice before requesting changes." : "Your earlier answers, scope decisions, and development results stay with the challenge. The agent will ask what you want to change.";
    controls();
  }
  async function load() {
    if (state.loading || state.busy) return;
    const generation = ++state.generation;
    state.loading = true; controls();
    try {
      const [project, conversation, workflow, attempts] = await Promise.all([api(root), api(root + "/conversation"), api(root + "/workflow"), api(root + "/attempts")]);
      if (generation !== state.generation) return;
      if (!workflow.version) { location.replace(interview); return; }
      state.auth = false; $("sign-in").hidden = true;
      state.data = { project, conversation, workflow, attempts }; render();
    } catch (error) { if (generation === state.generation) await failure(error); }
    finally { if (generation === state.generation) state.loading = false; controls(); }
  }
  const pendingKey = "autokaggle-review-iteration:" + id;
  async function discuss() {
    if ($("request-changes").disabled || state.busy) return;
    const generation = state.generation;
    state.busy = true; controls(); notice("Opening the review agent with your saved context…");
    try {
      if (!state.retryId) { try { state.retryId = sessionStorage.getItem(pendingKey); } catch (_) {} state.retryId ||= crypto.randomUUID(); }
      try { sessionStorage.setItem(pendingKey, state.retryId); } catch (_) {}
      await api(root + "/iterate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ request_id: state.retryId }) });
      if (generation !== state.generation) return;
      try { sessionStorage.removeItem(pendingKey); } catch (_) {}
      location.assign(interview);
    } catch (error) { if (generation === state.generation) await failure(error); }
    finally { state.busy = false; controls(); }
  }
  function tab(name, focus = false) {
    for (const current of tabNames) { const selected = current === name; $("tab-" + current).setAttribute("aria-selected", String(selected)); $("tab-" + current).tabIndex = selected ? 0 : -1; $("panel-" + current).hidden = !selected; }
    if (focus) $("tab-" + name).focus(); $("review-content").scrollTop = 0;
  }
  for (const name of tabNames) {
    $("tab-" + name).addEventListener("click", () => tab(name));
    $("tab-" + name).addEventListener("keydown", event => { const index = tabNames.indexOf(name); const next = { ArrowRight: (index + 1) % 4, ArrowLeft: (index + 3) % 4, Home: 0, End: 3 }[event.key]; if (next !== undefined) { event.preventDefault(); tab(tabNames[next], true); } });
  }
  $("refresh").addEventListener("click", load); $("request-changes").addEventListener("click", discuss);
  window.addEventListener("storage", event => {
    if (event.key !== "autokaggle-session-ended") return;
    clearPrivate(); state.auth = true; controls();
    $("sign-in").hidden = false; $("sign-in").href = "/login?next=" + encodeURIComponent(canonical);
    notice("Your account changed or signed out. Sign in again to reopen this review.", "error");
  });
  if (!id || new URLSearchParams(location.search).get("view") !== "review") location.replace(interview); else load();
})();
