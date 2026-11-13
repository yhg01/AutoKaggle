/* BOLD AutoKaggle Lite. Source and model content is rendered as text. */
"use strict";
(() => {
  const $ = id => document.getElementById(id);
  const groups = [
    ["objective", "Research question", "The claim and useful outcome"],
    ["sources", "Data & environment", "Sources, versions, and access"],
    ["submission", "Submitted artifact", "What another researcher supplies"],
    ["evaluation", "Evaluation", "Metric, seeds, and stopping rules"],
    ["resources", "Resources", "Training and evaluation limits"],
    ["provenance", "Reproduction", "Commands, dependencies, and evidence"]
  ];
  const state = { id: null, data: null, access: null, busy: false, loading: false, auth: false, generation: 0, poll: null, dialog: null, messageKey: "", pending: new Map() };
  const dialog = $("detail-dialog"), content = $("dialog-content");
  const path = (tail = "", id = state.id) => `/api/projects/${encodeURIComponent(id)}/lite${tail}`;
  const el = (tag, text, className) => { const n = document.createElement(tag); if (text !== undefined && text !== null) n.textContent = String(text); if (className) n.className = className; return n; };
  const readable = value => typeof value === "string" ? value : JSON.stringify(value, null, 2);
  const human = key => String(key).replaceAll("_", " ").replace(/^./, c => c.toUpperCase());
  function stored(key, value) { try { if (arguments.length > 1) { if (value === null) sessionStorage.removeItem(key); else sessionStorage.setItem(key, value); } else return sessionStorage.getItem(key); } catch (_) {} return null; }
  function draftKey() { return "autokaggle-lite-draft:" + state.id; }
  function busy() { return state.busy || state.loading || state.data?.status === "working"; }
  function ready() { return !!state.id && !!state.data && !state.auth; }
  function notice(text = "", error = false) { $("notice").textContent = text; $("notice").hidden = !text; $("notice").className = "notice" + (error ? " error" : ""); }
  function modalError(text = "") { $("dialog-error").textContent = text; $("dialog-error").hidden = !text; }
  function safeURL(value, internal = false) {
    if (typeof value !== "string" || !value) return null;
    try { const u = new URL(value, location.origin); if (!["http:", "https:"].includes(u.protocol) || u.username || u.password) return null; if (internal && (u.origin !== location.origin || !u.pathname.startsWith(path() + "/"))) return null; return internal ? u.pathname + u.search : u.href; } catch (_) { return null; }
  }
  async function api(url, options = {}) {
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 45000);
    try {
      const response = await fetch(url, { credentials: "same-origin", ...options, headers: { ...(options.body && !(options.body instanceof FormData) ? { "Content-Type": "application/json" } : {}), ...options.headers }, signal: controller.signal });
      let data; try { data = await response.json(); } catch (_) { throw new Error("The server returned an unexpected response. Refresh the session and try again."); }
      if (!response.ok) { const detail = data.detail; const error = new Error(typeof detail === "string" ? detail : Array.isArray(detail) ? detail.map(x => x.msg || "Invalid input").join("; ") : "The request could not be completed."); error.status = response.status; throw error; }
      return data;
    } catch (error) { if (error.name === "AbortError") throw new Error("The connection timed out. The request may still be running. Retry to recover its result."); if (error instanceof TypeError) throw new Error("The connection was interrupted. Your text stays here. Retry when the connection returns."); throw error; }
    finally { clearTimeout(timer); }
  }
  function controls() {
    renderNextAction();
    const active = ready(), blocked = busy();
    for (const id of ["sources-button", "send-message", "build-package", "retry-request", "continue-round"]) $(id).disabled = !active || blocked;
    $("message-input").disabled = !active || blocked;
    const opening = active ? intake() : null;
    $("attach-paper").hidden = !active; $("attach-paper").disabled = blocked;
    $("message-input").placeholder = codingReview() ? "What should change in the evaluator?" : opening ? "Paste a link, or answer in a sentence…" : "Describe your question, answer, or what you want to change…";
    $("send-message").disabled ||= !$("message-input").value.trim() && !pendingFiles.length;
    $("package-button").disabled = !active;
    $("results-button").disabled = !active;
    $("evaluator-button").disabled = !active;
    for (const id of ["new-button", "sessions-button", "welcome-start"]) $(id).disabled = state.auth || state.busy || state.loading || (id !== "sessions-button" && state.access?.can_create_projects === false);
    $("review-proposals").disabled = !active || blocked;
    $("refresh-session").hidden = !state.id || state.auth; $("refresh-session").disabled = state.busy || state.loading;
    $("thinking").hidden = !blocked;
    $("thinking-text").textContent = state.loading ? "Opening the saved session…" : state.data?.stage || "Saving your request…";
    $("composer-hint").textContent = !active ? "Create a session to start." : blocked ? "Your request is in progress. You can return to this session later." : "Enter to send · Shift + Enter for a new line";
    $("session-state").textContent = state.data?.status === "working" ? "Agent working" : state.data?.package?.status === "stale" ? "Package needs an update" : state.data?.ready ? "Definition recorded" : "Internal draft";
    for (const button of content.querySelectorAll("[data-mutation]")) button.disabled = blocked || state.auth ||
      (button.dataset.packageRequired === "true" && state.data?.package?.status !== "ready") ||
      (button.dataset.evaluatorAction && (evaluatorActive(state.evaluator) ||
        (button.dataset.evaluatorAction === "build" && (!state.evaluator?.available || !state.evaluator?.contract.accepted))));
  }
  function clearPrivate() {
    pendingFiles = []; renderAttachments();
    state.generation++; clearTimeout(state.poll); clearTimeout(state.evaluatorPoll); state.evaluator = null; state.data = null; state.busy = false; state.loading = false; state.messageKey = "";
    $("messages").replaceChildren(); $("message-input").value = ""; $("proposal-banner").hidden = true; $("recovery-banner").hidden = true; $("welcome").hidden = false; $("challenge-title").textContent = "Sign in to continue your research.";
    content.replaceChildren(); if (dialog.open) dialog.close(); renderChecklist(); controls();
  }
  function authFailure() {
    try { for (let i = sessionStorage.length - 1; i >= 0; i--) { const key = sessionStorage.key(i); if (key?.startsWith("autokaggle-lite-")) sessionStorage.removeItem(key); } } catch (_) {}
    clearPrivate(); state.auth = true; controls();
    $("sign-in").hidden = false; $("sign-in").href = "/login?next=" + encodeURIComponent("/lite" + (state.id ? "?project=" + encodeURIComponent(state.id) : ""));
    notice("Your sign-in ended. Sign in again to reopen your saved session.", true);
  }
  async function failure(error) {
    if (error.status === 401) { authFailure(); return; }
    if (error.status === 404 && state.access?.private_mode) {
      try { const access = await api("/api/access"); if (access.auth_kind === "anonymous") { authFailure(); return; } } catch (_) {}
    }
    const message = error.message || "The connection stopped. Try again.";
    if (dialog.open) modalError(message); else notice(message, true);
  }
  function button(text, action, primary = false, mutation = false) {
    const n = el("button", text, "button " + (primary ? "primary" : "secondary")); n.type = "button"; if (mutation) n.dataset.mutation = "true";
    n.addEventListener("click", () => action()); return n;
  }
  function field(label, id, type = "text", help = "") {
    const wrap = el("label", null, "field"), input = el(type === "textarea" ? "textarea" : "input"); input.id = id;
    if (type !== "textarea") input.type = type; wrap.append(el("span", label), input); if (help) wrap.append(el("small", help)); return { wrap, input };
  }
  function showDialog(kind, title, kicker = "YOUR RESEARCH") {
    state.dialog = kind; modalError(); $("dialog-title").textContent = title; $("dialog-kicker").textContent = kicker; content.replaceChildren();
    if (!dialog.open) dialog.showModal();
  }
  function pendingID(action, payload) {
    const key = "autokaggle-lite-request:" + (state.id || "new") + ":" + action, fingerprint = JSON.stringify(payload);
    let saved; try { saved = JSON.parse(stored(key) || "null"); } catch (_) {}
    if (!saved || saved.fingerprint !== fingerprint) { saved = { fingerprint, id: crypto.randomUUID() }; stored(key, JSON.stringify(saved)); }
    return { id: saved.id, key };
  }
  async function mutate(tail, payload, { after, label, withID = true } = {}) {
    if (busy() || !ready()) return;
    const generation = state.generation, request = withID ? pendingID(tail, payload) : null;
    state.busy = true; modalError(); notice(label || "Saving…"); controls();
    try {
      const data = await api(path(tail), { method: "POST", body: JSON.stringify({ ...payload, ...(request ? { request_id: request.id } : {}) }) });
      if (generation !== state.generation) return;
      if (request) stored(request.key, null);
      state.data = data; render(); notice(); if (after) after(data); schedule();
    } catch (error) { if (generation === state.generation) await failure(error); }
    finally { if (generation === state.generation) { state.busy = false; controls(); } }
  }
  function renderChecklist() {
    const checks = state.data?.checklist || [], list = $("checklist"); list.replaceChildren();
    let done = 0;
    for (let i = 0; i < groups.length; i++) {
      const [id, title, hint] = groups[i], item = checks.find(x => x.id === id), complete = !!item && item.total > 0 && item.resolved >= item.total;
      if (complete) done++;
      const n = el("button", null, "check-item" + (complete ? " complete" : "")); n.type = "button"; n.disabled = !state.data; n.id = "check-" + id;
      n.setAttribute("aria-label", title + ": " + (item ? `${item.resolved} of ${item.total} details recorded` : hint));
      n.append(el("span", complete ? "✓" : String(i + 1).padStart(2, "0"), "check-icon"));
      const copy = el("span", null, "check-copy"); copy.append(el("strong", item?.title || title), el("span", item ? `${item.resolved}/${item.total} details recorded` : hint));
      n.append(copy, el("span", "›", "check-chevron")); n.addEventListener("click", () => showCard(id)); list.append(n);
    }
    $("coverage").value = done; $("coverage").textContent = `${done} of 6`;
    $("coverage-label").textContent = state.data ? `${done} of 6 areas defined · select one for evidence` : "The agent records evidence as you go.";
    $("readiness-title").textContent = state.data?.ready ? "Ready to prepare the package" : state.data ? "Only the missing decisions remain" : "Start with what you know";
    $("readiness-detail").textContent = state.data?.ready ? "The contract is defined. The package records how to run and report the experiment." : "A reference baseline is optional. Open decisions stay visible until resolved.";
  }
  function render() {
    const data = state.data; if (!data) { renderChecklist(); controls(); return; }
    $("challenge-title").textContent = data.title || "Untitled research"; document.title = (data.title || "Research") + " · BOLD AutoKaggle Lite";
    $("welcome").hidden = true;
    const opening = intake(), messages = opening ? [{ role: "assistant", content: intakeText.paper }, ...opening.log] : data.messages || [], key = JSON.stringify(messages);
    if (state.messageKey !== key) {
      const transcript = $("transcript"), nearBottom = transcript.scrollHeight - transcript.scrollTop - transcript.clientHeight < 120;
      const root = $("messages"); root.replaceChildren();
      for (const message of messages) {
        const row = el("article", null, "message " + (message.role === "user" ? "user" : message.role === "source" ? "import" : "assistant")), role = el("div", null, "message-role");
        if (message.role !== "user") { const mark = el("img"); mark.src = "/static/bold-butterfly.svg"; mark.alt = ""; role.append(mark); }
        role.append(el("span", message.role === "user" ? "You" : "BOLD AutoKaggle Lite")); row.append(role, el("div", message.content || "", "message-content")); root.append(row);
      }
      if (!messages.length) root.append(el("p", "Share your research question to continue.", "empty"));
      if (nearBottom || !state.messageKey) transcript.scrollTop = transcript.scrollHeight; state.messageKey = key;
    }
    $("proposal-banner").hidden = !data.proposal; $("proposal-summary").textContent = data.proposal?.summary || "Review the source-backed proposal before adding it to the definition.";
    const limit = (data.model?.round_calls || 0) >= (data.model?.limit || 30), failed = data.status === "error";
    $("recovery-banner").hidden = !limit && !failed; $("retry-request").hidden = !failed || limit; $("continue-round").hidden = !limit;
    $("recovery-title").textContent = limit ? "This interview round is complete" : "Your answers are saved";
    $("recovery-detail").textContent = limit ? "Continue with the saved context for another bounded round. Open decisions still need a recorded answer." : "The agent could not finish its last request. Retry it without adding your answer again.";
    $("result-count").textContent = data.results?.length ? `(${data.results.length})` : "";
    renderChecklist(); renderNextAction(); controls();
    if (data.status === "error") notice(data.error || "The agent could not finish this request. Your saved definition is still available. Retry the request or add a correction.", true);
  }
  function renderNextAction() {
    const box = $("next-action"); box.replaceChildren(); box.hidden = true;
    if (!ready() || busy() || intake()) return;
    const field = state.data.proposal?.question_field || "";
    const add = (text, label, action) => { box.hidden = false; box.append(el("p", text), button(label, action)); };
    if (state.data.ready && state.data.package?.status !== "ready") {
      add("The required decisions are recorded. Shall I prepare the versioned package?", "Prepare package", () => mutate("/build", {}, { after: showPackage }));
    } else if (state.data.package?.status === "ready") {
      add("Your package is ready. You can download it, review the evaluation module, or report a local result.", "Download package", showPackage);
      box.append(button("Evaluation module", showEvaluator), button("Report a result", showResults));
    } else if (["source_url", "source_revision"].includes(field)) {
      add("Paste source links in your reply. You can also attach a paper for me to read.", "Attach a paper or source", showSources);
    }
  }
  function schedule(delay = 1500) {
    clearTimeout(state.poll); if (state.data?.status !== "working" || state.auth) return;
    const generation = state.generation; state.poll = setTimeout(async () => {
      try { const data = await api(path()); if (generation !== state.generation) return; state.data = data; render(); schedule(); }
      catch (error) { if (generation === state.generation) { await failure(error); if (!state.auth) schedule(5000); } }
    }, delay);
  }
  async function reload() {
    const generation = state.generation; try { const data = await api(path()); if (generation !== state.generation) return; state.data = data; notice(); render(); schedule(); } catch (error) { if (generation === state.generation) { await failure(error); if (!state.auth) schedule(5000); } }
  }
  async function openSession(id) {
    const arrival = new URLSearchParams(location.search);
    if (arrival.get("project") === id && arrival.get("review") === "evaluator") stored("autokaggle-lite-code-review:" + id, "yes");
    if (state.id) stored(draftKey(), $("message-input").value);
    pendingFiles = []; renderAttachments();
    const generation = ++state.generation; clearTimeout(state.poll); state.id = id; state.data = null; state.messageKey = ""; state.loading = true; state.auth = false;
    $("messages").replaceChildren(); $("welcome").hidden = true; $("proposal-banner").hidden = true; $("challenge-title").textContent = "Opening your research…"; $("message-input").value = stored(draftKey()) || ""; renderChecklist(); controls();
    history.replaceState(null, "", "/lite?project=" + encodeURIComponent(id));
    try { const data = await api(path()); if (generation !== state.generation) return; state.data = data; notice(); render(); schedule();
      if (codingReview()) { $("message-input").placeholder = "What should change in the evaluator?"; notice("Code review: describe what should change. Your earlier context and release are saved."); }
    }
    catch (error) { if (generation === state.generation) { $("challenge-title").textContent = "Session unavailable"; await failure(error); } }
    finally { if (generation === state.generation) { state.loading = false; controls(); } }
  }
  function showNew() {
    showDialog("new", "Start a research session", "BOLD INTERNAL");
    content.append(el("p", "Use a paper and repository to start quickly. Your email identifies this session and keeps it available when you return."));
    const form = el("form"), title = field("Working title (optional)", "new-title"), email = field("Researcher email", "new-email", "email");
    title.input.maxLength = 180; email.input.required = true; email.input.autocomplete = "email"; email.input.maxLength = 254;
    form.append(title.wrap, email.wrap);
    const label = el("label", null, "checkbox-row"), check = el("input"); check.type = "checkbox"; check.id = "storage-accepted"; check.required = true;
    label.append(check, el("span", "I agree to storage of this session and processing of research text and source excerpts by the configured model service."));
    const privacy = el("a", "Read the data-storage notice"); privacy.href = "/privacy"; privacy.target = "_blank"; privacy.rel = "noopener noreferrer";
    const submit = el("button", "Create session →", "button primary"); submit.type = "submit"; submit.dataset.mutation = "true";
    const actions = el("div", null, "dialog-actions"); actions.append(submit); form.append(label, privacy, actions); content.append(form);
    form.addEventListener("submit", async event => {
      event.preventDefault(); if (state.busy || !check.checked) return;
      const generation = state.generation; state.busy = true; controls(); modalError();
      try {
        const data = await api("/api/lite/projects", { method: "POST", body: JSON.stringify({ title: title.input.value.trim(), organizer_email: email.input.value.trim(), storage_accepted: true }) });
        if (generation !== state.generation) return; dialog.close(); state.busy = false; await openSession(data.id); $("message-input").focus();
      } catch (error) { if (generation === state.generation) await failure(error); }
      finally { if (generation === state.generation) { state.busy = false; controls(); } }
    });
    email.input.focus();
  }
  async function showSessions() {
    showDialog("sessions", "Your research sessions"); content.append(el("p", "Loading saved sessions…", "empty"));
    const generation = state.generation;
    try {
      const result = await api("/api/lite/projects"); if (generation !== state.generation || state.dialog !== "sessions" || !dialog.open) return; content.replaceChildren();
      for (const project of result.projects || []) {
        const row = el("article", null, "session-record"), text = el("div"); text.append(el("strong", project.title || "Untitled research"));
        const date = project.updated_at ? new Date(project.updated_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : "";
        text.append(el("p", [date, project.id === state.id ? "Current session" : "Saved session"].filter(Boolean).join(" · "))); const actions = el("div", null, "session-actions"); actions.append(button("Resume →", async () => { dialog.close(); await openSession(project.id); }));
        if (project.can_delete) actions.append(button("Share session", () => showHandoff(project.id)));
        if (project.can_delete) { const remove = el("button", "Delete", "text-button"); remove.type = "button"; remove.addEventListener("click", () => showDelete(project)); actions.append(remove); } row.append(text, actions); content.append(row);
      }
      const join = el("form"), code = field("Handoff code", "handoff-redeem"); code.input.required = true;
      const submit = el("button", "Join shared session", "button secondary"); submit.type = "submit";
      const consentLabel=el("label",null,"consent"), consent=el("input");consent.type="checkbox";consent.required=true;consent.id="handoff-consent";
      consentLabel.append(consent,el("span","I accept storage of this shared session and collaboration access."));
      const privacy=el("a","Read the data-storage notice");privacy.href="/privacy";privacy.target="_blank";privacy.rel="noopener";
      join.append(code.wrap,consentLabel,privacy,submit); content.append(join);
      join.addEventListener("submit", async event => {
        event.preventDefault(); if(!consent.checked){modalError("Accept the storage and collaboration notice first.");return;} submit.disabled = true; modalError();
        try { const result = await api("/api/handoffs/redeem", {method:"POST", body:JSON.stringify({code:code.input.value.trim(),accepted:consent.checked})});
          if (generation !== state.generation) return; location.href = result.redirect;
        } catch(error) { if(generation===state.generation){modalError(error.message);submit.disabled=false;} }
      });
      if (!(result.projects || []).length) content.append(el("p", "No Lite sessions yet. Create one to begin.", "empty"));
      if (state.access?.can_create_projects !== false) { const actions = el("div", null, "dialog-actions"); actions.append(button("New research session", showNew, true)); content.append(actions); }
    } catch (error) { if (generation === state.generation) await failure(error); }
  }
  async function showHandoff(id) {
    showDialog("handoff", "Share this research session", "SESSION ACCESS");
    const generation = state.generation, base = `/api/projects/${encodeURIComponent(id)}/handoff`;
    const active = () => generation === state.generation && state.dialog === "handoff" && dialog.open;
    content.append(el("p", "A handoff code gives another signed-in researcher ongoing edit access. It can be used once within 24 hours. Create a new code to replace an unused code. You can revoke access here."));
    try {
      const data = await api(base); if(!active())return;
      if (!data.can_manage) { content.append(el("p", "Only the session owner can create handoff codes or manage collaborators.")); return; }
      const output = el("div"), actions = el("div", null, "dialog-actions");
      const setPending = value => { create.disabled=value; revoke.disabled=value; };
      const create = button("Create handoff code", async () => {
        if(create.disabled)return;setPending(true); modalError();
        try { const value=await api(base,{method:"POST",body:"{}"});if(!active())return;
          output.replaceChildren(el("code",value.code),el("p",`Expires ${new Date(value.expires_at).toLocaleString()}`));
          output.append(button("Copy code",async()=>{try{await navigator.clipboard.writeText(value.code);}catch(_){modalError("Select and copy the code shown above.");}}));
        } catch(e) {if(active())modalError(e.message);} finally{if(active())setPending(false);}
      });
      const revoke=button("Revoke unused code",async()=>{if(revoke.disabled)return;setPending(true);modalError();try{await api(base+"/codes",{method:"DELETE"});if(active())output.replaceChildren(el("p","Unused codes revoked."));}catch(e){if(active())modalError(e.message);}finally{if(active())setPending(false);}});
      actions.append(create,revoke);
      content.append(actions,output);
      for(const member of data.members || []) {
        const row=el("div",null,"session-record");row.append(el("span",member.name||"Collaborator"));
        row.append(button("Revoke access",async()=>{try{await api(base+"/"+encodeURIComponent(member.id),{method:"DELETE"});if(active())await showHandoff(id);}catch(e){if(active())modalError(e.message);}}));content.append(row);
      }
    }catch(e){if(active())modalError(e.message);}
  }
  function showDelete(project) {
    showDialog("delete", "Delete this research session?", "PERMANENT DELETION");
    content.append(el("p", `This deletes “${project.title || "Untitled research"}”, its conversation, sources, packages, results, and access grants. It cannot recall downloaded files. Backups remain subject to the storage notice.`));
    const form = el("form"), confirm = field("Type DELETE to confirm", "delete-confirm"); confirm.input.required = true; confirm.input.autocomplete = "off"; form.append(confirm.wrap);
    const actions = el("div", null, "dialog-actions"), submit = el("button", "Delete session permanently", "button danger"); submit.type = "submit"; submit.dataset.mutation = "true"; actions.append(submit, button("Cancel", showSessions)); form.append(actions); content.append(form);
    form.addEventListener("submit", async event => {
      event.preventDefault(); if (busy()) return; if (confirm.input.value !== "DELETE") { modalError("Type DELETE to confirm this permanent deletion."); return; }
      const generation = state.generation; state.busy = true; controls(); modalError();
      try {
        await api(`/api/projects/${encodeURIComponent(project.id)}`, { method: "DELETE", body: JSON.stringify({ confirm: true }) });
        if (generation !== state.generation) return;
        try { for (let i = sessionStorage.length - 1; i >= 0; i--) { const key = sessionStorage.key(i); if (key === "autokaggle-lite-draft:" + project.id || key?.startsWith("autokaggle-lite-request:" + project.id + ":")) sessionStorage.removeItem(key); } } catch (_) {}
        state.busy = false;
        if (project.id === state.id) { clearPrivate(); state.id = null; $("challenge-title").textContent = "Start from the research you have."; document.title = "BOLD AutoKaggle Lite"; history.replaceState(null, "", "/lite"); controls(); }
        await showSessions(); notice("The live session and its access grants were deleted.");
      } catch (error) { if (generation === state.generation) await failure(error); }
      finally { state.busy = false; controls(); }
    }); controls();
  }
  function sourceRecords() {
    const list = el("div");
    for (const source of state.data?.sources || []) {
      const row = el("article", null, "source-record"); row.append(el("strong", human(source.kind || "Source")));
      const url = safeURL(source.url); if (url) { const a = el("a", source.url); a.href = url; a.target = "_blank"; a.rel = "noopener noreferrer"; const p = el("p"); p.append(a); row.append(p); }
      else row.append(el("p", source.title || source.filename || source.name || "Uploaded paper"));
      if (source.commit) row.append(el("small", "Frozen commit: " + source.commit)); if (source.sha256) row.append(el("small", "SHA-256: " + source.sha256));
      if (source.truncated) row.append(el("small", "Only a bounded excerpt was read.")); list.append(row);
    } return list;
  }
  function showSources() {
    if (!ready()) return; showDialog("sources", "Sources", "PAPER AND REPOSITORY");
    content.append(el("p", "Add another paper or repository here. The agent reads the paper and selected repository files. Review its proposal before the extracted facts become part of your definition."));
    const form = el("form"), paper = field("Paper URL", "paper-url", "url", "A public paper, abstract, or direct PDF link."), repo = field("Public GitHub repository", "repository-url", "url", "The import records the exact commit it reads."), pdf = field("Or upload a paper PDF", "paper-file", "file", "PDF only, up to 16 MB. This is a reference paper, not a dataset."), brief = field("What do you want to investigate? (optional)", "source-brief", "textarea", "State what should change or improve beyond the source work.");
    pdf.input.accept = ".pdf,application/pdf"; brief.input.maxLength = 30000; paper.input.placeholder = "https://arxiv.org/abs/…"; repo.input.placeholder = "https://github.com/owner/repository";
    form.append(paper.wrap, repo.wrap, pdf.wrap, brief.wrap);
    const submit = el("button", "Read sources and propose a definition →", "button primary"); submit.type = "submit"; submit.dataset.mutation = "true"; const actions = el("div", null, "dialog-actions"); actions.append(submit); form.append(actions); content.append(form);
    if (state.data.sources?.length) { content.append(el("h3", "Saved sources", "section-label"), sourceRecords()); }
    form.addEventListener("submit", async event => {
      event.preventDefault(); if (busy()) return; modalError(); const file = pdf.input.files?.[0];
      if (!paper.input.value.trim() && !repo.input.value.trim() && !file && !state.data.sources?.length) { modalError("Add a paper URL, a PDF, or a public GitHub repository."); return; }
      if (file && (!file.name.toLowerCase().endsWith(".pdf") || file.size > 16 * 1024 * 1024)) { modalError("Choose a PDF file of 16 MB or less."); return; }
      if (file) {
        const generation = state.generation; state.busy = true; controls();
        try { const formData = new FormData(); formData.append("file", file); const data = await api(path("/paper"), { method: "POST", body: formData }); if (generation !== state.generation) return; state.data = data; render(); }
        catch (error) { if (generation === state.generation) await failure(error); return; }
        finally { if (generation === state.generation) { state.busy = false; controls(); } }
      }
      await mutate("/import", { paper_url: paper.input.value.trim(), repository_url: repo.input.value.trim(), brief: brief.input.value.trim() }, { label: "Reading the source material…", after: () => { dialog.close(); } });
    }); controls();
  }
  function showOpenDecisions(decisions, description) {
    if (!decisions?.length) return;
    const section = el("section", null, "extraction-notes"), list = el("ul");
    section.append(el("h3", "Required decisions are still open"), el("p", description));
    for (const decision of decisions) list.append(el("li", `${human(decision.field)}: ${decision.reason}`));
    section.append(list); content.append(section);
  }
  function showProposals() {
    const proposal = state.data?.proposal; if (!proposal) return; showDialog("proposal", "Review the proposed definition", "SOURCE-BACKED PROPOSAL");
    content.append(el("p", proposal.summary || "Confirm that these details describe your intended experiment. Imported text can contain errors."));
    if (proposal.validation_notes?.length) {
      const notes = el("section", null, "extraction-notes"); notes.append(el("h3", "Some proposed values need a decision"), el("p", "The valid details are kept below. These values need correction before they can be recorded."));
      const list = el("ul"); for (const note of proposal.validation_notes) list.append(el("li", `${human(note.field)}: ${note.reason}`)); notes.append(list); content.append(notes);
    }
    showOpenDecisions(proposal.open_decisions, "You can save the defined details. The remaining decisions must be resolved before you can build the package.");
    for (const [key, value] of Object.entries(proposal.contract || {})) { if (value === "") continue; const row = el("article", null, "fact-record"); row.append(el("strong", human(key)), el("p", key === "max_steps" && value === null ? "No step limit. The declared time limit still applies." : readable(value))); const evidence = proposal.evidence?.[key]; if (evidence) row.append(el("p", `${{source: "Source evidence", researcher: "Researcher statement", suggestion: "Agent suggestion — requires your decision"}[evidence.basis] || "Evidence"}: ${evidence.excerpt || readable(evidence)}`, "evidence")); content.append(row); }
    if (proposal.question) { content.append(el("h3", "Still to decide", "section-label"), el("p", proposal.question)); }
    content.append(el("h3", "Sources read", "section-label"), sourceRecords());
    const actions = el("div", null, "dialog-actions");
    actions.append(button(proposal.open_decisions?.length ? "Save defined details" : "Accept this definition", () => mutate("/accept", { proposal_id: proposal.id }, { withID: false, after: () => dialog.close() }), true, true), button("Request a change", () => { dialog.close(); $("message-input").value = "Please change the proposed definition: "; $("message-input").focus(); controls(); }), button("Discard proposal", () => mutate("/discard", { proposal_id: proposal.id }, { withID: false, after: () => dialog.close() }), false, true)); content.append(actions); controls();
  }
  function showCard(id) {
    const item = state.data?.checklist?.find(x => x.id === id); if (!item) return;
    showDialog("card", item.title || human(id), `${item.resolved} OF ${item.total} DETAILS RECORDED`);
    content.append(el("p", item.summary || "The agent records the supported details and asks about the remaining decisions."));
    showOpenDecisions(item.open_decisions, "The saved details remain available. Answer these decisions in the chat to complete this area.");
    const fields = Object.keys(item.fields || {});
    for (const key of fields) { const value = state.data.contract?.[key]; const row = el("article", null, "fact-record"); row.append(el("strong", human(key)), el("p", key === "max_steps" && Object.hasOwn(state.data.contract || {}, key) && value === null ? "No step limit. The declared time limit still applies." : value === undefined || value === "" || value === null ? "Not recorded" : readable(value))); const evidence = state.data.evidence?.[key]; if (evidence) row.append(el("p", `${{source: "Source evidence", researcher: "Researcher statement", suggestion: "Accepted agent suggestion"}[evidence.basis] || "Evidence"}: ${evidence.excerpt || readable(evidence)}`, "evidence")); content.append(row); }
    if (item.missing?.length) { content.append(el("h3", "Remaining decisions", "section-label")); const ul = el("ul"); for (const missing of item.missing) ul.append(el("li", human(missing))); content.append(ul); }
    if (!fields.length && !item.summary) content.append(el("pre", JSON.stringify(state.data.contract, null, 2), "contract"));
    const actions = el("div", null, "dialog-actions"); actions.append(button("Discuss or correct this", () => { dialog.close(); $("message-input").value = `About ${item.title || human(id)}: `; $("message-input").focus(); controls(); })); content.append(actions);
  }
  function artifactLink(text, value, download = false) {
    const href = safeURL(value, true); if (!href) return null; const a = el("a", text, "button secondary"); a.href = href;
    if (download) a.download = ""; else { a.target = "_blank"; a.rel = "noopener noreferrer"; } return a;
  }
  function showPackage() {
    if (!ready()) return; showDialog("package", "Research package", "EVALUATION CONTRACT");
    const pack = state.data.package || {}, available = pack.status === "ready";
    const descriptions = { ready: "The package matches the current definition. Run it on your own approved resources and return the result report.", stale: "The definition has changed. Prepare a new package before running or reporting another attempt.", not_built: "Prepare a versioned package after the required experiment decisions are recorded." };
    content.append(el("div", descriptions[pack.status] || descriptions.not_built, "package-status"));
    if (pack.version) content.append(el("p", "Version " + pack.version, "version"));
    content.append(el("p", "The package contains the README, participant instructions, evaluation contract, fixed evaluation seeds, runner, and submission manifest. Lite evaluation runs on researcher-controlled machines."));
    const actions = el("div", null, "dialog-actions");
    if (available) for (const [text, url, download] of [["Download ZIP ↓", pack.url, true], ["Download config ↓", pack.config_url, true], ["View challenge ↗", pack.preview_url, false], ["Read README ↗", pack.readme_url, false]]) { const a = artifactLink(text, url, download); if (a) actions.append(a); }
    actions.append(button(pack.status === "stale" ? "Update research package" : available ? "Rebuild package" : "Prepare research package", () => mutate("/build", {}, { label: "Preparing the research package…", after: showPackage }), true, true)); content.append(actions);
    content.append(el("h3", "Recorded contract", "section-label"), el("pre", JSON.stringify(state.data.contract || {}, null, 2), "contract"));
    if (!state.data.ready) { content.append(el("h3", "Required decisions are still open", "section-label")); const ul = el("ul"); for (const item of state.data.checklist || []) for (const missing of item.missing || []) ul.append(el("li", `${item.title}: ${human(missing)}`)); content.append(ul); }
    controls();
  }
  function resultLevel(result) {
    const value = result.evidence_level || result.evidence_status || result.verification_status || result.status;
    if (value === "independently_reproduced") return { text: "Independently reproduced", className: "verified" };
    if (value === "evidence_checked") return { text: "Evidence checked · researcher-run", className: "reported" };
    return { text: "Researcher-reported · not independently verified", className: "reported" };
  }
  function showResults() {
    if (!ready()) return; showDialog("results", "Results and evidence", "RESEARCHER-RUN EVALUATION");
    content.append(el("p", "Run the package on your own machine, then upload its JSON result report. The service checks the contract and records the supplied evidence. It does not rerun your model."));
    const form = el("form"), report = field("Run report JSON", "result-file", "file", "Use the report written by the packaged runner. Include its manifest and a result for every required seed, including failures."); report.input.accept = ".json,application/json"; report.input.required = true;
    const preview = el("p", "Select a report to inspect it before submission.", "hint"), submit = el("button", "Record result and evidence", "button primary"); submit.type = "submit"; submit.dataset.mutation = "true"; submit.dataset.packageRequired = "true"; let parsed = null;
    report.input.addEventListener("change", async () => {
      parsed = null; modalError(); const file = report.input.files?.[0]; if (!file) return;
      try { if (file.size > 16 * 1024 * 1024) throw new Error("Use a JSON report of 16 MB or less."); const result = JSON.parse(await file.text()); if (!result || typeof result.manifest !== "object" || !result.manifest || Array.isArray(result.manifest) || !Array.isArray(result.results)) throw new Error("The report needs a manifest object and a results array."); parsed = result; preview.textContent = `${result.results.length} episode records · challenge version ${result.manifest.challenge_version || result.challenge_version || "missing"}. The server checks the manifest and seed coverage when you submit.`; } catch (error) { modalError(error instanceof SyntaxError ? "The file is not valid JSON. Upload the report written by the runner." : error.message); preview.textContent = "Choose a valid run report."; }
    });
    const actions = el("div", null, "dialog-actions"); actions.append(submit); form.append(report.wrap, preview, actions); content.append(form);
    if (state.data.package?.status !== "ready") { submit.disabled = true; content.append(el("p", "Prepare the current research package before recording an attempt.", "hint")); }
    form.addEventListener("submit", event => { event.preventDefault(); if (!parsed) { modalError("Select a valid run report first."); return; } if (state.data.package?.status !== "ready") { modalError("Prepare the current package first."); return; } mutate("/results", { manifest: parsed.manifest, results: parsed.results }, { label: "Checking the submitted report…", after: showResults }); });
    content.append(el("h3", "Saved attempts", "section-label"));
    for (const result of state.data.results || []) {
      const row = el("article", null, "result-record"), level = resultLevel(result); row.append(el("span", level.text, "badge " + level.className));
      row.append(el("h3", result.received_at || result.created_at ? new Date(result.received_at || result.created_at).toLocaleString() : "Saved attempt"));
      const summary = result.summary || result.result || {}; row.append(el("p", readable(summary))); if (result.version || result.challenge_version) row.append(el("small", "Challenge version: " + (result.version || result.challenge_version)));
      if (result.manifest?.artifact_sha256 || result.artifact_sha256) row.append(el("small", "Artifact SHA-256: " + (result.manifest?.artifact_sha256 || result.artifact_sha256))); if (result.limitations) row.append(el("p", result.limitations)); content.append(row);
    }
    if (!state.data.results?.length) content.append(el("p", "No results have been recorded.", "empty")); controls();
  }
  let pendingFiles = [];
  function renderAttachments() {
    const list = $("attachment-list"); list.replaceChildren();
    for (const file of pendingFiles) {
      const chip = el("span", null, "attachment-chip");
      chip.append(el("span", `${file.name} · ${Math.ceil(file.size / 1024)} KB`), button("Remove", () => {
        pendingFiles = pendingFiles.filter(other => other !== file); renderAttachments(); controls();
      })); list.append(chip);
    }
  }
  function addAttachments(files) {
    if (!ready() || busy()) return;
    for (const file of files) {
      if (!file.size || file.size > 50 * 1024 * 1024) { notice("Files must contain data and be no larger than 50 MB. Use a shared link for larger datasets.", true); continue; }
      if (pendingFiles.length >= 12) { notice("Attach at most twelve files at once.", true); break; }
      if (!pendingFiles.some(other => other.name === file.name && other.size === file.size && other.lastModified === file.lastModified)) pendingFiles.push(file);
    }
    renderAttachments(); controls();
  }
  async function uploadAttachments() {
    const generation = state.generation, opening = intake(), names = [];
    state.busy = true; controls();
    try {
      while (pendingFiles.length) {
        const file = pendingFiles[0], form = new FormData(); form.append("file", file);
        notice("Reading " + file.name + "…");
        const data = await api(path("/attachments"), { method: "POST", body: form });
        if (generation !== state.generation) return false;
        state.data = data; pendingFiles.shift(); names.push(file.name); renderAttachments();
      }
      if (opening && opening.step === "paper") {
        opening.pdf = names.join(", "); opening.done.paper = true; opening.step = opening.done.repository ? "question" : "repository";
        opening.log.push({ role: "user", content: "Attached " + names.join(", ") }, { role: "assistant", content: intakeText[opening.step] });
        saveIntake();
      }
      render(); notice(); return true;
    } catch (error) { await failure(error); return false; }
    finally { if (generation === state.generation) { state.busy = false; controls(); } }
  }
  async function sendMessage() {
    let message = $("message-input").value.trim(); if ((!message && !pendingFiles.length) || busy() || !ready()) return;
    if (pendingFiles.length) {
      const opening = intake();
      if (!await uploadAttachments()) return;
      if (!message && opening) { state.messageKey = ""; render(); return; }
      message ||= "Please read the attached files and use them to refine this experiment.";
    }
    if (intake()) { $("message-input").value = ""; stored(draftKey(), null); await answerIntake(message); return; }
    if (codingReview()) {
      await buildEvaluator(message);
      return;
    }
    const links = messageLinks(message);
    const repository = links.find(repositoryRoot);
    const paper = links.find(url => /^https:\/\/(arxiv\.org|doi\.org)\//i.test(url));
    const tail = repository || paper ? "/import" : "/message";
    const payload = repository || paper ? { paper_url: paper || "", repository_url: repository || "", brief: message } : { message };
    await mutate(tail, payload, { label: "Reading your answer…", after: () => { $("message-input").value = ""; stored(draftKey(), null); $("transcript").scrollTop = $("transcript").scrollHeight; } });
  }
  // Only a repository root link can be imported; the server accepts exactly https://github.com/owner/repository.
  // Other GitHub links, such as files, commits, or archives, stay in the message so the model can read them.
  const messageLinks = text => (text.match(/https?:\/\/[^\s<>"')\]]+/gi) || []).map(link => link.replace(/[.,;:!?]+$/, ""));
  const githubLink = link => /^https?:\/\/(www\.)?github\.com\//i.test(link);
  const repositoryRoot = link => /^https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+\/?$/i.test(link);
  const insideRepositoryNote = "That GitHub link points inside a repository. Paste the repository's main link, such as https://github.com/owner/repository. ";
  // Opening questions. A new session starts by asking, in the conversation, whether there is a paper and a repository.
  // The answers are kept in this browser tab until the first request is sent; the saved transcript then takes over.
  const intakeText = {
    paper: "Is this work based on a paper? Paste its link or attach a file. You can also attach notes, tables, code, or images. If there is no paper, say so.",
    repository: "Is there a code repository for it? Paste its public GitHub link. If there is none, say so.",
    question: "What do you want to investigate? One or two sentences are enough. Which BOLD OS project is this evaluation for? Include its project page link."
  };
  const intakeKey = () => "autokaggle-lite-intake:" + state.id;
  function intake() {
    const data = state.data;
    // A new session holds only the service's greeting. The opening questions take its place until the researcher's first request is saved.
    if (!state.id || !data || data.messages?.some(message => message.role === "user") || data.proposal || data.status === "working") return null;
    if (state.intake?.id !== state.id) {
      let saved; try { saved = JSON.parse(stored(intakeKey()) || "null"); } catch (_) {}
      state.intake = { step: "paper", paper: "", repository: "", brief: "", pdf: "", done: {}, log: [], ...(saved || {}), id: state.id, file: null };
      if (!saved && data.sources?.some(source => source.url?.startsWith("uploaded:"))) {
        state.intake.pdf = data.sources.map(source => source.title).join(", "); state.intake.done.paper = true; state.intake.step = "repository";
        state.intake.log.push({role: "assistant", content: "Your files are saved. " + intakeText.repository});
      }
      // Files already uploaded survive reload. A legacy local file selection does not.
      if (state.intake.pdf && !data.sources?.some(source => source.url?.startsWith("uploaded:"))) { state.intake.pdf = ""; state.intake.done.paper = false; state.intake.step = "paper"; state.intake.log.push({ role: "assistant", content: "The page was reloaded, so the attached PDF is gone. " + intakeText.paper }); }
    }
    return state.intake;
  }
  function saveIntake() { const { file, id, ...kept } = state.intake; stored(intakeKey(), JSON.stringify(kept)); }
  async function answerIntake(text, file) {
    const it = intake(); if (!it || busy()) return;
    const say = (role, content) => it.log.push({ role, content }); let note = "";
    if (file) {
      say("user", "Attached " + file.name);
      if (!file.name.toLowerCase().endsWith(".pdf") || file.size > 16 * 1024 * 1024) note = "That file cannot be used. Choose a PDF of 16 MB or less. ";
      else { it.file = file; it.pdf = file.name; it.paper = ""; it.done.paper = true; }
    } else {
      say("user", text);
      const links = messageLinks(text);
      const project = links.find(link => /^https:\/\/bold-lab-ai\.github\.io\/bold-os\/project\.html#/i.test(link));
      if (project) it.project = project;
      const repository = links.find(repositoryRoot), paper = links.find(link => !githubLink(link) && link !== project);
      const inside = links.some(link => githubLink(link) && !repositoryRoot(link));
      const none = /^\s*(no|none|nope|n\/a|not yet|nothing)\b/i.test(text) || /\b(no|not a|without|don't have|do not have)\b[^.]{0,20}\b(paper|preprint|publication|repo|repository|code|github|link)\b/i.test(text);
      if (repository) { it.repository = repository; it.done.repository = true; }
      const fresh = paper && !it.done.paper;  // A link in a later answer does not replace the paper already given.
      if (fresh) { it.paper = paper; it.done.paper = true; }
      if (it.step === "paper" && !fresh) {
        if (none && !repository) it.done.paper = true;
        // A bare link is not a research question, however long it is.
        else if (!repository && text.replace(/https?:\/\/\S+/gi, "").trim().length >= 60 && !it.brief) { it.brief = text; note = "I will use that as your research question. "; }
        else if (!repository) note = inside ? insideRepositoryNote : "I did not find a link. ";
      } else if (it.step === "repository" && !repository) {
        if (none) it.done.repository = true;
        else note = inside ? insideRepositoryNote : links.length ? "I can read public GitHub repositories only. " : "I did not find a GitHub link. ";
      } else if (it.step === "question") it.brief = text;
    }
    it.step = !it.done.paper ? "paper" : !it.done.repository ? "repository" : !it.brief ? "question" : "send";
    if (it.step !== "send") { say("assistant", note + intakeText[it.step]); saveIntake(); state.messageKey = ""; render(); $("transcript").scrollTop = $("transcript").scrollHeight; return; }
    saveIntake(); state.messageKey = ""; render();
    const generation = state.generation;
    if (it.file) {
      state.busy = true; controls();
      try { const formData = new FormData(); formData.append("file", it.file); const data = await api(path("/paper"), { method: "POST", body: formData }); if (generation !== state.generation) return; state.data = data; it.file = null; }
      catch (error) { if (generation === state.generation) { await failure(error); restartIntake(it, "The PDF could not be read. "); } return; }
      finally { if (generation === state.generation) { state.busy = false; controls(); } }
    }
    const sent = () => { stored(intakeKey(), null); state.intake = null; $("transcript").scrollTop = $("transcript").scrollHeight; };
    if (it.paper || it.repository || it.pdf) await mutate("/import", { paper_url: it.paper, repository_url: it.repository, brief: it.brief + (it.project ? "\nBOLD OS project: " + it.project : "") }, { label: "Reading the source material…", after: sent });
    else await mutate("/message", { message: it.brief + (it.project ? "\nBOLD OS project: " + it.project : "") }, { label: "Sending your answer…", after: sent });
    if (generation === state.generation && state.intake === it && intake() === it) restartIntake(it, "That did not go through. Check the links. ");
  }
  function restartIntake(it, note) {
    Object.assign(it, { step: "paper", paper: "", repository: "", pdf: "", file: null, done: {} });
    it.log.push({ role: "assistant", content: note + intakeText.paper }); saveIntake(); state.messageKey = ""; render();
  }
  async function signOut() {
    if (state.busy) return; state.busy = true; controls();
    try { const access = await api("/api/access"); await api("/api/access/logout", { method: "POST", headers: { "X-CSRF-Token": access.csrf_token }, body: "{}" });
      try { for (let i = sessionStorage.length - 1; i >= 0; i--) { const key = sessionStorage.key(i); if (key?.startsWith("autokaggle-lite-")) sessionStorage.removeItem(key); } localStorage.setItem("autokaggle-session-ended", String(Date.now())); } catch (_) {}
      authFailure();
    } catch (error) { await failure(error); } finally { state.busy = false; controls(); }
  }
  // Evaluator build. A separate saved record, loaded when its dialog opens.
  const evaluatorText = {
    not_built: ["Not built", "No evaluator exists for this contract yet. A build writes the scoring code, then tests it from a fresh clone."],
    queued: ["Queued", "The build is waiting for a slot."],
    building: ["Building", "A coding agent is implementing and testing the evaluator in a disposable workspace. This can take several minutes."],
    testing: ["Testing", "The examples are being scored from a fresh clone in a clean environment."],
    ready: ["Software release", "Review the separate software checks and research-data validation below. A release alone does not establish research validation."],
    blocked: ["Draft · a decision is needed", "A decision or input that affects scoring is missing. Answer it in the conversation, accept the updated contract, then build again."],
    failed: ["Draft · the build did not pass", "The evaluator stays a draft. The cause is shown below."],
    stale: ["Draft · the contract changed", "The contract changed after the last tested evaluator. Build again for the current contract."]
  };
  const evaluatorActive = view => ["queued", "building", "testing"].includes(view?.status) || ["queued", "publishing"].includes(view?.release?.publication?.status) || view?.release?.validation?.research_data === "running" || ["queued", "sending"].includes(view?.release?.review_invitation?.status);
  function renderEvaluator(view) {
    if (state.dialog !== "evaluator" || !dialog.open) return; content.replaceChildren();
    const [label, detail] = evaluatorText[view.status] || evaluatorText.not_built, release = view.release, latest = view.latest;
    const status = el("div", null, "package-status"); status.append(el("strong", label + ". "), el("span", evaluatorActive(view) && latest?.stage ? latest.stage + "." : detail)); content.append(status);
    content.append(el("p", view.contract.version ? "Accepted contract version " + view.contract.version : view.contract.accepted ? "The contract is accepted. Its package is prepared when the build starts." : "Accept the contract before building its evaluator.", "version"));
    if (latest?.blockers?.length) { const box = el("div", null, "extraction-notes"); box.append(el("h3", "Decisions that affect scoring")); const ul = el("ul"); for (const item of latest.blockers) ul.append(el("li", human(item.field) + ": " + item.reason)); box.append(ul); content.append(box); }
    else if (latest?.cause && !evaluatorActive(view)) { const box = el("div", null, "extraction-notes"); box.append(el("h3", "Why this build is not ready"), el("p", latest.cause)); content.append(box); }
    if (release) {
      const e = release.evidence, tag = e.tag;
      const v = release.validation || {};
      content.append(el("p", `Contract coverage: ${human(v.contract_coverage || "unassessed")}. Code review: ${human(v.code_review || "unassessed")}. Synthetic tests: ${human(v.synthetic || "unassessed")}. Declared research data: ${human(v.research_data || "not_run")}.`, "extraction-notes"));
      if (release.registry) content.append(el("p", "BOLD OS: " + human(release.registry.status) + ". " + (release.registry.reason || ""), "hint"));
      if (release.review_invitation) content.append(el("p", "Build review email: " + human(release.review_invitation.status) + ". " + (release.review_invitation.reason || ""), "hint"));
      if (v.research_error) content.append(el("p", v.research_error, "extraction-notes"));
      if (v.research_evidence) content.append(el("p", `Research run: observed ${v.research_evidence.observed_fitness}; expected ${v.research_evidence.expected_fitness}. Basis: ${v.research_evidence.expected_basis}`, "hint"));
      content.append(el("h3", "Tested release", "section-label"), el("p", `Evaluator version ${release.evaluator_version}, commit ${e.commit}. The example ${e.fixture} has expected fitness ${e.expected_fitness}; the fresh clone scored ${e.observed_fitness}.`));
      const pub = release.published, link = pub && safeURL(pub.url);
      if (link) { const p = el("p", "Published to the private GitHub repository "), a = el("a", pub.repository + " ↗"); a.href = link; a.target = "_blank"; a.rel = "noopener noreferrer"; p.append(a, el("span", ` at ${pub.tag}.` + (pub.address_recorded ? "" : " This release was built before its repository address was set, so its lock file does not name this repository. Rebuild and publish again to record it."))); content.append(p); }
      if (["queued", "publishing"].includes(release.publication?.status)) content.append(el("p", "Publishing the tested evaluator to GitHub…", "hint"));
      if (release.publication?.status === "failed") content.append(el("p", "GitHub publication needs a retry. " + release.publication.error, "extraction-notes"));
      content.append(el("pre", `git clone ${link ? link + ".git" : "evaluator.bundle"} evaluator && cd evaluator && git checkout ${tag}\npython -m venv .venv && . .venv/bin/activate\npython -m pip install -r requirements.lock\npython fetch_assets.py --mode synthetic\n${e.command}    # expected fitness ${e.expected_fitness}\npython evaluate.py --artifact PATH --output results.json`, "contract"));
    }
    const shown = release || latest;
    if (shown?.tests?.length) { content.append(el("h3", release ? "Fresh-clone tests" : "Tests from the last build", "section-label")); const ul = el("ul", null, "test-list"); for (const t of shown.tests) { const li = el("li", null, t.passed ? "test-pass" : "test-fail"); li.append(el("strong", (t.passed ? "✓ " : "✗ ") + human(t.name)), el("span", " — " + t.detail)); ul.append(li); } content.append(ul); }
    if (shown?.model) content.append(el("p", `${release ? "Built" : "Last attempt"} by ${shown.model.agent} with ${shown.model.name} on ${shown.model.provider} (${shown.model.reasoning} reasoning, ${shown.model.requests} model requests) in a ${shown.runtime?.kind || "separate"} runtime.` + (release ? " Expected scores come from a separate calculation in the same build. Review each example's basis before relying on it." : ""), "hint"));
    if (view.earlier_releases?.length) content.append(el("p", "Earlier tested releases are kept: " + view.earlier_releases.map(r => `version ${r.evaluator_version} (contract ${r.contract_version})`).join(", ") + ".", "hint"));
    const actions = el("div", null, "dialog-actions");
    if (release) for (const [text, url, download] of [["Download release ↓", release.bundle_url, true], ["Download YAML config ↓", release.config_url, true], ["Read README ↗", release.readme_url, false]]) { const a = artifactLink(text, url, download); if (a) actions.append(a); }
    const zip = safeURL(release?.published?.zip_url);
    if (zip) { const a = el("a", "Download GitHub ZIP ↓", "button secondary"); a.href = zip; a.target = "_blank"; a.rel = "noopener noreferrer"; actions.append(a); }
    const start = button(release ? "Rebuild evaluator" : "Build evaluator", buildEvaluator, true, true);
    start.dataset.evaluatorAction = "build";
    start.disabled = evaluatorActive(view) || !view.available || !view.contract.accepted || busy(); actions.append(start);
    const publishing = view.publishing;
    if (release && publishing?.available && (!release.published || release.publication?.status === "failed")) { const send = button(release.publication?.status === "failed" ? "Retry publication" : "Publish to GitHub", publishEvaluator, false, true); send.dataset.evaluatorAction = "publish"; send.disabled = evaluatorActive(view) || busy(); actions.append(send); }
    content.append(actions);
    if (release || latest || view.recoverable_draft) {
      if (release?.validation?.contract_coverage === "passed") {
        const check = button("Validate on research data", showResearchValidation); check.disabled = evaluatorActive(view); content.append(check);
      }
      if (release?.validation?.research_data === "validated") content.append(artifactLink("Download research validation ↓", path("/evaluator/research-report"), true));
      if (release?.validation?.research_data === "validated" && !release.human_approval) content.append(button("Review and approve this version", showReleaseApproval));
      if (release?.human_approval) content.append(el("p", "Human approval recorded for this exact version and research run.", "hint"));
      if (release?.human_approval && ["failed", "pending_connection"].includes(release.registry?.status)) content.append(button("Retry BOLD OS registration", () => evaluatorAction("/registry/retry", {})));
      if (release?.review_invitation?.status && release.review_invitation.status !== "sent") content.append(button("Retry review email", () => evaluatorAction("/review-email", {})));
      content.append(button("Revise code in chat", () => {
        stored("autokaggle-lite-code-review:" + state.id, "yes");
        dialog.close(); state.dialog = null;
        notice("Code review: describe what should change. The agent will inspect and test a new version. Use the Evaluator view to return to the scientific interview.");
        $("message-input").placeholder = "What should change in the evaluator?"; $("message-input").focus();
      }));
      if (codingReview()) content.append(button("Return to scientific interview", () => {
        stored("autokaggle-lite-code-review:" + state.id, null);
        const url = new URL(location.href); url.searchParams.delete("review"); history.replaceState(null, "", url);
        notice("Scientific interview: changes need contract acceptance before the next build."); dialog.close(); state.dialog = null;
      }));
    }
    if (release && publishing?.available && !release.published) content.append(el("p", publishing.repository ? `Publishing updates the private repository ${publishing.repository.name}.` : `Publishing creates a private repository under ${publishing.owner} and pushes the tested commit unchanged.`, "hint"));
    else if (release && publishing?.owner && !publishing.available) content.append(el("p", publishing.reason, "hint"));
    if (!view.available) content.append(el("p", view.unavailable_reason || "Evaluator builds are not available on this server.", "hint"));
    else if (!view.contract.accepted) content.append(el("p", "Resolve and accept the open contract decisions first.", "hint"));
    else content.append(el("p", `A build may use up to ${view.settings.minutes} minutes and ${view.settings.requests} model requests. ` + (publishing?.automatic ? "After the checks pass, the tested release is published to a private GitHub repository. Downloads need access to that repository." : "The release stays in this session until it is published."), "hint"));
  }
  async function evaluatorAction(tail, payload) {
    if (busy() || !ready()) return;
    const generation = state.generation; state.busy = true; modalError(); controls();
    try {
      const view = await api(path("/evaluator" + tail), {method:"POST", body:JSON.stringify(payload)});
      if (generation !== state.generation) return;
      state.evaluator = view; state.busy = false; showDialog("evaluator", "Evaluator", "RELEASE REVIEW"); renderEvaluator(view);
      if (evaluatorActive(view)) state.evaluatorPoll = setTimeout(loadEvaluator, 3000);
    } catch (error) { if (generation === state.generation) await failure(error); }
    finally { if (generation === state.generation) { state.busy = false; controls(); } }
  }
  function showResearchValidation() {
    showDialog("research-validation", "Validate on the declared research data", "MEASURED CHECK");
    content.append(el("p", "Supply an actual research artifact and an expected score from an independent calculation or published scorer. Synthetic examples do not qualify. The server uses the existing resource limits."));
    const form = el("form"), fields = {};
    for (const [key, label, type] of [
      ["artifact_url", "Artifact download link", "url"], ["artifact_sha256", "Artifact SHA-256", "text"], ["artifact_bytes", "Artifact size in bytes", "number"],
      ["reference_url", "Reference download link (optional)", "url"], ["reference_sha256", "Reference SHA-256 (optional)", "text"], ["reference_bytes", "Reference size in bytes (optional)", "number"],
      ["reference_expanded_bytes", "Expanded reference size in bytes (for a ZIP or tar archive)", "number"],
      ["expected_fitness", "Independently established score", "number"], ["expected_basis", "Where does this expected score come from?", "textarea"]]) {
      const f = field(label, "research-" + key, type); fields[key] = f.input;
      f.input.required = !key.startsWith("reference_"); if (type === "number") f.input.step = "any"; form.append(f.wrap);
    }
    const submit = el("button", "Run the validation", "button primary"); submit.type = "submit"; form.append(submit);
    form.addEventListener("submit", event => {
      event.preventDefault(); const body = Object.fromEntries(Object.entries(fields).map(([k, input]) => [k, input.value.trim()]));
      for (const k of ["artifact_bytes", "reference_bytes", "reference_expanded_bytes", "expected_fitness"]) body[k] = Number(body[k]);
      body.reference_archive = body.reference_expanded_bytes > 0;
      body.request_id = pendingID("/evaluator/research-check", body).id;
      evaluatorAction("/research-check", body);
    }); content.append(form);
    content.append(el("p", "Licensed data can remain on your own machine. If the server cannot access it, this stage stays pending. Do not make licensed data public to pass this check.", "hint"));
  }
  function showReleaseApproval() {
    const release = state.evaluator?.release, evidence = release?.validation?.research_evidence;
    if (!evidence) return;
    showDialog("release-approval", "Approve this validated version", "HUMAN REVIEW");
    content.append(el("p", "Confirm that the scientific contract, evaluator code, declared reference data, and measured check meet your requirements. Approval applies only to this commit and research report. It makes this version eligible for the BOLD OS problem bank and benchmarks page."));
    const form = el("form"), note = field("Your review note", "release-review-note", "textarea"); note.input.required = true; note.input.minLength = 10;
    const submit = el("button", "Approve this version for BOLD OS", "button primary"); submit.type = "submit"; form.append(note.wrap, submit);
    form.addEventListener("submit", event => { event.preventDefault(); evaluatorAction("/approve", {build_id:release.id, research_report_sha256:evidence.report_sha256, approved:true, note:note.input.value.trim()}); });
    content.append(form);
  }
  async function loadEvaluator() {
    const generation = state.generation; clearTimeout(state.evaluatorPoll);
    try {
      const view = await api(path("/evaluator")); if (generation !== state.generation) return;
      const finished = evaluatorActive(state.evaluator) && !evaluatorActive(view); state.evaluator = view; renderEvaluator(view);
      if (finished) reload();
      if (evaluatorActive(view) && state.dialog === "evaluator" && dialog.open) state.evaluatorPoll = setTimeout(loadEvaluator, 3000);
    } catch (error) { if (generation === state.generation) await failure(error); }
  }
  function showEvaluator() { if (!ready()) return; showDialog("evaluator", "Evaluator", "BUILD AND TEST"); content.append(el("p", "Loading the build record…", "hint")); loadEvaluator(); }
  function codingReview() { return new URLSearchParams(location.search).get("review") === "evaluator" || stored("autokaggle-lite-code-review:" + state.id) === "yes"; }
  async function buildEvaluator(feedback = "") {
    feedback = typeof feedback === "string" ? feedback : "";
    if (busy() || !ready()) return;
    const generation = state.generation, request = pendingID("/evaluator/build", { version: state.evaluator?.contract?.version || "", builds: state.evaluator?.builds || 0, feedback });
    state.busy = true; modalError(); controls();
    try {
      const view = await api(path("/evaluator/build"), { method: "POST", body: JSON.stringify({ request_id: request.id, feedback: typeof feedback === "string" ? feedback : "" }) }); if (generation !== state.generation) return;
      if (feedback) { $("message-input").value = ""; stored(draftKey(), null); showDialog("evaluator", "Evaluator", "CODE REVIEW"); }
      stored(request.key, null); state.evaluator = view; state.busy = false; renderEvaluator(view); reload();
      if (evaluatorActive(view)) state.evaluatorPoll = setTimeout(loadEvaluator, 3000);
    } catch (error) { if (generation === state.generation) await failure(error); }
    finally { if (generation === state.generation) { state.busy = false; controls(); } }
  }
  async function publishEvaluator() {
    if (busy() || !ready()) return;
    const generation = state.generation; state.busy = true; modalError(); controls();
    try {
      const view = await api(path("/evaluator/publish"), { method: "POST", body: "{}" }); if (generation !== state.generation) return;
      state.evaluator = view; state.busy = false; renderEvaluator(view);
    } catch (error) { if (generation === state.generation) await failure(error); }
    finally { if (generation === state.generation) { state.busy = false; controls(); } }
  }
  $("attach-paper").addEventListener("click", () => $("paper-attach").click?.());
  $("paper-attach").addEventListener("change", () => { addAttachments(Array.from($("paper-attach").files || [])); $("paper-attach").value = ""; });
  $("message-input").addEventListener("paste", event => {
    const files = Array.from(event.clipboardData?.files || []); if (files.length) { event.preventDefault(); addAttachments(files); }
  });
  $("message-form").addEventListener("dragover", event => { if (event.dataTransfer?.types?.includes("Files")) event.preventDefault(); });
  $("message-form").addEventListener("drop", event => { const files = Array.from(event.dataTransfer?.files || []); if (files.length) { event.preventDefault(); addAttachments(files); } });
  $("message-form").addEventListener("submit", event => { event.preventDefault(); sendMessage(); });
  $("message-input").addEventListener("input", () => { if (state.id) stored(draftKey(), $("message-input").value); controls(); });
  $("message-input").addEventListener("keydown", event => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); sendMessage(); } });
  $("close-dialog").addEventListener("click", () => dialog.close());
  for (const [id, action] of [["new-button", showNew], ["welcome-start", showNew], ["sessions-button", showSessions], ["sources-button", showSources], ["review-proposals", showProposals], ["package-button", showPackage], ["evaluator-button", showEvaluator], ["results-button", showResults], ["sign-out", signOut], ["refresh-session", reload], ["retry-request", () => mutate("/retry", {})], ["continue-round", () => mutate("/continue", {})], ["build-package", () => mutate("/build", {}, { after: showPackage })]]) $(id).addEventListener("click", action);
  window.addEventListener("storage", event => { if (event.key === "autokaggle-session-ended") authFailure(); });
  window.addEventListener("focus", () => { if (ready() && !state.busy && !state.loading) reload(); });
  async function start() {
    renderChecklist(); controls();
    try { state.access = await api("/api/access"); $("sign-out").hidden = !state.access.private_mode || state.access.auth_kind === "anonymous";
      if (state.access.private_mode && state.access.auth_kind === "anonymous") { state.id = new URLSearchParams(location.search).get("project"); authFailure(); return; }
      const id = new URLSearchParams(location.search).get("project"), destination = location.hash;
      if (id) { await openSession(id); if (state.data && destination === "#results") showResults(); if(state.data && new URLSearchParams(location.search).get("review")==="handoff") showHandoff(id); }
      else controls();
    } catch (error) { await failure(error); }
  }
  start();
})();
