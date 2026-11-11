/* Session tools. Remote values are always inserted as text. */
"use strict";
(() => {
  const ws = { id: null, conversation: null, busy: false, action: false, tab: "sessions", importRequest: null, importSignature: null, forgetRequest: null, timer: null };
  const $ = (id) => document.getElementById(id);
  const node = (tag, text, cls) => { const n = document.createElement(tag); if (text != null) n.textContent = text; if (cls) n.className = cls; return n; };
  const button = (text, action, cls = "button button-secondary") => { const n = node("button", text, cls); n.type = "button"; n.addEventListener("click", () => run(action)); return n; };
  const notify = (name, detail) => window.dispatchEvent(new CustomEvent("autokaggle:" + name, { detail }));
  const path = (tail = "") => "/api/projects/" + encodeURIComponent(ws.id) + tail;
  async function api(url, method = "GET", body) {
    const response = await fetch(url, { method, credentials: "same-origin",
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
    const value = await response.json();
    if (!response.ok) {
      const error = new Error(typeof value.detail === "string" ? value.detail : "This action could not finish. Check the current session and retry."); error.status = response.status;
      // The main chat checks account status without exposing private project IDs.
      if ([401, 403, 404].includes(response.status)) notify("refresh");
      throw error;
    }
    return value;
  }
  function notice(text, error = false) { $("workspace-status").textContent = text; $("workspace-status").className = error ? "workspace-status error" : "workspace-status"; }
  function requireIdle() { if (ws.busy) throw new Error("Wait for the current reply before switching or joining a session."); }
  async function run(action) {
    if (ws.action) return;
    ws.action = true; $("workspace-dialog").setAttribute("aria-busy", "true");
    const previous = [...$("workspace-body").querySelectorAll("button")].map((control) => [control, control.disabled]);
    for (const [control] of previous) control.disabled = true;
    try { await action(); } catch (error) { notice(error.message || "The connection was interrupted. Retry to check the result.", true); }
    finally { ws.action = false; $("workspace-dialog").setAttribute("aria-busy", "false"); for (const [control, disabled] of previous) if (control.isConnected) control.disabled = disabled; }
  }
  const dialog = node("dialog", null, "workspace-dialog"); dialog.id = "workspace-dialog"; dialog.setAttribute("aria-labelledby", "workspace-heading");
  const header = node("div", null, "workspace-header");
  const heading = node("h2", "Your research sessions"); heading.id = "workspace-heading";
  const close = button("Close", () => dialog.close(), "button button-quiet"); close.setAttribute("aria-label", "Close session tools");
  header.append(heading, close);
  const nav = node("nav", null, "workspace-tabs"); nav.setAttribute("aria-label", "Session tools");
  const tabs = [["sessions", "Sessions"], ["sources", "Start from research"], ["attempts", "Attempts & changes"], ["share", "Share"], ["privacy", "Data & privacy"]];
  for (const [id, label] of tabs) { const b = button(label, () => show(id), "button button-quiet"); b.dataset.tab = id; nav.append(b); }
  const body = node("div", null, "workspace-body"); body.id = "workspace-body";
  const status = node("p", "", "workspace-status"); status.id = "workspace-status"; status.setAttribute("role", "status");
  dialog.append(header, nav, body, status); document.body.append(dialog);
  const manager = button("Sessions", () => open("sessions"), "button button-quiet"); manager.id = "open-sessions";
  document.querySelector(".project-controls").prepend(manager);
  const profileLink = node("a", "Profile", "button button-quiet"); profileLink.id = "open-profile"; profileLink.hidden = true;
  header.insertBefore(profileLink, close);
  const banner = node("div", null, "storage-banner"); banner.hidden = true; banner.id = "storage-banner";
  banner.append(node("span", "Review data storage before adding research content."), button("Review notice", () => open("privacy"), "button button-small button-secondary"));
  document.querySelector(".conversation-toolbar").after(banner);
  const editDialog = node("dialog", null, "workspace-dialog answer-dialog"); editDialog.id = "answer-dialog"; editDialog.setAttribute("aria-labelledby", "answer-heading");
  editDialog.innerHTML = '<div class="workspace-header"><h2 id="answer-heading">Edit or remove this answer</h2><button type="button" class="button button-quiet" id="close-answer">Close</button></div><div class="workspace-body"><p>The selected answer and generated text that could retain it will be removed. Other researcher answers remain and the agent checks them again. Old drafts, model records, results, review links, and package files are removed from the live session. Daily submission usage is retained.</p><label for="replacement-answer">Replacement answer (leave blank to remove)</label><textarea id="replacement-answer" rows="7" maxlength="12000"></textarea><label class="workspace-check"><input type="checkbox" id="confirm-answer">I understand that this removes the old answer and generated records.</label><div class="workspace-actions"><button type="button" class="button button-primary" id="replace-answer">Replace answer</button><button type="button" class="button button-danger" id="forget-answer">Remove answer</button></div><p id="answer-status" role="status"></p></div>';
  document.body.append(editDialog);
  $("close-answer").addEventListener("click", () => { if (!ws.action) editDialog.close(); });
  let answerId = null;
  document.addEventListener("click", (event) => {
    const control = event.target.closest("[data-edit-answer]");
    if (!control || ws.busy || ws.action) return;
    const answer = ws.conversation?.messages?.find((m) => m.id === control.dataset.editAnswer && m.role === "user");
    if (!answer) return;
    answerId = answer.id; ws.forgetRequest = null;
    $("replacement-answer").value = answer.content; $("confirm-answer").checked = false; $("answer-status").textContent = "";
    editDialog.showModal();
  });
  async function changeAnswer(replace) {
    if (ws.action || !$("confirm-answer").checked) { $("answer-status").textContent = "Confirm removal of the old answer and generated records first."; return; }
    const replacement = $("replacement-answer").value.trim();
    if (replace && !replacement) { $("answer-status").textContent = "Write a replacement, or select Remove answer."; return; }
    const signature = JSON.stringify([answerId, replace ? replacement : null]);
    if (!ws.forgetRequest || ws.forgetRequest.signature !== signature) ws.forgetRequest = { id: crypto.randomUUID(), signature };
    ws.action = true; $("replace-answer").disabled = true; $("forget-answer").disabled = true;
    $("answer-status").textContent = "Removing generated records and checking the remaining answers…";
    try {
      await api(path("/conversation/messages/" + encodeURIComponent(answerId) + "/forget"), "POST", {
        request_id: ws.forgetRequest.id, confirm: true, ...(replace ? { replacement } : {}) });
      $("message-input").value = "";
      try { localStorage.removeItem("autokaggle-chat-compose:" + ws.id); localStorage.removeItem("autokaggle-chat-pending:" + ws.id); } catch (_) {}
      editDialog.close(); notify("refresh");
    } catch (error) { $("answer-status").textContent = error.message || "The connection stopped. Retry with the same action to check the result."; }
    finally { ws.action = false; $("replace-answer").disabled = false; $("forget-answer").disabled = false; }
  }
  $("replace-answer").addEventListener("click", () => changeAnswer(true));
  $("forget-answer").addEventListener("click", () => changeAnswer(false));
  dialog.addEventListener("close", () => { clearTimeout(ws.timer); ws.timer = null; });
  function section(title, text) { body.append(node("h3", title)); if (text) body.append(node("p", text)); }
  function input(label, id, placeholder, type = "text") {
    const lab = node("label", label); lab.htmlFor = id;
    const field = node("input"); field.id = id; field.type = type; field.placeholder = placeholder || ""; field.maxLength = 2000;
    body.append(lab, field); return field;
  }
  async function open(tab) { if (!dialog.open) dialog.showModal(); await show(tab); }
  async function show(tab) {
    clearTimeout(ws.timer); ws.timer = null; ws.tab = tab; body.replaceChildren(); notice("");
    for (const control of nav.querySelectorAll("button")) control.setAttribute("aria-current", control.dataset.tab === tab ? "page" : "false");
    if (tab !== "sessions" && !ws.id) { section("Open a session first", "Select a saved session or create a new one."); return; }
    if (tab === "sessions") return sessions();
    if (tab === "privacy") return privacy();
    if (tab === "sources") return sources();
    if (tab === "share") return share();
    if (tab === "attempts") return attempts();
  }
  async function sessions() {
    section("Continue a session", "Each session keeps its own conversation, files, attempts, and draft.");
    const result = await api("/api/projects");
    const list = node("div", null, "session-list");
    for (const project of result.projects) {
      const row = node("div", null, "session-row"); const detail = node("div");
      detail.append(node("strong", project.title), node("small", (project.researcher_name || "Researcher name not recorded") + " · " + (project.id === ws.id ? "Current · " : "") + project.role + " · " + new Date(project.updated_at).toLocaleString()));
      const actions = node("div", null, "workspace-actions");
      actions.append(button(project.id === ws.id ? "Resume current" : "Open", () => { requireIdle(); dialog.close(); notify("open", { id: project.id }); }, "button button-small button-secondary"));
      if (project.can_delete) actions.append(button("Delete", () => confirmDelete(project), "button button-small button-danger"));
      row.append(detail, actions); list.append(row);
    }
    if (!result.projects.length) list.append(node("p", "No saved sessions."));
    body.append(list);
    if (ws.canCreate !== false) body.append(button("New session", async () => {
      requireIdle();
      const project = await api("/api/projects", "POST", { title: "New challenge" });
      dialog.close(); notify("open", { id: project.id });
    }));
    if (ws.canCreate === false) { body.append(node("p", "Sign in with your own email to create or join another session.")); return; }
    section("Pick up a shared problem", "A single-use handoff code gives you edit access to the same session. It expires after 24 hours. The owner can revoke your access.");
    const code = input("Handoff code", "join-code", "Paste the code from the session owner");
    const consent = node("label", null, "workspace-check"); const check = node("input"); check.type = "checkbox"; check.id = "join-consent";
    consent.append(check, document.createTextNode("I accept the data-storage notice and understand this shares research context."));
    const link = node("a", "Read the storage notice"); link.href = "/privacy"; link.target = "_blank"; link.rel = "noopener";
    body.append(consent, link, button("Join shared session", async () => {
      requireIdle();
      if (!check.checked) throw new Error("Accept the storage and collaboration notice first.");
      const result = await api("/api/handoffs/redeem", "POST", { code: code.value.trim(), accepted: true });
      dialog.close(); notify("open", { id: result.project_id });
    }));
  }
  function confirmDelete(project) {
    body.replaceChildren();
    section("Delete “" + project.title + "”?", "This permanently removes its live messages, files, source imports, model records, drafts, results, and all review and handoff access. It cannot recall copies already downloaded or emailed. Backups are subject to the storage notice.");
    const field = input("Type DELETE to confirm", "delete-session-confirm", "DELETE");
    body.append(button("Delete session permanently", async () => {
      if (field.value !== "DELETE") throw new Error("Type DELETE to confirm this permanent deletion.");
      await api("/api/projects/" + encodeURIComponent(project.id), "DELETE", { confirm: true });
      notify("deleted", { id: project.id });
      await show("sessions"); notice("The live session and its access grants were deleted.");
    }, "button button-danger"), button("Cancel", () => show("sessions")));
  }
  async function privacy() {
    const result = await api(path("/privacy"));
    section("Data storage", result.notice); body.append(node("p", "Policy version " + result.version + (result.accepted_at ? " · accepted " + new Date(result.accepted_at).toLocaleString() : "")));
    if (result.required) {
      const label = node("label", null, "workspace-check"); const check = node("input"); check.type = "checkbox"; check.id = "storage-consent";
      label.append(check, document.createTextNode("I agree to storage of this session and processing of research text and imported excerpts by the configured model service."));
      body.append(label, button("Accept and continue", async () => {
        if (!check.checked) throw new Error("Select the checkbox to accept storage, or delete the session.");
        await api(path("/privacy"), "PATCH", { accepted: true, version: result.version });
        dialog.close(); notify("refresh");
      }, "button button-primary"));
    }
    section("Delete content", "Use Edit or remove answer beside a researcher message to remove one answer and its generated records. Removing imported references keeps approved chat messages; remove those answers separately if needed.");
    body.append(button("Remove imported reference files", async () => { await api(path("/sources"), "DELETE"); notice("Imported references and their model records were removed."); notify("refresh"); }));
    if (result.can_delete) {
      body.append(button("Delete attached dataset", () => {
        body.replaceChildren(); section("Delete the dataset?", "This removes the attached file, generated packages, results, and access tokens. The interview messages stay.");
        const field = input("Type DELETE to confirm", "delete-dataset-confirm", "DELETE");
        body.append(button("Delete dataset and artifacts", async () => {
          if (field.value !== "DELETE") throw new Error("Type DELETE to confirm.");
          await api(path("/dataset"), "DELETE", { confirm: true }); notify("refresh"); await show("privacy"); notice("Dataset and generated artifacts deleted.");
        }, "button button-danger"), button("Cancel", () => show("privacy")));
      }, "button button-danger"));
      body.append(button("Delete this session / withdraw storage", () => confirmDelete({ id: ws.id, title: ws.conversation?.title || "this session" }), "button button-danger"));
    } else body.append(node("p", "The session owner controls dataset and session deletion. You can leave the shared session from Share."));
  }
  async function sources() {
    section("Start from a paper and existing implementation", "Import public references, then review and edit a proposed starting brief. We read bounded text and selected repository files at a fixed commit. We do not execute repository code or import its datasets.");
    const job = await api(path("/sources"));
    const paper = input("Paper or abstract link", "import-paper", "https://arxiv.org/abs/…", "url"); paper.value = job.paper_url || "";
    const repo = input("Public GitHub repository", "import-repository", "https://github.com/owner/repository", "url"); repo.value = job.repository_url || "";
    const importing = ["queued", "working"].includes(job.status);
    paper.disabled = importing; repo.disabled = importing;
    const progress = node("p", job.stage || "Add either link, or both.", "source-progress"); progress.setAttribute("role", "status"); body.append(progress);
    const start = button(job.status === "failed" ? "Retry import" : job.status === "ready" ? "Import again" : "Import references", async () => {
      if (ws.conversation?.storage?.required) throw new Error("Accept Data & privacy before importing research.");
      if (!paper.value.trim() && !repo.value.trim()) throw new Error("Provide a paper or repository link.");
      const signature = JSON.stringify([paper.value.trim(), repo.value.trim()]);
      if (!ws.importRequest || signature !== ws.importSignature || ["failed", "ready"].includes(job.status)) ws.importRequest = crypto.randomUUID();
      ws.importSignature = signature;
      await api(path("/sources"), "POST", { paper_url: paper.value.trim(), repository_url: repo.value.trim(), request_id: ws.importRequest });
      await show("sources");
    }, "button button-primary"); start.disabled = importing; body.append(start);
    if (job.error) body.append(node("p", job.error, "error"));
    if (job.status === "ready" && job.proposal) {
      section(job.proposal.title, "This is a proposal. Edit it before the interview treats it as your starting definition. Source claims have not been reproduced.");
      const label = node("label", "Your starting brief"); label.htmlFor = "source-brief";
      const brief = node("textarea"); brief.id = "source-brief"; brief.rows = 9; brief.maxLength = 12000; brief.value = job.proposal.brief;
      body.append(label, brief);
      const gaps = node("ul"); for (const q of job.proposal.open_questions || []) gaps.append(node("li", q)); body.append(gaps);
      let applyRequest = null;
      body.append(button(job.applied ? "Send revised starting brief" : "Use this starting brief", async () => {
        if (!brief.value.trim()) throw new Error("Write the brief you want to use.");
        if (!applyRequest || applyRequest.text !== brief.value.trim()) applyRequest = { id: crypto.randomUUID(), text: brief.value.trim() };
        await api(path("/sources/apply"), "POST", { brief: applyRequest.text, request_id: applyRequest.id });
        dialog.close(); notify("refresh");
      }, "button button-primary"));
      const records = node("ul"); for (const source of job.sources || []) records.append(node("li", source.kind + ": " + source.url + (source.commit ? " · commit " + source.commit : "") + (source.truncated ? " · bounded excerpt" : ""))); body.append(records);
    }
    if (importing) {
      const selected = ws.id;
      ws.timer = setTimeout(() => { if (dialog.open && ws.tab === "sources" && ws.id === selected && !ws.action) run(() => show("sources")); }, 2000);
    }
  }
  async function share() {
    const result = await api(path("/handoff"));
    section("Continue this problem together", "A handoff code adds a collaborator to this session. They can read and edit its research context and drafts. The owner keeps control of session deletion and access. Each code works once within 24 hours.");
    if (result.can_manage) {
      body.append(button("Create handoff code", async () => {
        const issued = await api(path("/handoff"), "POST", {});
        const label = node("label", "Share this code privately"); label.htmlFor = "issued-handoff";
        const code = node("input"); code.id = "issued-handoff"; code.readOnly = true; code.value = issued.code;
        body.append(label, code, node("p", issued.detail), node("p", "Expires " + new Date(issued.expires_at).toLocaleString()));
        notice("The new code replaces any unused earlier code.");
      }), button("Revoke unused handoff code", async () => { await api(path("/handoff/codes"), "DELETE"); await show("share"); notice("Unused codes revoked."); }));
    }
    for (let index = 0; index < result.members.length; index++) {
      const member = result.members[index]; const row = node("div", null, "session-row");
      row.append(node("span", (member.name ? member.name + " · " : "") + "Collaborator " + member.id.slice(0, 6).toUpperCase() + (member.is_you ? " (you)" : "") + " · joined " + new Date(member.joined_at).toLocaleString()));
      if (result.can_manage || member.is_you) row.append(button(member.is_you ? "Leave session" : "Revoke access", async () => {
        await api(path("/handoff/" + encodeURIComponent(member.id)), "DELETE");
        if (member.is_you) { notify("deleted", { id: ws.id }); dialog.close(); } else { await show("share"); notice("Collaborator access and existing submission tokens revoked."); }
      }, "button button-small button-danger"));
      body.append(row);
    }
    if (!result.members.length) body.append(node("p", "No collaborators have joined yet."));
  }
  async function attempts() {
    const result = await api(path("/attempts"));
    section("Attempts and problem changes", result.detail);
    for (const attempt of result.attempts) {
      const row = node("div", null, "attempt-row");
      const value = attempt.result || {};
      row.append(node("strong", attempt.day + " · " + attempt.version),
        node("p", [value.status, value.metric, typeof value.score === "number" ? String(value.score) : null, value.detail].filter(Boolean).join(" · ")));
      body.append(row);
    }
    if (!result.attempts.length) body.append(node("p", "No submission attempts are saved yet."));
    body.append(node("p", "Revise the scientific definition, method and deployment, or reference baseline after reviewing these attempts. Earlier context and development results remain available. Build the package again after changes."));
    const requestId = crypto.randomUUID();
    const revise = button(ws.conversation?.review?.mode === "revision" && ws.conversation.review.status !== "draft_ready" ? "Continue this revision" : "Revisit the problem definition", async () => {
      if (ws.conversation?.review?.mode === "revision" && ws.conversation.review.status !== "draft_ready") { dialog.close(); notify("refresh"); return; }
      await api(path("/iterate"), "POST", { request_id: requestId });
      dialog.close(); notify("refresh");
    }, "button button-primary");
    revise.disabled = !ws.conversation?.readme && ws.conversation?.review?.mode !== "revision";
    body.append(revise);
    if (revise.disabled) body.append(node("p", "Create a working draft before starting a revision."));
  }
  window.addEventListener("autokaggle:state", (event) => {
    const changed = ws.id !== event.detail.projectId;
    ws.id = event.detail.projectId; ws.conversation = event.detail.conversation; ws.busy = event.detail.busy; ws.canCreate = event.detail.canCreate;
    profileLink.hidden = event.detail.authKind !== "user";
    profileLink.href = "/profile?next=" + encodeURIComponent(ws.id ? "/?project=" + encodeURIComponent(ws.id) : "/");
    profileLink.textContent = event.detail.researcherName || "Profile";
    profileLink.title = event.detail.researcherName || "Edit your researcher name";
    profileLink.setAttribute("aria-label", "Edit your researcher name");
    banner.hidden = !ws.conversation?.storage?.required;
    manager.disabled = false;
    if (changed) { ws.importRequest = null; ws.importSignature = null; clearTimeout(ws.timer); if (dialog.open) run(() => show(ws.tab)); }
  });
})();
