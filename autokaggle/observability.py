"""Bounded internal model records. Never included in organizer responses."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
import re
import time
import uuid
from fastapi import Request, Query

from .store import now

LIMIT = 30
TEXT_LIMIT = 24000
PRIVATE_KEYS = {"organizer_email", "_setup_private_emails", "_participant", "_seed", "owner", "participant"}


def scrub(value):
    """Remove credentials and correspondence addresses from diagnostic records."""
    if isinstance(value, dict):
        return {k: ("[redacted]" if k in PRIVATE_KEYS or re.search(r"password|secret|credential|access_code|api_key|authorization|cookie|encrypted|token$", k, re.I)
                    else scrub(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r"(?<![\w.+-])[\w.+-]{1,64}@[\w.-]{1,253}\.[A-Za-z]{2,63}", "[private email]", value)
        for name in ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "AUTOKAGGLE_ADMIN_ACCESS_CODE"):
            secret = os.getenv(name)
            if secret:
                value = value.replace(secret, "[redacted credential]")
        value = re.sub(r"(?i)\bBearer\s+\S+|\bsk-[A-Za-z0-9_-]+", "[redacted credential]", value)
        value = re.sub(r"(?i)([?&](?:token|key|code|secret)=)[^\s&#\"<>]+", r"\1[redacted]", value)
        return value
    return value


def bounded(value):
    text = scrub(str(value))
    return text[:TEXT_LIMIT] + ("\n[truncated]" if len(text) > TEXT_LIMIT else "")


def response_record(response):
    # Select text only; opaque/encrypted reasoning and provider metadata are excluded.
    reasoning = []
    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", None) == "reasoning":
            for part in (getattr(item, "summary", []) or []) + (getattr(item, "content", []) or []):
                text = getattr(part, "text", None)
                if isinstance(text, str):
                    reasoning.append(text)
    usage = getattr(response, "usage", None)
    details = getattr(usage, "output_tokens_details", None)
    return {"provider_status": getattr(response, "status", None),
            "model": getattr(response, "model", None),
            "output": bounded(getattr(response, "output_text", "") or ""),
            "reasoning": bounded("\n".join(reasoning)),
            "reasoning_available": bool(reasoning),
            "usage": {"input_tokens": getattr(usage, "input_tokens", None),
                      "output_tokens": getattr(usage, "output_tokens", None),
                      "reasoning_tokens": getattr(details, "reasoning_tokens", None)}}


@contextmanager
def model_call(project, kind, instructions, provider_input, effort, reserve=None):
    """Persist before/after a call so an interrupted request remains visible."""
    trace = {"id": uuid.uuid4().hex, "kind": kind, "started_at": now(),
             "status": "running", "model": os.getenv("AUTOKAGGLE_MODEL", "gpt-6.1-sol"),
             "effort": effort, "instructions": bounded(instructions), "input": bounded(provider_input)}
    state = project.get("conversation") or {}
    pending = state.get("_pending") or {}
    trace["trigger"] = {"message_id": pending.get("message_id"), "field": pending.get("field"),
                        "requirement_id": pending.get("requirement_id"), "revision": project.get("revision"),
                        "interview_round": state.get("_interview_round")}
    trace["capture"] = {key: {"original_chars": len(scrub(str(value))), "limit_chars": TEXT_LIMIT,
                               "truncated": len(scrub(str(value))) > TEXT_LIMIT}
                        for key, value in (("instructions", instructions), ("input", provider_input))}
    records = project.setdefault("_model_traces", [])
    records.append(trace)
    del records[:-LIMIT]
    started = time.monotonic()
    if reserve:
        reserve(project)
    try:
        yield trace
    except Exception as exc:
        trace.update(status="failed", error_type=type(exc).__name__)
        raise
    else:
        trace["status"] = "completed" if trace.get("provider_status") == "completed" else "incomplete"
    finally:
        trace.update(finished_at=now(), duration_ms=round((time.monotonic() - started) * 1000))
        if reserve:
            reserve(project)


def mark_validation(project, previous_id, status, attempt, code=None):
    """Annotate only a call created in this validation attempt, never a legacy call."""
    traces = project.get("_model_traces", [])
    if traces and traces[-1].get("id") != previous_id:
        traces[-1]["validation"] = {"status": status, "attempt": attempt, "code": code, "at": now()}


def project_detail(item):
    allowed = ("id", "title", "brief", "created_at", "updated_at", "status", "revision", "answers",
               "design", "dataset", "analysis", "advice", "events", "harness", "prepared", "notices",
               "conversation", "setup", "workflow", "_model_calls", "_model_traces")
    return scrub({key: item[key] for key in allowed if key in item})


def review_data(store, item):
    """Presentation metadata and bounded ledgers, with no saved-project mutation."""
    from .conversation import ITEMS
    from .readiness import REQUIREMENTS
    with store.connection() as con:
        rows = con.execute("SELECT version, request, day, team, result FROM draft_submissions WHERE project=? ORDER BY day DESC, rowid DESC LIMIT 200", (item["id"],)).fetchall()
        total = con.execute("SELECT count(*) FROM draft_submissions WHERE project=?", (item["id"],)).fetchone()[0]
        invitations = con.execute("SELECT version, expires, used FROM review_tokens WHERE project=? ORDER BY expires DESC LIMIT 100", (item["id"],)).fetchall()
    return scrub({"field_definitions": [{"id": f[0], "label": f[1], "group": f[2]} for f in ITEMS],
                  "requirement_definitions": REQUIREMENTS,
                  "submissions": {"total": total, "limit": 200, "records": [
                      {"version": r[0], "request_id": r[1], "day": r[2], "team": r[3], "result": json.loads(r[4])} for r in rows]},
                  "review_invitations": {"limit": 100, "records": [
                      {"version": r[0], "expires": r[1], "used": bool(r[2])} for r in invitations]},
                  "sources": {"project": "projects.body (saved snapshot)", "submissions": "draft_submissions",
                              "review_invitations": "review_tokens (metadata only)"}})


def register(app, access, store, static_dir):
    from fastapi import HTTPException
    from fastapi.responses import FileResponse, RedirectResponse

    def require_admin(request):
        if not access.is_admin(request):
            raise HTTPException(403, "Administrator sign-in required.")

    @app.get("/internal")
    def internal_page(request: Request):
        if not access.is_admin(request):
            return RedirectResponse("/login?next=/internal", status_code=303)
        return FileResponse(static_dir / "internal.html")

    @app.get("/api/internal/projects")
    def projects(request: Request, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
        require_admin(request)
        # Do not deserialize every project's full model input/output on a list request.
        with store.connection() as con:
            total = con.execute("SELECT count(*) FROM projects").fetchone()[0]
            rows = con.execute("SELECT id, updated_at, json_extract(body, '$.title'), json_extract(body, '$.status'), json_extract(body, '$._model_calls'), json_extract(body, '$.conversation.status') FROM projects ORDER BY updated_at DESC, id LIMIT ? OFFSET ?", (limit, offset)).fetchall()
        return {"total": total, "limit": limit, "offset": offset, "projects": [
            {"id": r[0], "updated_at": r[1], "title": scrub(r[2]), "status": r[3], "model_calls": r[4] or 0, "conversation_status": r[5]}
            for r in rows]}

    @app.get("/api/internal/projects/{project_id}")
    def detail(project_id: str, request: Request):
        require_admin(request)
        with store.connection() as con:
            row = con.execute("SELECT body FROM projects WHERE id=?", (project_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Challenge not found.")
        item = json.loads(row[0])
        return {"project": project_detail(item), "review": review_data(store, item), "trace_limit": LIMIT,
                "reasoning_note": "Only reasoning text returned by the provider is recorded. Hidden reasoning is unavailable. Older calls have no trace; records retain the latest 30 calls, with each text field capped at 24,000 characters."}
