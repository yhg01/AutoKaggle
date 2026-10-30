"""Local organizer workbench and bounded onboarding harness."""
from __future__ import annotations

from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import copy
import os
from pathlib import Path
import secrets
from typing import Literal
from urllib.parse import quote, urlparse

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import advisor, conversation, onboarding_setup, workflow, notifications, submissions
from .access import AccessGate
from .email_auth import USER_COOKIE
from .core import datasets
from .core.datasets import profile_csv, analyze_dataset
from .examples import load_example
from .exports import description, package
from .policy import brief_checks, checklist, summarize
from .store import Store, now, public_project
from .runner import RunnerUnavailable

HERE = Path(__file__).parent


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_max_length=2000)


class AnswerPatch(StrictModel):
    objective: str | None = None
    prediction_unit: str | None = None
    success_criterion: str | None = None
    data_origin: Literal["private", "public", "synthetic", "unknown"] | None = None
    labels_public: Literal["yes", "no", "unknown"] | None = None
    rights: Literal["yes", "unknown"] | None = None
    compute_budget: str | None = None
    token_budget: str | None = None


class DesignPatch(StrictModel):
    target: str | None = None
    task: Literal["classification", "regression"] | None = None
    metric: Literal["accuracy", "balanced_accuracy", "roc_auc", "rmse", "mae"] | None = None
    split: Literal["random", "group", "time"] | None = None
    group_column: str | None = None
    time_column: str | None = None
    exclude_columns: list[str] | None = Field(default=None, max_length=200)
    test_fraction: float | None = Field(default=None, ge=0.1, le=0.4)


class ProjectPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, max_length=180)
    brief: str | None = Field(default=None, max_length=12000)
    answers: AnswerPatch | None = None
    design: DesignPatch | None = None


class AdviceRequest(StrictModel):
    kind: Literal["conversation", "review"] = "conversation"


class ExampleRequest(StrictModel):
    name: Literal["materials", "leakage", "noise"]


class PrepareRequest(StrictModel):
    acknowledge_review: bool = False


class ConversationAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=8, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")


class ConversationMessage(ConversationAction):
    message: str = Field(min_length=1, max_length=12000)


class RequirementBypass(ConversationAction):
    model_config = ConfigDict(extra="forbid", strict=True)
    field: str = Field(min_length=1, max_length=40)
    requirement_id: str = Field(min_length=1, max_length=80)
    reason: str = Field(default="", max_length=2000)
    remove: bool = False


class ScopeResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    requirement_id: str = Field(min_length=1, max_length=80)
    mode: Literal["confirmed", "delegated", "exception"]
    detail: str = Field(min_length=1, max_length=2000)


class ScopeDecision(ConversationAction):
    model_config = ConfigDict(extra="forbid", strict=True)
    field: str = Field(min_length=1, max_length=40)
    summary: str = Field(default="", max_length=4000)
    resolutions: list[ScopeResolution] = Field(default_factory=list, max_length=10)
    remove: bool = False


class SetupPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    competition_type: Literal["prediction", "code"] | None = None
    daily_submission_limit: int | None = Field(default=None, ge=1, le=1000)
    submissions_confirmed: bool | None = None
    organizer_email: str | None = Field(default=None, max_length=254)


class ReviewLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=30, max_length=100)


class PredictionSubmission(ConversationAction):
    predictions_csv: str = Field(min_length=1, max_length=5_000_000)


class CodeSubmission(ConversationAction):
    source_code: str = Field(min_length=1, max_length=262_144)


def create_app(data_dir: Path | None = None):
    access = AccessGate()
    store = Store(data_dir or Path(os.getenv("AUTOKAGGLE_DATA_DIR", str(HERE / "data"))))
    access.attach_store(store)
    app = FastAPI(title="AutoKaggle", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.access = access
    app.state.store = store
    notifications.initialize(store)
    submissions.initialize(store)
    pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="autokaggle")
    app.state.pool = pool
    hosts = ["localhost", "127.0.0.1", "[::1]", "testserver"]
    hosts += [h.strip() for h in os.getenv("AUTOKAGGLE_ALLOWED_HOSTS", "").split(",") if h.strip()]
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)

    @app.middleware("http")
    async def boundaries(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin and urlparse(origin).netloc != request.headers.get("host"):
                return PlainTextResponse("Cross-origin writes are not allowed", status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        if request.url.path.startswith(("/api/", "/challenge/")) or request.url.path in {"/", "/workbench", "/login", "/review"}:
            response.headers["Cache-Control"] = "no-store"
        elif request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    access.register(app, HERE / "static")

    @app.get("/healthz")
    def health():
        return {"status": "ok"}

    def owner(request):
        return access.owner(request)

    def get(project_id, request):
        item = store.get(project_id, owner(request))
        if not item:
            raise HTTPException(404, "Challenge not found in this organizer session.")
        return item

    def output(item):
        result = public_project(item)
        if "conversation" in item:
            result["conversation"] = conversation.conversation_view(item)
        result["checklist"] = checklist(item)
        return result

    def event(item, stage, status, detail):
        item["events"].append({"stage": stage, "status": status, "detail": detail, "at": now()})
        item["events"] = item["events"][-120:]

    def invalidate(item):
        item["analysis"] = None
        item["prepared"] = False
        item["_participant"] = None
        item["status"] = "draft"
        item["revision"] += 1
        item["harness"] = {"status": "idle", "stage": "scope"}
        for name in ("researcher.zip", "organizer.zip"):
            (store.directory(item["id"]) / name).unlink(missing_ok=True)

    @contextmanager
    def editing(project_id, request):
        get(project_id, request)
        lock = store.lock(project_id)
        if not lock.acquire(blocking=False):
            raise HTTPException(409, "This challenge is busy. Wait for the current action to finish.")
        try:
            yield get(project_id, request)
        finally:
            lock.release()

    def analyze(item):
        if not item.get("dataset"):
            raise ValueError("Attach a CSV before running the data audit.")
        if conversation.sync_legacy_answers(item):
            invalidate(item)
        result = analyze_dataset(store.directory(item["id"]) / "dataset.csv", item["design"], item["answers"], item["_seed"])
        result["checks"] = brief_checks(item) + result["checks"]
        result["summary"] = summarize(result["checks"])
        item["analysis"] = result
        item["status"] = "needs_changes" if result["summary"]["blockers"] else "ready_for_review"
        event(item, "audit", "complete", f"{result['summary']['blockers']} blockers and {result['summary']['warnings']} warnings.")
        base = result.get("baseline", {})
        event(item, "trial", base.get("status", "unavailable"), base.get("detail", "Development trial finished."))

    def advice(item, kind):
        note = advisor.advise(item, kind, reserve=store.save)
        if advisor.apply_supported_updates(item, note):
            invalidate(item)
        note["revision"] = item["revision"]
        item["advice"].append(note)
        item["advice"] = item["advice"][-20:]
        item["notices"] = [note["notice"]] if note.get("notice") else []
        event(item, "review" if kind == "review" else "scope", "complete", f"{note['mode'].capitalize()} advice recorded.")
        return note

    def run_harness(project_id, organizer):
        item = store.get(project_id, organizer)
        try:
            item["harness"] = {"status": "running", "stage": "scope"}
            event(item, "scope", "running", "Read the brief and identify missing decisions.")
            store.save(item)
            advice(item, "conversation")
            item["harness"] = {"status": "running", "stage": "audit"}
            store.save(item)
            if item.get("dataset"):
                event(item, "audit", "running", "Check data, split independence, and development performance.")
                store.save(item)
                analyze(item)
            else:
                event(item, "audit", "waiting", "Attach a CSV to continue the data audit and trial.")
            item["harness"] = {"status": "running", "stage": "review"}
            store.save(item)
            advice(item, "review")
            item["harness"] = {"status": "complete", "stage": "review"}
            event(item, "review", "complete", "Onboarding run finished. Review the findings and resolve open decisions.")
        except Exception as exc:
            item["harness"] = {"status": "failed", "stage": "review", "error": "The run stopped. Your saved work is available. Correct the issue and retry."}
            event(item, "run", "failed", f"The run stopped ({type(exc).__name__}).")
        finally:
            store.save(item)
            store.lock(project_id).release()

    @app.get("/api/config")
    def config(request: Request):
        return {"mode": "model" if advisor.configured() else "rules", "model": advisor.model_name(), "max_upload_mb": datasets.MAX_UPLOAD_MB, "max_upload_bytes": datasets.MAX_BYTES, "version": "0.3.0",
                "private_mode": access.enabled, "can_create_projects": access.can_create(request),
                "auth_kind": access.auth_kind(request)}

    @app.get("/api/projects")
    def projects(request: Request):
        return {"projects": store.list(owner(request))}

    @app.post("/api/projects")
    def create(body: ProjectPatch, request: Request, response: Response):
        access.require_create(request)
        organizer = owner(request)
        if not organizer or len(organizer) < 32 or len(organizer) > 100:
            organizer = secrets.token_urlsafe(32)
            response.set_cookie("autokaggle_owner", organizer, httponly=True, samesite="lax", secure=access.secure_cookie(request), max_age=60*60*24*90)
        item = store.create(organizer, body.title or "", body.brief or "")
        if body.answers:
            item["answers"].update(body.answers.model_dump(exclude_none=True))
        if body.design:
            item["design"].update(body.design.model_dump(exclude_none=True))
        conversation.ensure_conversation(item)
        identity = access.user(request)
        if identity:
            onboarding_setup.update(item, {"organizer_email": identity["email"]}, source="verified_email")
        event(item, "scope", "created", "A new challenge workspace is ready.")
        store.save(item)
        return output(item)

    @app.get("/api/projects/{project_id}")
    def read(project_id: str, request: Request):
        return output(get(project_id, request))

    def conversation_output(item, working=False):
        result = conversation.conversation_view(item)
        result.update(project_id=item["id"], title=item["title"],
                      mode="model" if advisor.configured() else "rules",
                      contact_required=not bool(onboarding_setup.get(item)["organizer_email"]))
        if working:
            result["status"] = "working"
            result["can_retry"] = False
        return result

    def require_contact(item):
        if not onboarding_setup.get(item)["organizer_email"]:
            raise HTTPException(422, "Enter an organizer email before starting the interview.")

    @app.get("/api/projects/{project_id}/setup")
    def get_setup(project_id: str, request: Request):
        item = get(project_id, request)
        return {"setup": onboarding_setup.get(item), "conversation": conversation_output(item)}

    @app.patch("/api/projects/{project_id}/setup")
    def update_setup(project_id: str, body: SetupPatch, request: Request):
        with editing(project_id, request) as item:
            old_email = onboarding_setup.get(item)["organizer_email"]
            try:
                onboarding_setup.update(item, body.model_dump(exclude_none=True))
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            if old_email != onboarding_setup.get(item)["organizer_email"]:
                with store.connection() as con:
                    con.execute("DELETE FROM review_grants WHERE project=?", (project_id,))
                    con.execute("DELETE FROM review_tokens WHERE project=?", (project_id,))
            store.save(item)
            return {"setup": onboarding_setup.get(item), "conversation": conversation_output(item)}

    @app.get("/api/projects/{project_id}/workflow")
    def get_workflow(project_id: str, request: Request):
        return workflow.view(get(project_id, request))

    @app.post("/api/projects/{project_id}/workflow")
    def build_workflow(project_id: str, request: Request):
        with editing(project_id, request) as item:
            require_contact(item)
            try:
                if conversation.sync_legacy_answers(item):
                    invalidate(item)
                workflow.build(item, store.directory(project_id))
                store.save(item)
                notifications.send_review(store, item)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            return workflow.view(item)

    @app.post("/api/projects/{project_id}/workflow/notify")
    def notify_organizer(project_id: str, request: Request):
        with editing(project_id, request) as item:
            notifications.send_review(store, item, renew=True)
            return workflow.view(item)

    def built(project_id, request):
        item = get(project_id, request)
        if workflow.view(item)["status"] in {"stale", "not_built"}:
            raise HTTPException(409, "Build the current draft before opening its artifacts.")
        return store.directory(project_id) / "workflow"

    @app.get("/api/projects/{project_id}/workflow/package")
    def workflow_package(project_id: str, request: Request):
        directory = built(project_id, request)
        return FileResponse(directory / "researcher.zip", filename="autokaggle-research.zip", media_type="application/zip")

    @app.get("/api/projects/{project_id}/workflow/preview")
    def workflow_preview(project_id: str, request: Request):
        import html
        directory = built(project_id, request)
        result = workflow.view(get(project_id, request))
        code_mode = onboarding_setup.get(get(project_id, request))["competition_type"] == "code"
        code_ready = any(c["id"] == "runner" and c["status"] == "pass" for c in result["checks"])
        file_label = "Python source" if code_mode else "Prediction file"
        file_accept = ".py,text/x-python,text/plain" if code_mode else ".csv,text/csv"
        submission_help = ("Submit one Python file, up to 256 KiB. It runs with private inputs on the Civo sandbox. Only the development score is returned."
            if code_ready else "The Civo code trial has not passed. Code submissions are disabled.") if code_mode else "Submit a CSV with development predictions. Final test scores remain private."
        body = (directory / "researcher/index.html").read_text().replace('href="site.css"', f'href="/api/projects/{project_id}/workflow/site.css"')
        checks_html = "".join(f"<li><strong>{html.escape(c['label'])}</strong>: {html.escape(c['detail'])} ({html.escape(c['status'])})</li>" for c in result["checks"])
        controls = f'''<h2>Organizer review</h2><ul>{checks_html}</ul>
          <p><a href="/api/projects/{project_id}/workflow/package">Download research ZIP</a> ·
          <a href="/?project={project_id}&amp;view=review">Review and request changes</a></p>
          <section id="submission" data-project="{project_id}" data-version="{result['version']}" data-type="{'code' if code_mode else 'prediction'}">
          <h2>Try a development submission</h2>
          <p>{submission_help}</p>
          <label>{file_label} <input type="file" id="prediction-file" accept="{file_accept}"></label>
          <button type="button" id="submit-predictions" {'disabled' if code_mode and not code_ready else ''}>Submit {'code' if code_mode else 'predictions'}</button>
          <button type="button" id="new-submission-attempt" hidden>New attempt</button>
          <p id="submission-result" role="status"></p>
          <h2>Submission access for an agent</h2>
          <p>Create a token that can only submit development attempts. It cannot open organizer pages or download private data.
          Keep the token outside the ZIP. A new token replaces the prior preview token and keeps the same daily allowance.</p>
          <button type="button" id="create-submission-token">Create submission token</button>
          <pre id="submission-token" role="status"></pre></section>
          <script src="/static/review.js" defer></script>'''
        if "<!-- ORGANIZER_CONTROLS -->" in body:
            body = body.replace("<!-- ORGANIZER_CONTROLS -->", controls)
        else:
            body = body.replace("</main>", controls + "</main>")
        return HTMLResponse(body)

    @app.get("/api/projects/{project_id}/workflow/site.css")
    def workflow_css(project_id: str, request: Request):
        return FileResponse(built(project_id, request) / "researcher/site.css", media_type="text/css")

    @app.post("/api/projects/{project_id}/workflow/submissions")
    def development_submission(project_id: str, body: PredictionSubmission, request: Request):
        with editing(project_id, request) as item:
            try:
                return submissions.submit(store, item, body.request_id, body.predictions_csv)
            except submissions.LimitReached as exc:
                raise HTTPException(429, str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc

    @app.post("/api/projects/{project_id}/workflow/code-submissions")
    def development_code_submission(project_id: str, body: CodeSubmission, request: Request):
        with editing(project_id, request) as item:
            try:
                return submissions.submit_code(store, item, body.request_id, body.source_code)
            except RunnerUnavailable as exc:
                raise HTTPException(503, str(exc)) from exc
            except submissions.LimitReached as exc:
                raise HTTPException(429, str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc

    @app.post("/api/projects/{project_id}/workflow/access")
    def draft_submission_access(project_id: str, request: Request):
        with editing(project_id, request) as item:
            try:
                token = submissions.issue_token(store, item)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            endpoint = "code-submissions" if onboarding_setup.get(item)["competition_type"] == "code" else "submissions"
            return {"token": token, "submission_url": f"/api/evaluation/{project_id}/{endpoint}",
                    "detail": "Submission-only access. This replaces the prior preview token. Keep it outside the research package."}

    @app.post("/api/evaluation/{project_id}/submissions")
    def token_submission(project_id: str, body: PredictionSubmission, request: Request):
        return evaluate_token(project_id, body.request_id, body.predictions_csv, request, "prediction")

    @app.post("/api/evaluation/{project_id}/code-submissions")
    def token_code_submission(project_id: str, body: CodeSubmission, request: Request):
        return evaluate_token(project_id, body.request_id, body.source_code, request, "code")

    def evaluate_token(project_id, request_id, payload, request, kind):
        header = request.headers.get("authorization", "")
        token = header[7:] if header.startswith("Bearer ") else ""
        authorized = submissions.authenticate(store, project_id, token)
        if not authorized:
            raise HTTPException(401, "A valid submission-only token is required.")
        lock = store.lock(project_id)
        if not lock.acquire(blocking=False):
            raise HTTPException(409, "This challenge is busy. Retry the same request ID shortly.")
        try:
            authorized = submissions.authenticate(store, project_id, token)
            if not authorized:
                raise HTTPException(401, "The draft changed. Request a new submission token.")
            submit = submissions.submit_code if kind == "code" else submissions.submit
            return submit(store, authorized[0], request_id, payload, authorized[1])
        except RunnerUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        except submissions.LimitReached as exc:
            raise HTTPException(429, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        finally:
            lock.release()

    @app.get("/review")
    def review_login_page():
        return FileResponse(HERE / "static/review.html")

    @app.post("/api/review/exchange")
    def review_login(body: ReviewLogin, request: Request, response: Response):
        try:
            session, project_id = notifications.redeem(store, body.token, owner(request))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if USER_COOKIE in request.cookies and not access.user(request):
            response.delete_cookie(USER_COOKIE, path="/", httponly=True,
                                   samesite="lax", secure=access.secure_cookie(request))
        response.set_cookie("autokaggle_owner", session, httponly=True, samesite="lax", secure=access.secure_cookie(request), max_age=60*60*24*7)
        return {"redirect": f"/?project={project_id}&view=review"}

    @app.get("/api/projects/{project_id}/conversation")
    def read_conversation(project_id: str, request: Request):
        item = get(project_id, request)
        return conversation_output(item, store.lock(project_id).locked())

    def change_conversation(project_id, request, operation, *args):
        with editing(project_id, request) as item:
            require_contact(item)
            old_email = onboarding_setup.get(item)["organizer_email"]
            old_scopes = copy.deepcopy({key: value.get("scope") for key, value in conversation.ensure_conversation(item)["items"].items()})
            invalidated = False
            def save_chat(changed):
                nonlocal invalidated
                scopes = {key: value.get("scope") for key, value in conversation.ensure_conversation(changed)["items"].items()}
                if not invalidated and scopes != old_scopes:
                    invalidate(changed)
                    invalidated = True
                if old_email != onboarding_setup.get(changed)["organizer_email"]:
                    with store.connection() as con:
                        con.execute("DELETE FROM review_grants WHERE project=?", (project_id,))
                        con.execute("DELETE FROM review_tokens WHERE project=?", (project_id,))
                store.save(changed)
            try:
                operation(item, *args, reserve=save_chat)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            new_scopes = {key: value.get("scope") for key, value in conversation.ensure_conversation(item)["items"].items()}
            legacy_changed = conversation.sync_legacy_answers(item)
            if not invalidated and (legacy_changed or old_scopes != new_scopes):
                invalidate(item)
                invalidated = True
            save_chat(item)
            return conversation_output(item)

    @app.post("/api/projects/{project_id}/conversation/messages")
    def chat_message(project_id: str, body: ConversationMessage, request: Request):
        if not body.message.strip():
            raise HTTPException(422, "Write a message before sending it.")
        return change_conversation(project_id, request, conversation.submit_message,
                                   body.message.strip(), body.request_id)

    @app.post("/api/projects/{project_id}/conversation/skip")
    def chat_skip(project_id: str, body: ConversationAction, request: Request):
        return change_conversation(project_id, request, conversation.skip_question, body.request_id)

    @app.post("/api/projects/{project_id}/conversation/draft")
    def chat_draft(project_id: str, body: ConversationAction, request: Request):
        return change_conversation(project_id, request, conversation.make_readme, body.request_id)

    @app.post("/api/projects/{project_id}/conversation/retry")
    def chat_retry(project_id: str, body: ConversationAction, request: Request):
        return change_conversation(project_id, request, conversation.retry_turn, body.request_id)

    @app.post("/api/projects/{project_id}/conversation/revision")
    def chat_revision(project_id: str, body: ConversationAction, request: Request):
        return change_conversation(project_id, request, conversation.begin_revision, body.request_id)

    @app.post("/api/projects/{project_id}/conversation/continue")
    def chat_continue(project_id: str, body: ConversationAction, request: Request):
        return change_conversation(project_id, request, conversation.continue_interview, body.request_id)

    @app.post("/api/projects/{project_id}/conversation/requirements/bypass")
    def chat_requirement_bypass(project_id: str, body: RequirementBypass, request: Request):
        return change_conversation(project_id, request, conversation.set_requirement_bypass,
                                   body.field, body.requirement_id, body.reason, body.request_id, body.remove)

    @app.post("/api/projects/{project_id}/conversation/scope")
    def chat_scope(project_id: str, body: ScopeDecision, request: Request):
        return change_conversation(project_id, request, conversation.set_scope,
                                   body.field, body.summary, [entry.model_dump() for entry in body.resolutions], body.request_id, body.remove)

    @app.get("/api/projects/{project_id}/conversation/readme.md")
    def chat_readme(project_id: str, request: Request):
        result = conversation.conversation_view(get(project_id, request))
        if not result.get("readme"):
            raise HTTPException(404, "Create the challenge README first.")
        return PlainTextResponse(result["readme"], media_type="text/markdown",
                                 headers={"Content-Disposition": 'attachment; filename="challenge-README.md"'})

    @app.patch("/api/projects/{project_id}")
    def patch(project_id: str, body: ProjectPatch, request: Request):
        with editing(project_id, request) as item:
            old = copy.deepcopy(item)
            for key in ("title", "brief"):
                value = getattr(body, key)
                if value is not None:
                    item[key] = value.strip()
            for key in ("answers", "design"):
                value = getattr(body, key)
                if value:
                    item[key].update(value.model_dump(exclude_none=True))
            conversation.sync_legacy_answers(item, manual_fields=body.answers.model_dump(exclude_none=True).keys() if body.answers else ())
            if item != old:
                invalidate(item)
                event(item, "scope", "updated", "Changes saved. Previous audit and packages were invalidated.")
                store.save(item)
            return output(item)

    @app.post("/api/projects/{project_id}/dataset")
    def upload(project_id: str, request: Request, file: UploadFile = File(...)):
        with editing(project_id, request) as item:
            directory = store.directory(project_id)
            temporary = directory / "upload.tmp"
            try:
                if not (file.filename or "").lower().endswith(".csv"):
                    raise ValueError("Choose a CSV file for this prototype.")
                size = 0
                with temporary.open("wb") as out:
                    while chunk := file.file.read(1024 * 1024):
                        size += len(chunk)
                        if size > datasets.MAX_BYTES:
                            raise ValueError(datasets.upload_limit_message())
                        out.write(chunk)
                profile = profile_csv(temporary)
                temporary.replace(directory / "dataset.csv")
                invalidate(item)
                item["dataset"] = {**profile, "filename": Path(file.filename).name[:180]}
                # A replacement file must not retain stale column choices.
                names = {c["name"] for c in profile["columns"]}
                for field in ("target", "group_column", "time_column"):
                    if item["design"][field] not in names:
                        item["design"][field] = ""
                item["design"]["exclude_columns"] = [c for c in item["design"]["exclude_columns"] if c in names]
                event(item, "data", "complete", f"Read {profile['rows']} rows and {len(profile['columns'])} columns.")
                store.save(item)
                return output(item)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            finally:
                temporary.unlink(missing_ok=True)
                file.file.close()

    @app.post("/api/projects/{project_id}/example")
    def example(project_id: str, body: ExampleRequest, request: Request):
        with editing(project_id, request) as item:
            invalidate(item)
            item["advice"] = []
            item["events"] = []
            item["notices"] = []
            path = store.directory(project_id) / "dataset.csv"
            load_example(item, body.name, path)
            item["dataset"] = {**profile_csv(path), "filename": f"{body.name}_synthetic.csv"}
            event(item, "data", "complete", f"Loaded the {body.name} synthetic example.")
            store.save(item)
            return output(item)

    @app.post("/api/projects/{project_id}/analyze")
    def audit(project_id: str, request: Request):
        with editing(project_id, request) as item:
            try:
                analyze(item)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            store.save(item)
            return output(item)

    @app.post("/api/projects/{project_id}/advise")
    def consult(project_id: str, body: AdviceRequest, request: Request):
        with editing(project_id, request) as item:
            advice(item, body.kind)
            store.save(item)
            return output(item)

    @app.post("/api/projects/{project_id}/run")
    def run(project_id: str, request: Request):
        get(project_id, request)
        lock = store.lock(project_id)
        if not lock.acquire(blocking=False):
            raise HTTPException(409, "A run is already active for this challenge.")
        item = get(project_id, request)
        item["harness"] = {"status": "running", "stage": "scope"}
        store.save(item)
        pool.submit(run_harness, project_id, owner(request))
        return output(item)

    @app.post("/api/projects/{project_id}/prepare")
    def prepare(project_id: str, body: PrepareRequest, request: Request):
        with editing(project_id, request) as item:
            if not body.acknowledge_review:
                raise HTTPException(422, "Review the findings and confirm the package before preparing it.")
            if not item.get("analysis"):
                raise HTTPException(422, "Run the data audit before preparing packages.")
            if item["analysis"]["summary"]["blockers"]:
                raise HTTPException(422, "Resolve every blocker, then run the audit again.")
            if item["analysis"].get("baseline", {}).get("status") != "complete":
                raise HTTPException(422, "A completed development trial is required before preparing packages.")
            if not item.get("prepared"):
                try:
                    result = package(item, store.directory(project_id) / "dataset.csv", store.directory(project_id))
                except ValueError as exc:
                    raise HTTPException(422, str(exc)) from exc
                split = item["analysis"]["split"]
                item["prepared"] = {"created_at": now(), "train_rows": split["train_rows"], "test_rows": split["test_rows"],
                                    "archive_sha256": result["archive_sha256"], "revision": item["revision"]}
                item["_participant"] = secrets.token_urlsafe(32)
                item["status"] = "prepared"
                event(item, "package", "complete", "Researcher and private organizer packages prepared after human review.")
                store.save(item)
            return output(item)

    @app.get("/api/projects/{project_id}/download/{kind}")
    def download(project_id: str, kind: Literal["researcher", "organizer"], request: Request):
        item = get(project_id, request)
        if not item.get("prepared"):
            raise HTTPException(404, "Prepare the current revision first.")
        return FileResponse(store.directory(project_id) / f"{kind}.zip", filename=f"autokaggle-{kind}-{project_id[:8]}.zip", media_type="application/zip")

    @app.get("/api/projects/{project_id}/brief.md")
    def markdown(project_id: str, request: Request):
        return PlainTextResponse(description(get(project_id, request)), media_type="text/markdown", headers={"Content-Disposition": 'attachment; filename="challenge-brief.md"'})

    @app.get("/api/projects/{project_id}/participant-link")
    def participant_link(project_id: str, request: Request):
        item = get(project_id, request)
        if not item.get("prepared"):
            raise HTTPException(404, "Prepare the current revision first.")
        return {"url": f"/challenge/{item['_participant']}"}

    def participant(token):
        item = store.by_token(token)
        if not item or not item.get("prepared"):
            raise HTTPException(404, "This challenge link is unavailable or has been replaced.")
        return item

    @app.get("/api/challenges/{token}")
    def researcher_view(token: str):
        item = participant(token)
        return {"title": item["title"], "brief": description(item), "metric": item["design"]["metric"],
            "train_rows": item["prepared"]["train_rows"], "download_url": f"/api/challenges/{token}/download",
            "limitations": ["Only training data are available. All final test rows remain private.",
                            "The organizer must provide an isolated prediction runner before accepting untrusted programs."]}

    @app.get("/api/challenges/{token}/download")
    def researcher_download(token: str):
        item = participant(token)
        return FileResponse(store.directory(item["id"]) / "researcher.zip", filename="autokaggle-researcher.zip", media_type="application/zip")

    @app.get("/")
    def chat_index(request: Request):
        if not access.can_open(request, store):
            return RedirectResponse("/login?next=" + quote(str(request.url.path) + ("?" + request.url.query if request.url.query else ""), safe=""), status_code=303)
        return FileResponse(HERE / "static/chat.html")

    @app.get("/workbench")
    @app.get("/challenge/{token}")
    def index(request: Request, token: str | None = None):
        if token is None and not access.can_open(request, store):
            return RedirectResponse("/login?next=" + quote(str(request.url.path) + ("?" + request.url.query if request.url.query else ""), safe=""), status_code=303)
        return FileResponse(HERE / "static/index.html")

    (HERE / "static").mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    return app
