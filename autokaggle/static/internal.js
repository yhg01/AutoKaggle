"use strict";
(() => {
  const D = window.InternalData, $ = id => document.getElementById(id);
  const categories = [["messages", "Conversation"], ["calls", "Model calls"], ["fields", "Saved fields"], ["changes", "Changes"], ["execution", "Execution"], ["artifacts", "Draft & artifacts"], ["raw", "Raw data"]];
  const params = new URLSearchParams(location.search);
  const state = {id: params.get("project"), section: params.get("view") || "messages", selected: {}, projects: [], total: 0, offset: 0, data: null, pending: null, version: 0, controller: null, refreshing: false, presentation: "visual", inspectorTabs: {}};
  if (!categories.some(c => c[0] === state.section)) state.section = "messages";
  if (params.get("record")) state.selected[state.section] = params.get("record");
  const el = (tag, text, cls) => {const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n;};
  const num = value => typeof value === "number" ? value.toLocaleString() : "Not recorded";
  const date = value => {if (!value) return "Time not recorded"; const d = new Date(value); return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleString();};
  const text = value => value === undefined ? "Not recorded" : value === null ? "null · no saved value" : typeof value === "boolean" ? String(value) : String(value);
  function status(message, error = false) {$("status").textContent = message; $("status").className = error ? "error" : ""; $("refresh").classList.toggle("error", error); $("refresh").title = message;}
  function url() {
    const p = new URLSearchParams(); if (state.id) p.set("project", state.id); p.set("view", state.section);
    if (state.selected[state.section]) p.set("record", state.selected[state.section]);
    const target = `/internal?${p}`;
    if (location.pathname + location.search !== target) history.pushState(null, "", target);
  }
  function pill(value) {return el("span", value || "not recorded", "pill" + (["failed", "rejected", "error", "interrupted"].includes(value) ? " failure" : ["missing", "partial", "incomplete"].includes(value) ? " warning" : ""));}
  function section(parent, title, note) {const n = el("section", undefined, "record-section"); n.append(el("h4", title)); if (note) n.append(el("p", note)); parent.append(n); return n;}
  function table(parent, entries) {const t = el("table", undefined, "record-table"), body = el("tbody"); for (const [key, value] of entries) {const row = el("tr"); row.append(el("th", key), el("td", text(value))); body.append(row);} t.append(body); parent.append(t);}
  function tree(value, key = "record", depth = 0) {
    if (value === null || typeof value !== "object") {
      const n = el("div", undefined, "json-scalar" + (typeof value === "string" && (value.length > 100 || value.includes("\n")) ? " long" : ""));
      n.append(el("span", key, "json-key"), el("pre", text(value))); return n;
    }
    const n = el("details", undefined, "json-node"), entries = Object.entries(value);
    n.append(el("summary", `${key} · ${Array.isArray(value) ? `${entries.length} records` : `${entries.length} keys`}`));
    let built = false;
    const build = () => {if (built) return; built = true; for (const [k, v] of entries) n.append(tree(v, k, depth + 1)); if (!entries.length) n.append(el("p", Array.isArray(value) ? "Empty array" : "Empty object", "muted"));};
    n.addEventListener("toggle", () => {if (n.open) build();});
    if (depth === 0) {n.open = true; build();}
    return n;
  }
  function raw(parent, value) {const d = el("details", undefined, "raw-details"); d.append(el("summary", "Original record JSON")); d.addEventListener("toggle", () => {if (d.open && d.children.length === 1) d.append(el("pre", JSON.stringify(value, null, 2), "text-value code"));}); parent.append(d);}
  function go(sectionId, recordId) {state.section = sectionId; state.selected[sectionId] = recordId; $("record-search").value = ""; $("record-filter").value = ""; render(true); url();}
  function jump(parent, title, sectionId, row) {const b = el("button", title, "record-link"); b.addEventListener("click", () => go(sectionId, row.id)); parent.append(b);}
  function projectList() {
    const q = $("project-search").value.toLowerCase(), root = $("projects"); root.replaceChildren();
    for (const p of state.projects.filter(p => `${p.title} ${p.id}`.toLowerCase().includes(q))) {
      const b = el("button", undefined, "project" + (p.id === state.id ? " active" : "")); b.setAttribute("aria-current", p.id === state.id ? "true" : "false");
      b.append(el("strong", p.title), el("small", `${p.conversation_status || p.status} · ${p.model_calls} calls`), el("small", date(p.updated_at)));
      b.addEventListener("click", () => {if (state.id === p.id) return; state.id = p.id; state.data = null; state.pending = null; state.selected = {}; $("new-data").hidden = true; $("record-search").value = ""; $("record-filter").value = ""; $("project-title").textContent = p.title; $("project-id").textContent = p.id; $("records").replaceChildren(el("p", "Loading saved records…", "empty")); $("inspector").replaceChildren(); $("export").disabled = true; projectList(); url(); load(true);});
      root.append(b);
    }
    if (!root.children.length) root.append(el("p", "No projects match this page.", "empty"));
    $("project-total").textContent = num(state.total);
    $("previous").disabled = state.offset === 0 || state.refreshing; $("next").disabled = state.offset + 50 >= state.total || state.refreshing;
    $("page").textContent = `${state.total ? state.offset + 1 : 0}–${Math.min(state.offset + 50, state.total)} / ${state.total}`;
  }
  function render(rebuildFilters = false) {
    if (!state.data) return;
    const data = state.data, p = data.project, records = D.rows(data, state.section);
    $("project-title").textContent = p.title; $("project-title").title = p.title; $("project-id").textContent = p.id;
    $("project-meta").textContent = `Saved status: ${p.status} · Conversation: ${p.conversation?.status ?? "not recorded"} · Revision ${p.revision ?? "not recorded"} · Saved ${date(p.updated_at)}`;
    $("export").disabled = false;
    const nav = $("sections"); nav.replaceChildren();
    for (const [id, label] of categories) {
      const b = el("button", undefined, "section-button" + (state.section === id ? " selected" : ""));
      const icon = el("span", {messages:"◌",calls:"▥",fields:"▦",changes:"⇄",execution:"◇",artifacts:"▤",raw:"{ }"}[id], "nav-icon"); icon.setAttribute("aria-hidden", "true");
      b.append(icon, el("span", label), el("span", D.rows(data, id).length, "nav-count")); b.setAttribute("aria-pressed", String(state.section === id));
      b.addEventListener("click", () => {state.section = id; $("record-search").value = ""; $("record-filter").value = ""; render(true); url();}); nav.append(b);
    }
    if (rebuildFilters) {
      const filter = $("record-filter"), old = filter.value; filter.replaceChildren(new Option("All records", ""));
      for (const v of [...new Set(records.map(r => r.status || r.type).filter(Boolean))]) filter.append(new Option(v, v));
      filter.value = [...filter.options].some(o => o.value === old) ? old : "";
    }
    const visible = D.select(records, $("record-search").value, $("record-filter").value, $("record-order").value === "reverse");
    $("record-count").textContent = `${visible.length} / ${records.length}`;
    $("category-title").textContent = categories.find(c => c[0] === state.section)[1];
    $("visual-view").setAttribute("aria-pressed", String(state.presentation === "visual"));
    $("list-view").setAttribute("aria-pressed", String(state.presentation === "list"));
    const traces = p._model_traces || [], usage = D.totals(traces);
    const notes = {
      messages: "Sequence numbers preserve saved message order. Missing timestamps remain unrecorded; links use saved message IDs only.",
      calls: `${traces.length} retained / ${p._model_calls ?? "unknown"} total calls · Retained usage: ${num(usage.input)} input, ${num(usage.output)} output tokens (${usage.measured} measured calls). Reasoning tokens are part of output, not an extra total. Cost is not recorded.`,
      fields: "Field values, evidence and settings are displayed as saved. A saved status is not an independent verification of scientific correctness.",
      changes: "Each source array retains its own recorded order. No timestamp or historical after-state is inferred where it was not saved.",
      execution: `Application state, checks, events and ledgers. Showing up to ${data.review?.submissions?.limit ?? 200} submissions and ${data.review?.review_invitations?.limit ?? 100} invitation metadata records. No worker files or test answers are exposed.`,
      artifacts: "Saved drafts, advice and artifact metadata. A listed artifact or suggested action does not establish that execution occurred.",
      raw: "Saved project fields, with credentials and correspondence addresses redacted. Export JSON includes the same project snapshot and review ledgers."
    };
    if (!visible.some(r => r.id === state.selected[state.section])) state.selected[state.section] = visible[0]?.id;
    const list = $("records"); list.replaceChildren(); list.classList.toggle("list-mode", state.presentation === "list");
    const note = el("details", undefined, "data-notes"); note.append(el("summary", "Record scope & reading notes"), el("p", notes[state.section])); list.append(note);
    if (state.presentation === "visual" && state.section === "calls" && visible.length) callCharts(list, visible);
    if (state.presentation === "visual" && ["messages", "changes"].includes(state.section)) {
      const timeline = el("div", undefined, "timeline"); visible.forEach(row => timeline.append(recordCard(row))); list.append(timeline);
    } else if (state.presentation === "visual") {
      const groups = new Map();
      for (const row of visible) {
        const key = row.group || (row.type === "settings" ? "Application settings" : {execution:"Saved application state", event:"Execution events", submission:"Development submissions", invitation:"Review invitations", draft:"Saved drafts", artifact:"Artifacts", advice:"Advice", raw:"Stored sections", call:"Call records"}[row.type] || "Records");
        if (!groups.has(key)) groups.set(key, []); groups.get(key).push(row);
      }
      for (const [name, group] of groups) {const block = el("section", undefined, "board-group"), head = el("div", undefined, "group-heading"), grid = el("div", undefined, "card-grid"); head.append(el("h3", name), el("span", group.length)); block.append(head, grid); group.forEach(row => grid.append(recordCard(row))); list.append(block);}
    } else visible.forEach(row => list.append(recordCard(row)));
    if (!visible.length) list.append(el("div", records.length ? "No records match this search or filter." : "No saved records in this category.", "empty"));
    const selected = visible.find(r => r.id === state.selected[state.section]);
    if (selected) inspect(selected); else $("inspector").replaceChildren(el("p", "Select a record to inspect.", "empty"));
  }
  function choose(row) {
    state.selected[state.section] = row.id;
    for (const b of $("records").querySelectorAll(".record-row")) {const selected = b.dataset.recordId === row.id; b.classList.toggle("selected", selected); b.setAttribute("aria-pressed", String(selected));}
    inspect(row); url();
  }
  function recordCard(row) {
    const b = el("button", undefined, "record-row" + (row.id === state.selected[state.section] ? " selected" : "")); b.dataset.recordId = row.id; b.dataset.role = row.value?.role || ""; b.setAttribute("aria-pressed", String(row.id === state.selected[state.section]));
    const top = el("div", undefined, "row-top"); top.append(el("span", `#${row.index}`, "row-index"), el("strong", row.label)); if (row.status && row.type !== "message") top.append(pill(row.status)); b.append(top);
    let preview = row.subtitle;
    if (row.type === "settings") preview = Object.entries(D.object(row.value)).map(([k,v]) => `${k}: ${text(v)}`).slice(0, 3).join(" · ");
    if (row.id === "workflow" && row.value) preview = `${Array.isArray(row.value.checks) ? row.value.checks.length + " saved checks" : "Checks not recorded"} · ${Array.isArray(row.value.artifacts) ? row.value.artifacts.length + " artifact records" : "Artifacts not recorded"}`;
    if (row.id === "harness" && row.value) preview = `Stage: ${row.value.stage ?? "not recorded"}`;
    if (row.id === "dataset" && row.value) preview = `${num(row.value.rows)} rows · ${Array.isArray(row.value.columns) ? row.value.columns.length : "Unknown"} columns`;
    if (row.id === "analysis" && row.value) preview = `${Array.isArray(row.value.checks) ? row.value.checks.length + " saved checks" : "Check records unavailable"} · baseline: ${row.value.baseline?.status ?? "not recorded"}`;
    if (row.type === "raw") preview = row.value !== null && typeof row.value === "object" ? `${Object.keys(row.value).length} ${Array.isArray(row.value) ? "records" : "keys"} · expand to inspect` : D.short(row.value);
    if (row.type === "change" && Array.isArray(row.value.replacement_evidence)) preview = row.value.replacement_evidence.join(" · ");
    if (row.value === null) preview = "No saved record";
    b.append(el("div", preview, "row-preview"));
    if (row.type === "field") {
      const cells = D.requirementCells(state.data, row), strip = el("div", undefined, "requirement-strip");
      for (const cell of cells) {const dot = el("span", undefined, "requirement-dot"); dot.dataset.status = cell.status; dot.title = `${cell.label}: ${cell.status}`; strip.append(dot);}
      if (cells.length) b.append(strip);
      b.append(el("div", `${D.array(row.value.evidence).length} evidence records · ${cells.filter(c=>c.value !== null).length}/${cells.length} saved requirement assessments`, "row-meta"));
    } else if (row.type === "call") b.append(el("div", `${row.value.duration_ms === undefined ? "Duration not recorded" : (row.value.duration_ms/1000).toFixed(2)+"s"} · validation: ${row.value.validation?.status || "not recorded"}`, "row-meta"));
    else if (row.at) b.append(el("div", date(row.at), "row-meta"));
    else if (row.type === "change") b.append(el("div", "Source order retained · time not recorded", "row-meta"));
    b.addEventListener("click", () => choose(row)); return b;
  }
  function callCharts(parent, rows) {
    const panel = el("section", undefined, "chart-panel"), header = el("div", undefined, "chart-header"); header.append(el("strong", "Retained calls"), el("span", "Click a bar to inspect the call")); panel.append(header);
    const legend = el("div", undefined, "chart-legend"), inputKey = el("span"), outputKey = el("span"); inputKey.append(el("i"), el("span", "Input tokens")); outputKey.append(el("i", undefined, "output-key"), el("span", "Output tokens")); legend.append(inputKey, outputKey); panel.append(legend);
    const maxTokens = Math.max(1, ...rows.map(r => (r.value.usage?.input_tokens || 0) + (r.value.usage?.output_tokens || 0)));
    const maxTime = Math.max(1, ...rows.map(r => r.value.duration_ms || 0));
    for (const mode of ["tokens", "duration"]) {
      const block = section(panel, mode === "tokens" ? "Token volume" : "Wall time");
      for (const row of rows) {
        const t = row.value, b = el("button", undefined, "chart-row"), track = el("span", undefined, "chart-track"); let label;
        if (mode === "tokens") {
          const input = t.usage?.input_tokens, output = t.usage?.output_tokens;
          label = typeof input === "number" && typeof output === "number" ? num(input+output) : "Unknown";
          if (label !== "Unknown") for (const [cls,n] of [["input",input],["output",output]]) {const bar = el("span", undefined, "chart-segment "+cls); bar.style.width = `${100*n/maxTokens}%`; track.append(bar);}
          b.title = `Call #${row.index}: ${num(input)} input, ${num(output)} output tokens`;
        } else {label = typeof t.duration_ms === "number" ? `${(t.duration_ms/1000).toFixed(2)}s` : "Unknown"; if (label !== "Unknown") {const bar=el("span",undefined,"chart-segment duration"); bar.style.width=`${100*t.duration_ms/maxTime}%`; track.append(bar);} b.title=`Call #${row.index}: ${label}`;}
        b.append(el("span", `#${row.index} ${t.kind}`), track, el("span", label)); b.addEventListener("click",()=>choose(row)); block.append(b);
      }
    }
    panel.append(el("p", "Only retained measurements are plotted. Unknown measurements have no bar.", "muted")); parent.append(panel);
  }
  function inspect(row) {
    const root = $("inspector"), value = row.value;
    root.replaceChildren(); root.scrollTop = 0;
    const head = el("div", undefined, "inspector-heading"), copy = el("button", "Copy JSON");
    copy.addEventListener("click", async () => {try {await navigator.clipboard.writeText(JSON.stringify(value, null, 2)); copy.textContent = "Copied";} catch (_) {status("Clipboard unavailable. Use the JSON tab to copy manually.", true);}});
    head.append(el("h3", row.label), copy); root.append(head);
    const choices = row.type === "call" ? [["output","Output"],["input","Input"],["reasoning","Reasoning"],["meta","Meta"],["links","Links"],["raw","JSON"]]
      : row.type === "field" ? [["value","Value & evidence"],["requirements","Requirements"],["links","Links"],["raw","JSON"]]
      : row.type === "message" ? [["value","Message"],["links","Links"],["raw","JSON"]]
      : row.type === "change" ? [["compare","Compare"],["links","Links"],["raw","JSON"]]
      : [["value",row.type === "raw" ? "Tree" : "Panel"],["raw","JSON"]];
    const selected = choices.some(c=>c[0]===state.inspectorTabs[row.type]) ? state.inspectorTabs[row.type] : choices[0][0];
    const nav=el("nav",undefined,"inspector-tabs"); nav.setAttribute("aria-label","Record detail views");
    for(const [id,label] of choices) {const b=el("button",label);b.setAttribute("aria-pressed",String(selected===id)); b.addEventListener("click",()=>{state.inspectorTabs[row.type]=id;inspect(row);});nav.append(b);}root.append(nav);
    const pane=el("div",undefined,"inspector-content");root.append(pane);
    if(selected==="raw") {pane.append(el("p",row.path,"source-path"),el("pre",JSON.stringify(value,null,2),"text-value code"));return;}
    if(selected==="links") {linkedPanel(pane,row);return;}
    if(row.type==="call") callInspector(pane,row,selected);
    else if(row.type==="field") fieldInspector(pane,row,selected);
    else if(row.type==="message") {relationMap(pane,row); section(pane,"Original message").append(el("pre",value.content ?? value.text ?? "","text-value"));
      const meta=el("details",undefined,"raw-details");meta.append(el("summary","Message metadata"));table(meta,[["Message ID",value.id],["Role",value.role],["Time",row.at?date(row.at):"Not recorded"]]);pane.append(meta);}
    else if(row.type==="change") changeInspector(pane,row);
    else if(row.type==="draft") section(pane,"Saved README", "Original Markdown text.").append(el("pre",value ?? "No README is saved.","text-value"));
    else if(row.type==="execution" || row.type==="submission") executionInspector(pane,row);
    else if(row.type==="settings") table(pane,Object.entries(D.object(value)));
    else if(row.type==="advice") {if(value.content) section(pane,"Saved advice").append(el("pre",value.content,"text-value"));pane.append(tree(value,"Record metadata"));}
    else pane.append(tree(value));
  }
  function relationMap(parent,row) {
    const links=D.related(state.data,row);
    if(!links.messageIds.length)return;
    parent.append(el("p","Saved ID links · counts are records, not inferred events","link-key"));
    const map=el("div",undefined,"link-map");
    for(const [key,label] of [["messages","Messages"],["calls","Model calls"],["fields","Saved fields"],["changes","Changes"]]) {
      const b=el("button",undefined,"link-step");b.append(el("span",label),el("strong",links[key].length));b.disabled=!links[key].length;
      b.addEventListener("click",()=>{if(links[key].length===1)go(key,links[key][0].id);else{state.inspectorTabs[row.type]="links";inspect(row);}});map.append(b);
    }parent.append(map);
  }
  function linkedPanel(parent,row) {
    const links=D.related(state.data,row);
    if(!links.messageIds.length) {parent.append(el("p","No source message ID was saved for this record. Links are not inferred from nearby timestamps.","section-note"));return;}
    for(const [key,label] of [["messages","Source messages"],["calls","Model calls"],["fields","Saved fields"],["changes","Saved changes"]]) {
      const block=section(parent,`${label} · ${links[key].length}`);
      for(const r of links[key])jump(block,`#${r.index} · ${r.label} — ${D.short(r.subtitle)}`,key,r);
      if(!links[key].length)block.append(el("p","No linked record is saved."));
    }
  }
  function capturePanel(parent,t,key,label) {
    const capture=D.captured(t,key),n=section(parent,label);
    if(capture.truncated)n.append(el("p",`Truncated capture · ${capture.originalChars===null?"Original length unknown":num(capture.originalChars)+" original characters"}. Only the retained text is available.`,"section-note"));
    if(capture.parsed!==undefined)n.append(tree(capture.parsed,label));else n.append(el("pre",capture.text===undefined?"Not recorded":capture.text||"Empty string","text-value code"));
  }
  function callInspector(parent,row,tab) {
    const t=row.value;
    if(tab==="output") {
      const metrics=el("div",undefined,"call-metrics");
      for(const [v,label] of [[num(t.usage?.input_tokens),"Input tokens"],[num(t.usage?.output_tokens),"Output tokens"],[t.duration_ms===undefined?"—":(t.duration_ms/1000).toFixed(2)+"s","Wall time"]]){const box=el("div");box.append(el("strong",v),el("span",label));metrics.append(box);}parent.append(metrics);
      const stage=el("div",undefined,"row-top");stage.append(el("span","Provider","muted"),pill(t.provider_status),el("span","→ validation","muted"),pill(t.validation?.status||"not recorded"));parent.append(stage);
      relationMap(parent,row);
      const cap=D.captured(t,"output");
      if(cap.parsed&&typeof cap.parsed==="object"&&!Array.isArray(cap.parsed))providerOutput(parent,cap.parsed);
      else capturePanel(parent,t,"output","Provider output");
      parent.append(el("p","Output is the original provider response. Validation and field application are separate records.","section-note"));
    } else if(tab==="input") {capturePanel(parent,t,"input","Request input");const sys=el("details",undefined,"raw-details");sys.append(el("summary","System instructions"));capturePanel(sys,t,"instructions","Instructions");parent.append(sys);}
    else if(tab==="reasoning") {table(parent,[["Reasoning tokens (included in output)",t.usage?.reasoning_tokens],["Readable reasoning returned",t.reasoning_available]]);if(t.reasoning_available)capturePanel(parent,t,"reasoning","Provider-returned reasoning");else parent.append(el("p","No readable reasoning text was returned. A token count does not reveal hidden reasoning.","section-note"));}
    else {parent.append(el("p",row.path,"source-path"));table(parent,[["Call ID",t.id],["Model",t.model],["Call status",t.status],["Provider status",t.provider_status],["Validation",t.validation?.status],["Validation code",t.validation?.code],["Started",date(t.started_at)],["Finished",t.finished_at?date(t.finished_at):"Not recorded"],["Effort",t.effort],["Error type",t.error_type]]);parent.append(tree(t.trigger??null,"Recorded trigger"),tree(t.capture??null,"Capture metadata"));}
  }
  function providerOutput(parent,value) {
    if(value.question_text){const box=section(parent,"Proposed next question");box.append(el("pre",value.question_text,"text-value"));if(value.question_why)box.append(el("p",value.question_why));if(value.question_field)box.append(el("p",`${value.question_field} / ${value.question_requirement_id||"criterion not recorded"}`,"meta"));}
    if(value.intro)section(parent,"Draft introduction").append(el("pre",value.intro,"text-value"));
    for(const [key,label] of [["updates","Proposed field updates"],["requirements","Proposed requirement assessments"]])if(Array.isArray(value[key])){
      const n=section(parent,`${label} · ${value[key].length}`);
      for(const item of value[key]){if(item===null||typeof item!=="object"||Array.isArray(item)){n.append(tree(item,"Returned entry"));continue;}const card=el("div",undefined,"value-card"),top=el("div",undefined,"row-top");top.append(el("strong",`${item.field||"field not recorded"}${item.id?" / "+item.id:""}`),pill(item.status));card.append(top);
        if(item.operation)card.append(el("p",item.operation,"meta"));
        for(const q of D.array(item.evidence))card.append(el("pre",typeof q==="string"?q:D.pretty(q),"text-value"));
        if(item.remaining_gap||item.reason)card.append(el("p",item.remaining_gap||item.reason,"muted"));n.append(card);
      }if(!value[key].length)n.append(el("p","Empty array returned."));
    }
    if(Array.isArray(value.next_actions)){const n=section(parent,"Proposed next actions"),list=el("ol");for(const action of value.next_actions)list.append(el("li",action));n.append(list);}
    const extra=Object.fromEntries(Object.entries(value).filter(([k])=>!["question_text","question_why","question_field","question_requirement_id","intro","updates","requirements","next_actions"].includes(k)));
    if(Object.keys(extra).length)section(parent,"Other returned fields").append(tree(extra));
  }
  function fieldInspector(parent,row,tab) {
    const item=row.value;
    if(tab==="requirements") {
      const matrix=el("div",undefined,"requirement-matrix");
      for(const cell of D.requirementCells(state.data,row)) {const tile=el("details",undefined,"requirement-cell"),title=el("summary");title.append(el("div",cell.label),pill(cell.status));tile.append(title,el("p",cell.description,"muted"),tree(cell.value,cell.id));matrix.append(tile);}parent.append(matrix);
      if(!matrix.children.length)parent.append(el("p","No requirement definitions or assessments are saved.","muted"));
      for(const key of ["scope","bypasses"])if(item[key])section(parent,key==="scope"?"Saved scope decision":"Saved manual bypasses").append(tree(item[key]));
      return;
    }
    const top=el("div",undefined,"row-top");top.append(pill(item.status),el("span",row.group,"muted"));parent.append(top);
    relationMap(parent,row);
    section(parent,"Saved field value").append(el("pre",item.value===""?"Empty string · no saved text":item.value??"Not recorded","text-value"));
    const setupKeys={competition:["competition_type"],submissions:["daily_submission_limit","submissions_confirmed"],organizer:["organizer_email"]}[row.id];
    if(setupKeys){const block=section(parent,"Canonical application settings");table(block,setupKeys.map(k=>[k,state.data.project.setup?.[k]]));}
    if(item.gap)section(parent,"Saved remaining gap").append(el("p",item.gap));
    const evidence=section(parent,`Source evidence · ${D.array(item.evidence).length}`);
    for(const e of D.array(item.evidence)){
      const block=el("div",undefined,"evidence");for(const q of D.array(e.quotes))block.append(el("blockquote",typeof q==="string"?q:D.pretty(q)));
      const message=D.rows(state.data,"messages").find(m=>m.value.id===e.message_id);
      if(message)jump(block,`Open source message #${message.index}`,"messages",message);else block.append(el("p","Source message is not present in this snapshot.","muted"));
      const meta=el("details");meta.append(el("summary","Evidence metadata"),tree(e));block.append(meta);evidence.append(block);
    }
    if(!D.array(item.evidence).length)evidence.append(el("p","No source evidence is saved."));
  }
  function changeInspector(parent,row) {
    const v=row.value,columns=el("div",undefined,"split-values");
    const values=[["Before this change",v.before],[v.after===undefined?"Current saved state":"After this change",v.after===undefined?state.data.project.conversation?.items?.[v.field]:v.after]];
    for(const [label,value] of values){const box=section(columns,label);if(value===undefined)box.append(el("p","Not recorded","muted"));else {const body=value&&typeof value==="object"&&"value" in value?value.value:value;if(value?.status)box.append(pill(value.status));box.append(typeof body==="string"?el("pre",body,"text-value"):tree(body));}}parent.append(columns);
    if(v.after===undefined&&v.before!==undefined)parent.append(el("p","The second panel is the current field snapshot. This historical record did not save an after-state.","section-note"));
    if(v.replacement_evidence)section(parent,"Recorded replacement evidence").append(tree(v.replacement_evidence));
    relationMap(parent,row);section(parent,"Change metadata").append(tree(Object.fromEntries(Object.entries(v).filter(([k])=>!["before","after"].includes(k)))));
  }
  function executionInspector(parent,row) {
    const value=row.value;
    if(value===null){parent.append(el("div","No record has been saved for this part of the workflow.","empty"));return;}
    if(row.id==="interview-runtime") {table(parent,[["Saved status",value.status],["Phase",value.phase],["Follow-ups",value.followups],["Interview round",value._interview_round],["In-flight",value._inflight],["Can retry",value.can_retry]]);if(value.current_question)section(parent,"Current question").append(tree(value.current_question));if(value.scope_checkpoint)section(parent,"Saved checkpoint").append(tree(value.scope_checkpoint));const other=section(parent,"Control records");other.append(tree(value));}
    else if(Array.isArray(value.checks)){table(parent,[["Saved workflow status",value.status],["Version",value.version]]);const n=section(parent,`Saved checks · ${value.checks.length}`);for(const c of value.checks){const block=el("div",undefined,"check-row"),top=el("div");top.append(el("strong",c.label||c.id),pill(c.status));block.append(top,el("p",c.detail||c.description||""));n.append(block);}const more=el("details",undefined,"raw-details");more.append(el("summary","Other workflow data"),tree(Object.fromEntries(Object.entries(value).filter(([k])=>k!=="checks"))));parent.append(more);}
    else if(Array.isArray(value.columns)){table(parent,[["Rows",value.rows],["Bytes",value.size_bytes],["Columns",value.columns.length]]);for(const column of value.columns){const n=section(parent,column.name);table(n,Object.entries(column).filter(([k])=>k!=="name"));}}
    else parent.append(tree(value));
  }
  async function api(path, signal) {
    const response = await fetch(path, {credentials: "same-origin", cache: "no-store", signal: AbortSignal.any([signal, AbortSignal.timeout(20000)])});
    if (response.status === 403) {state.data = null; state.pending = null; $("records").replaceChildren(); $("inspector").replaceChildren(); location.replace("/login?next=/internal"); throw new Error("Administrator sign-in required.");}
    if (!response.ok) throw new Error(`Request failed (${response.status}).`);
    return response.json();
  }
  async function load(apply = false) {
    if (state.refreshing && !apply) return;
    state.controller?.abort(); state.controller = new AbortController(); const signal = state.controller.signal, version = ++state.version, id = state.id;
    state.refreshing = true; $("refresh").disabled = true;
    try {
      const list = await api(`/api/internal/projects?offset=${state.offset}`, signal);
      if (version !== state.version) return;
      const listChanged = JSON.stringify(state.projects) !== JSON.stringify(list.projects) || state.total !== list.total;
      state.projects = list.projects; state.total = list.total;
      if (listChanged) projectList();
      if (id) {
        const data = await api(`/api/internal/projects/${encodeURIComponent(id)}`, signal);
        if (version !== state.version || id !== state.id) return;
        if (!state.data || apply) {state.data = data; state.pending = null; $("new-data").hidden = true; render(true);}
        else if (JSON.stringify(state.data) !== JSON.stringify(data)) {state.pending = data; $("new-data").hidden = false;}
      }
      status(`Checked ${new Date().toLocaleTimeString()} · viewing saved snapshot`);
    } catch (error) {if (version === state.version && error.name !== "AbortError") status(`${error.message}${state.data ? " Saved snapshot retained." : ""}`, true);}
    finally {if (version === state.version) {state.refreshing = false; $("refresh").disabled = false; $("previous").disabled = state.offset === 0; $("next").disabled = state.offset + 50 >= state.total;}}
  }
  $("project-search").addEventListener("input", projectList);
  $("visual-view").addEventListener("click", () => {state.presentation = "visual"; render();});
  $("list-view").addEventListener("click", () => {state.presentation = "list"; render();});
  $("toggle-projects").addEventListener("click", () => {
    const mobile = matchMedia("(max-width: 680px)").matches;
    document.body.classList.toggle(mobile ? "mobile-projects" : "rail-collapsed");
    $("toggle-projects").setAttribute("aria-expanded", String(mobile ? document.body.classList.contains("mobile-projects") : !document.body.classList.contains("rail-collapsed")));
  });
  $("focus-panel").addEventListener("click", () => {const focused = document.body.classList.toggle("inspector-only"); $("focus-panel").setAttribute("aria-pressed", String(focused)); $("focus-panel").textContent = focused ? "Back to split" : "Expand detail";});
  const resizer = $("panel-resizer"), layout = $("review-layout");
  let resizing = false;
  function setSplit(value) {const percent = Math.max(28, Math.min(72, value)); layout.style.setProperty("--list-width", percent + "%"); resizer.setAttribute("aria-valuenow", String(Math.round(percent)));}
  resizer.addEventListener("pointerdown", event => {event.preventDefault(); resizer.focus(); resizing = true; resizer.setPointerCapture(event.pointerId); document.body.classList.add("is-resizing");});
  resizer.addEventListener("pointermove", event => {if (!resizing) return; const bounds = layout.getBoundingClientRect(); setSplit(100 * (event.clientX - bounds.left) / bounds.width);});
  function stopResize() {resizing = false; document.body.classList.remove("is-resizing");}
  resizer.addEventListener("pointerup", stopResize); resizer.addEventListener("pointercancel", stopResize);
  resizer.addEventListener("dblclick", () => setSplit(52));
  resizer.addEventListener("keydown", event => {let value = Number(resizer.getAttribute("aria-valuenow")); if (event.key === "ArrowLeft") value -= 3; else if (event.key === "ArrowRight") value += 3; else if (event.key === "Home") value = 28; else if (event.key === "End") value = 72; else return; event.preventDefault(); setSplit(value);});
  for (const id of ["record-search", "record-filter", "record-order"]) $(id).addEventListener(id === "record-search" ? "input" : "change", () => render());
  $("refresh").addEventListener("click", () => load(true));
  $("load-latest").addEventListener("click", () => {if (!state.pending) return; state.data = state.pending; state.pending = null; $("new-data").hidden = true; render(true);});
  $("previous").addEventListener("click", () => {state.offset = Math.max(0, state.offset - 50); load(true);});
  $("next").addEventListener("click", () => {state.offset += 50; load(true);});
  $("export").addEventListener("click", () => {if (!state.data) return; const blob = new Blob([JSON.stringify(state.data, null, 2)], {type: "application/json"}), href = URL.createObjectURL(blob), a = el("a"); a.href = href; a.download = `${state.data.project.id}-review.json`; a.click(); window.setTimeout(() => URL.revokeObjectURL(href), 1000);});
  window.addEventListener("popstate", () => {const p = new URLSearchParams(location.search), previous = state.id; state.id = p.get("project"); state.section = categories.some(c => c[0] === p.get("view")) ? p.get("view") : "messages"; state.selected[state.section] = p.get("record"); $("record-search").value = ""; $("record-filter").value = ""; if (previous !== state.id) {state.data = null; state.pending = null; $("new-data").hidden = true; projectList(); load(true);} else render(true);});
  fetch("/api/access", {credentials: "same-origin", cache: "no-store"}).then(r => r.json()).then(a => {$("identity").textContent = a.auth_kind === "user" ? "Email workspace · administrator access" : "Email sign-in required";}).catch(() => {});
  setInterval(() => {if ($("auto").checked && !document.hidden && !state.pending) load();}, 5000);
  load(true);
})();
