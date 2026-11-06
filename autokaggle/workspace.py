"""Consent, shared workspaces, session erasure, and answer retraction."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from . import conversation, onboarding_setup
from .store import ANSWERS, now

POLICY_VERSION = "2026-11-06"
NOTICE = (
    "BOLD AutoKaggle stores this session, its files, messages, model records, and generated "
    "artifacts on the service running this app. The hosted service is on Civo in London; local development stores data on the developer’s machine. Chat text and imported source excerpts "
    "are sent to the configured model service through OpenRouter. Attached dataset files and private "
    "test answers are not sent as interview attachments. Text you paste in chat is processed as chat content. "
    "When you ask the agent to look something up, it sends what it reads from your attached documents and links, summaries of your dataset, and "
    "its web search queries to those services. Documents are kept as text for the interview and do not enter the challenge package. Content is retained until you delete "
    "it. The session owner can delete the session, its attached dataset, or an attached document. Deleted live data "
    "and access grants are removed. Downloads and email already received by other people "
    "cannot be recalled. Operator backups require the erasure journal before restoration; "
    "backup copies must remain outside normal use until removed under the operator's "
    "retention policy. A non-content deletion record prevents old backups from restoring erased "
    "sessions. A session handoff shares the research context with its collaborators."
)


def consent_required(project):
    return os.getenv("AUTOKAGGLE_REQUIRE_STORAGE_CONSENT", "1") != "0" and not (
        project.get("_storage_consent", {}).get("version") == POLICY_VERSION
        and project["_storage_consent"].get("accepted_at"))


def require_storage(project):
    if consent_required(project):
        raise HTTPException(428, "Read and accept the data-storage notice before adding research content.")


def consent_view(project):
    return {"version": POLICY_VERSION, "notice": NOTICE, "required": consent_required(project),
            "accepted_at": project.get("_storage_consent", {}).get("accepted_at")}


def clear_artifacts(store, item, *, erase_results=False):
    """Remove all derivative files, revoke old capabilities, and keep the researcher's inputs."""
    directory = store.directory(item["id"])
    for path in directory.iterdir() if directory.exists() else []:
        if path.name in {"dataset.csv", "documents"}:
            continue
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
    store.purge_dependents(item["id"], submissions=erase_results)
    for key in ("workflow", "analysis", "advice", "events", "notices"):
        item[key] = [] if key in {"advice", "events", "notices"} else None
    item.update(prepared=False, status="draft", _participant=None,
                harness={"status": "idle", "stage": "scope"})
    item["revision"] = item.get("revision", 0) + 1


def stamp_answers(project, existing_ids, label):
    for message in project.get("conversation", {}).get("messages", []):
        if message.get("role") == "user" and message.get("id") not in existing_ids:
            message.setdefault("author", label)


def forget_answer(project, message_id):
    """Remove a source and its dependents while preserving independent decisions."""
    old = conversation.ensure_conversation(project)
    target = next((m for m in old["messages"] if m["id"] == message_id and m["role"] == "user"), None)
    if not target:
        raise ValueError("This researcher answer is no longer available.")
    if old.get("_inflight") or old["status"] == "working":
        raise ValueError("Wait for the current response before removing an answer.")
    retained = [copy.deepcopy(m) for m in old["messages"] if m["role"] == "user" and m["id"] != message_id]
    remaining = [m["content"] for m in retained]
    retired = [target["content"]]
    for item in old["items"].values():
        for evidence in item.get("evidence", []):
            if evidence.get("message_id") == message_id:
                retired.extend(evidence.get("quotes", []))
        for record in item.get("requirements", {}).values():
            retired.extend(q for q in conversation._source_quotes(record) if q in target["content"])
    retired = list(dict.fromkeys(q for q in retired if isinstance(q, str) and q.strip()))

    def removed(text):
        if not isinstance(text, str) or not text or any(text in source for source in remaining):
            return False
        return any(text in quote or re.search(r"(?<!\w)" + re.escape(quote) + r"(?!\w)", text)
                   for quote in retired)

    preserved = copy.deepcopy(old["items"])
    changed = set()
    for field, item in preserved.items():
        evidence = item.get("evidence", [])
        item["evidence"] = [e for e in evidence if e.get("message_id") != message_id]
        if len(evidence) != len(item["evidence"]):
            changed.add(field)
        for identifier, record in list(item.get("requirements", {}).items()):
            if any(removed(q) for q in conversation._source_quotes(record)) or removed(record.get("value")):
                del item["requirements"][identifier]
                changed.add(field)
        if removed(item.get("value")):
            item["value"] = "\n".join(line for line in item["value"].split("\n") if not removed(line))
            changed.add(field)
        if removed(item.get("gap")):
            item["gap"] = "A supporting answer was removed. Check this decision again."
        scope = item.get("scope")
        if isinstance(scope, dict) and (any(removed(q) for q in scope.get("source_evidence", [])) or removed(scope.get("summary"))
                or any(removed(r.get("detail")) or any(removed(q) for q in r.get("source_evidence", [])) for r in scope.get("resolutions", []))):
            item.pop("scope", None)
            changed.add(field)
        for key, record in list(item.get("bypasses", {}).items()):
            if removed(record.get("reason")):
                del item["bypasses"][key]
                changed.add(field)
    # A dependent record cannot retain the text of a removed scope decision.
    for item in preserved.values():
        for identifier, record in list(item.get("requirements", {}).items()):
            if any(source.get("field") in changed for source in record.get("scope_sources", [])):
                del item["requirements"][identifier]

    derived = project.get("_chat_derived_answers", {})
    for key, record in list(derived.items()):
        if record.get("source_item") in changed or removed(record.get("value")):
            project.setdefault("answers", {})[key] = ANSWERS.get(key, "")
            derived.pop(key)
    for key, value in project.get("answers", {}).items():
        if removed(value):
            project["answers"][key] = ANSWERS.get(key, "")
    project.pop("_model_traces", None)
    project.pop("_submission_feedback", None)
    project.pop("_setup_private_emails", None)
    # Removing a message keeps its documents visible, so the researcher can resend or remove them.
    waiting = project.setdefault("_new_documents", [])
    waiting.extend(file["id"] for file in target.get("attachments", []) if file["id"] not in waiting)
    imported = project.get("_source_import", {})
    if any(removed(v) for v in imported.get("proposal", {}).values() if isinstance(v, str)):
        imported.pop("proposal", None)
        imported["applied"] = False
    if removed(project.get("brief")):
        project["brief"] = ""
    if removed(project.get("title")) or target["content"].startswith(project.get("title", "__none__")):
        project["title"] = "New challenge"
    setup = onboarding_setup.get(project)
    if setup.get("organizer_email") and setup["organizer_email"] in target["content"]:
        setup["organizer_email"] = ""
    for field in ("competition", "submissions"):
        if any(e.get("message_id") == message_id for e in old["items"].get(field, {}).get("evidence", [])):
            if field == "competition":
                setup["competition_type"] = None
            else:
                setup.update(daily_submission_limit=5, submissions_confirmed=False)
    project["setup"] = setup
    project.pop("conversation", None)
    fresh = conversation.ensure_conversation(project)
    fresh["items"] = preserved
    fresh["_requests"] = copy.deepcopy(old["_requests"])
    removed_request = hashlib.sha256(json.dumps(["message", target["content"]]).encode()).hexdigest()
    for request_id, fingerprint in fresh["_requests"].items():
        if fingerprint == removed_request:
            fresh["_requests"][request_id] = "erased"
    fresh["_interview_round"] = old.get("_interview_round", 1)
    fresh["_interview_call_start"] = old.get("_interview_call_start", 0)
    fresh["_criterion_asks"] = copy.deepcopy(old.get("_criterion_asks", {}))
    for field in changed:
        for criterion in conversation.readiness.REQUIREMENTS.get(field, []):
            fresh["_criterion_asks"].pop(field + "." + criterion["id"], None)
    conversation._apply_requirements(fresh, [])
    onboarding_setup.sync_checklist(project, fresh)
    fresh["messages"].extend(retained)
    conversation._message(fresh, "assistant",
        "I removed that answer and the text derived from it. Your other answers and independent "
        "decisions are kept. I will check the affected requirements before the next question.")
    if retained:
        last = retained[-1]
        fresh.update(phase="interview", _reassessment_required=True,
            _unprocessed=[{"text": last["content"], "message_id": last["id"]}],
            _pending={"kind": "message", "text": last["content"], "message_id": last["id"],
                      "field": None, "requirement_id": None, "was_draft": False})
    return bool(retained)


class Write(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Consent(Write):
    accepted: bool
    version: str


class Confirm(Write):
    confirm: bool


class Join(Write):
    code: str = Field(min_length=1, max_length=80)
    accepted: bool = False


class Forget(Write):
    request_id: str = Field(min_length=1, max_length=100)
    confirm: bool = False
    replacement: str | None = Field(default=None, max_length=12000)


def register(app, store, access, get, editing, conversation_output):
    def owner_only(identifier, request):
        get(identifier, request)
        if not store.owns(identifier, access.owner(request)):
            raise HTTPException(403, "Only the session owner can do this.")

    @app.get("/privacy")
    def privacy_page():
        import html
        return HTMLResponse("<!doctype html><html lang='en'><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width'><title>Data storage — BOLD AutoKaggle</title>"
            "<link rel='stylesheet' href='/static/workspace.css'><main class='privacy-page'>"
            "<h1>Data storage and deletion</h1><p>" + html.escape(NOTICE) + "</p>"
            "<p>Policy version: " + POLICY_VERSION + "</p><p>Open Sessions → Data &amp; privacy "
            "to accept storage, delete an attached dataset, or delete an owned session. "
            "Removing an answer also clears generated records that could retain that text.</p>"
            "<p>Service contact: boldcoscientist@gmail.com.</p>"
            "<p><a href='/'>Return to AutoKaggle</a></p></main></html>")

    @app.get("/api/projects/{project_id}/privacy")
    def privacy(project_id: str, request: Request):
        item = get(project_id, request)
        return {**consent_view(item), "can_delete": store.owns(project_id, access.owner(request))}

    @app.patch("/api/projects/{project_id}/privacy")
    def accept(project_id: str, body: Consent, request: Request):
        if body.accepted is not True or body.version != POLICY_VERSION:
            raise HTTPException(422, "Accept the current storage notice, or delete the session to withdraw.")
        with editing(project_id, request) as item:
            item["_storage_consent"] = {"version": POLICY_VERSION, "accepted_at": now(),
                "accepted_by": hashlib.sha256(access.owner(request).encode()).hexdigest()}
            store.save(item)
            return consent_view(item)

    @app.delete("/api/projects/{project_id}")
    def erase(project_id: str, body: Confirm, request: Request):
        owner_only(project_id, request)
        if body.confirm is not True:
            raise HTTPException(422, "Confirm permanent deletion of this session.")
        with editing(project_id, request):
            store.delete(project_id)
        return {"deleted": True, "project_id": project_id}

    @app.delete("/api/projects/{project_id}/dataset")
    def erase_dataset(project_id: str, body: Confirm, request: Request):
        owner_only(project_id, request)
        if body.confirm is not True:
            raise HTTPException(422, "Confirm deletion of the dataset and its generated artifacts.")
        with editing(project_id, request) as item:
            store.record_erasure(project_id, "content")
            clear_artifacts(store, item, erase_results=True)
            (store.directory(project_id) / "dataset.csv").unlink(missing_ok=True)
            item["dataset"] = None
            item.pop("_model_traces", None)
            state = conversation.ensure_conversation(item)
            state.update(readme=None, _draft_meta=None, _revision_rounds=[])
            store.save(item)
        store.checkpoint()
        return {"deleted": True, "project_id": project_id}

    @app.post("/api/projects/{project_id}/conversation/messages/{message_id}/forget")
    def forget(project_id: str, message_id: str, body: Forget, request: Request):
        if body.confirm is not True:
            raise HTTPException(422, "Confirm removal of the answer and its generated records.")
        if body.replacement is not None and not body.replacement.strip():
            raise HTTPException(422, "Use Remove answer to delete it, or write a replacement.")
        with editing(project_id, request) as item:
            require_storage(item)
            existing_ids = {m["id"] for m in conversation.ensure_conversation(item)["messages"]}
            requests = item.setdefault("_workspace_requests", {})
            fingerprint = hashlib.sha256(json.dumps([message_id, body.replacement]).encode()).hexdigest()
            if body.request_id in requests:
                if requests[body.request_id] != fingerprint:
                    raise HTTPException(409, "This request ID identifies another action.")
                return conversation_output(item)
            try:
                retained = forget_answer(item, message_id)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            requests[body.request_id] = fingerprint
            item["_workspace_requests"] = dict(list(requests.items())[-200:])
            store.record_erasure(project_id, "content")
            clear_artifacts(store, item, erase_results=True)
            store.save(item)
            if body.replacement is not None:
                item["conversation"].update(_pending=None, _unprocessed=[], _reassessment_required=True)
                conversation.submit_message(item, body.replacement.strip(),
                    "replacement-" + hashlib.sha256(body.request_id.encode()).hexdigest(), reserve=store.save)
                conversation.sync_legacy_answers(item)
                stamp_answers(item, existing_ids, store.author_label(project_id, access.owner(request)))
                store.save(item)
            elif retained:
                conversation._process_message(item, reserve=store.save)
                conversation.sync_legacy_answers(item)
                store.save(item)
            result = conversation_output(item)
        store.checkpoint()
        return result

    @app.get("/api/projects/{project_id}/attempts")
    def attempts(project_id: str, request: Request):
        get(project_id, request)
        with store.connection() as con:
            rows = con.execute("SELECT version, day, result FROM draft_submissions WHERE project=? ORDER BY rowid DESC LIMIT 20", (project_id,)).fetchall()
        return {"attempts": [{"version": row[0], "day": row[1], "result": json.loads(row[2])} for row in rows],
                "detail": "Development results only. Final test scores remain private."}

    @app.post("/api/projects/{project_id}/iterate")
    def iterate(project_id: str, body: Forget, request: Request):
        with editing(project_id, request) as item:
            with store.connection() as con:
                rows = con.execute("SELECT version, day, result FROM draft_submissions WHERE project=? ORDER BY rowid DESC LIMIT 10", (project_id,)).fetchall()
            item["_submission_feedback"] = [{"version": r[0], "day": r[1], "result": json.loads(r[2])} for r in rows]
            try:
                conversation.begin_revision(item, body.request_id, reserve=store.save)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            store.save(item)
            return conversation_output(item)

    @app.get("/api/projects/{project_id}/handoff")
    def members(project_id: str, request: Request):
        get(project_id, request)
        own = store.owns(project_id, access.owner(request))
        with store.connection() as con:
            rows = con.execute("SELECT c.id,c.joined,c.member=?,COALESCE(r.name,'') FROM collaborators c LEFT JOIN researcher_profiles r ON r.account=c.member WHERE c.project=? ORDER BY c.joined",
                               (access.owner(request), project_id)).fetchall()
        return {"can_manage": own, "members": [{"id": r[0], "joined_at": r[1], "is_you": bool(r[2]), "name": r[3]} for r in rows]}

    @app.post("/api/projects/{project_id}/handoff")
    def issue_handoff(project_id: str, request: Request):
        owner_only(project_id, request)
        with editing(project_id, request) as item:
            require_storage(item)
            code = secrets.token_hex(12).upper()
            expiry = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
            with store.connection() as con:
                con.execute("DELETE FROM handoff_codes WHERE project=?", (project_id,))
                con.execute("INSERT INTO handoff_codes VALUES (?,?,?,0)",
                            (hashlib.sha256(code.encode()).hexdigest(), project_id, expiry))
        return {"code": "-".join(code[i:i+6] for i in range(0, len(code), 6)), "expires_at": expiry,
                "detail": "Single use within 24 hours. This gives ongoing edit access to this session. The owner can revoke it."}

    @app.post("/api/handoffs/redeem")
    def redeem(body: Join, request: Request):
        access.require_create(request)
        actor = access.owner(request)
        if not actor or not body.accepted:
            raise HTTPException(422, "Sign in and accept the storage and collaboration notice before joining.")
        code = re.sub(r"[-\s]", "", body.code).upper()
        if not re.fullmatch(r"[0-9A-F]{24}", code):
            code = "invalid"
        digest = hashlib.sha256(code.encode()).hexdigest()
        current = now()
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        with store.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            con.execute("DELETE FROM handoff_attempts WHERE at<?", (cutoff,))
            count = con.execute("SELECT count(*) FROM handoff_attempts WHERE actor=? AND at>?", (actor, cutoff)).fetchone()[0]
            if count >= 20:
                raise HTTPException(429, "Too many handoff attempts. Try again in one hour.")
            con.execute("INSERT INTO handoff_attempts VALUES (?,?)", (actor, current))
            row = con.execute("SELECT project FROM handoff_codes WHERE digest=? AND expires>? AND used=0", (digest, current)).fetchone()
        if not row:
            raise HTTPException(404, "The handoff code is invalid, used, expired, or revoked.")
        project_id = row[0]
        lock = store.lock(project_id)
        if not lock.acquire(blocking=False):
            raise HTTPException(409, "This session is busy. Try the same code after the current action.")
        try:
            with store.connection() as con:
                con.execute("BEGIN IMMEDIATE")
                row = con.execute("SELECT 1 FROM handoff_codes JOIN projects ON projects.id=handoff_codes.project WHERE digest=? AND expires>? AND used=0", (digest, now())).fetchone()
                if not row:
                    raise HTTPException(404, "The handoff code is no longer available.")
                if not store.owns(project_id, actor):
                    con.execute("INSERT OR IGNORE INTO collaborators VALUES (?,?,?,?,?)",
                        (secrets.token_hex(16), project_id, actor, now(), POLICY_VERSION))
                con.execute("UPDATE handoff_codes SET used=1 WHERE digest=?", (digest,))
            return {"project_id": project_id, "redirect": "/?project=" + project_id}
        finally:
            lock.release()

    @app.delete("/api/projects/{project_id}/handoff/{member_id}")
    def revoke(project_id: str, member_id: str, request: Request):
        with editing(project_id, request):
            actor = access.owner(request)
            with store.connection() as con:
                if member_id == "codes":
                    owner_only(project_id, request)
                    con.execute("DELETE FROM handoff_codes WHERE project=?", (project_id,))
                elif store.owns(project_id, actor):
                    con.execute("DELETE FROM collaborators WHERE project=? AND id=?", (project_id, member_id))
                    con.execute("DELETE FROM submission_tokens WHERE project=?", (project_id,))
                else:
                    removed = con.execute("DELETE FROM collaborators WHERE project=? AND id=? AND member=?", (project_id, member_id, actor))
                    if removed.rowcount:
                        con.execute("DELETE FROM submission_tokens WHERE project=?", (project_id,))
            return {"revoked": True}
