"""Research-data validation and human release approval routes for Lite."""
from __future__ import annotations

import hashlib
import json
import secrets
import shutil
from pathlib import Path

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from . import lite_quality as quality, lite_release, sources
from .store import now


class ResearchCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=8, max_length=100)
    artifact_url: str = Field(max_length=2000)
    artifact_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    artifact_bytes: int = Field(gt=0, le=1024**4)
    reference_url: str = Field(default="", max_length=2000)
    reference_sha256: str = Field(default="", pattern=r"^([a-f0-9]{64})?$")
    reference_bytes: int = Field(default=0, ge=0, le=1024**4)
    reference_archive: bool = False
    reference_expanded_bytes: int = Field(default=0, ge=0, le=1024**4)
    expected_fitness: float = Field(allow_inf_nan=False)
    tolerance: float = Field(default=1e-6, ge=0, le=1e-5)
    expected_basis: str = Field(min_length=20, max_length=4000)


class Approval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    build_id: str
    research_report_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    approved: bool
    note: str = Field(min_length=10, max_length=4000)


def _fetch(url, target, size, digest):
    sources.fetch(url, limit=size, destination=target, deadline=1800)
    if target.stat().st_size != size or quality.digest(target) != digest:
        raise ValueError("The downloaded asset differs from its declared size or SHA-256.")


def worker(store, identifier, build_id, job_id, request, runtime):
    from . import lite_build as builds
    base = Path(store.directory(identifier)) / "lite-evaluator"
    job = base / "jobs" / job_id
    result = None
    running_released = False
    try:
        with builds._SLOTS:
            item = builds._reload(store, identifier)
            build = next(b for b in item["lite_evaluator"]["builds"] if b["id"] == build_id)
            evidence = build["evidence"]
            for name in ("in", "out", "work", "home"):
                (job / name).mkdir(parents=True, exist_ok=True)
            required = request["artifact_bytes"] + request["reference_bytes"] + request["reference_expanded_bytes"]
            if shutil.disk_usage(job).free < required + 1024**3:
                raise ValueError("This validation needs more free storage. No data were imported and no resources were increased.")
            _fetch(request["artifact_url"], job / "in/artifact", request["artifact_bytes"], request["artifact_sha256"])
            if request["reference_url"]:
                target = job / "in/reference"
                _fetch(request["reference_url"], target, request["reference_bytes"], request["reference_sha256"])
            request.update(commit=evidence["commit"], contract_sha256=evidence["contract_sha256"],
                           resources=json.dumps(runtime.describe()),
                           timeout_seconds=min(item["lite"]["contract"]["total_timeout_seconds"], 4*3600))
            (job / "in/research.json").write_text(json.dumps(request))
            shutil.copyfile(base / "releases" / f"v{build['evaluator_version']}" / "evaluator.bundle", job / "in/release.bundle")
            for name in ("lite_acceptance.py", "lite_research_check.py"):
                shutil.copyfile(Path(__file__).parent / name, job / "in" / name)
            runtime.prepare()
            code, seconds = runtime.run(["{python}", "{in}/lite_research_check.py", "--inputs", "{in}", "--work", "{work}", "--output", "{out}"],
                {"in": (job / "in", "ro"), "work": (job / "work", "rw"), "out": (job / "out", "rw"), "home": (job / "home", "rw")},
                "{work}", {}, min(4*3600, request["timeout_seconds"] + 2400), job / "research.log", "research")
            report_path = job / "out/research-report.json"
            if report_path.is_symlink() or not report_path.is_file() or report_path.stat().st_size > 100000:
                raise ValueError("The research validation job did not complete a report. Check assets, dependencies, and the approved resource limits.")
            result = json.loads(report_path.read_text())
            if code != 0 or result.get("passed") is not True:
                raise ValueError("The research validation did not pass: " + str(result.get("detail", "No result"))[:1200])
            # Bind evidence to the actual trusted job, not a submitted JSON claim.
            if result.get("commit") != evidence["commit"] or result.get("contract_sha256") != evidence["contract_sha256"]:
                raise ValueError("The research validation used a different evaluator version.")
            result.update(report_sha256=quality.digest(report_path), checked_by="controlled-runtime:" + job_id,
                          checked_at=now(), seconds=seconds, runtime=runtime.describe())
            release = base / "releases" / f"v{build['evaluator_version']}"
            destination = release / "research-validation" / job_id
            destination.parent.mkdir(exist_ok=True)
            # Inspect the complete tree before copying anything out of the job.
            # Generated adapters cannot make the host follow an output symlink.
            quality.digest(job / "out")
            shutil.copytree(job / "out", destination)
            with store.lock(identifier):
                item = builds._reload(store, identifier)
                current = next(b for b in item["lite_evaluator"]["builds"] if b["id"] == build_id)
                current["validation"].update(research_data="validated", research_evidence=result)
                current.pop("human_approval", None)
                lite_release.queue_registration(item, current)
                builds._RUNNING.discard(build_id)
                running_released = True
                store.save(item)
    except Exception as exc:
        detail = str(exc)[:1500] if isinstance(exc, (ValueError, RuntimeError)) else "Research validation failed (" + type(exc).__name__ + ")."
        with store.lock(identifier):
            item = builds._reload(store, identifier)
            if item:
                current = next(b for b in item["lite_evaluator"]["builds"] if b["id"] == build_id)
                current["validation"].update(research_data="failed", research_error=detail)
                current.pop("human_approval", None)
                lite_release.queue_registration(item, current)
                builds._RUNNING.discard(build_id)
                running_released = True
                store.save(item)
    finally:
        for folder in ("in", "work", "home", "out"):
            shutil.rmtree(job / folder, ignore_errors=True)
        if not running_released:
            builds._RUNNING.discard(build_id)


def register(app, store, pool, access, editing, read_view, runtime, github):
    from . import lite_build as builds

    @app.post("/api/projects/{project_id}/lite/evaluator/research-check")
    def research_check(project_id: str, body: ResearchCheck, request: Request):
        read_view(project_id, request)
        available, reason = runtime.available()
        if not available:
            raise HTTPException(503, reason or "The validation runtime is unavailable.")
        try:
            sources.source_syntax(body.artifact_url)
            if body.reference_url:
                sources.source_syntax(body.reference_url)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if body.reference_url:
            if not body.reference_sha256 or not body.reference_bytes or (body.reference_archive and not body.reference_expanded_bytes):
                raise HTTPException(422, "Declare the reference size, SHA-256, and expanded size for an archive.")
        elif body.reference_bytes or body.reference_sha256 or body.reference_archive or body.reference_expanded_bytes:
            raise HTTPException(422, "Supply the reference link with its metadata.")
        with editing(project_id, request) as item:
            current = builds.view(item, runtime, github)["release"]
            if not current or current["validation"]["contract_coverage"] != "passed":
                raise HTTPException(409, "Build an evaluator with complete contract checks first.")
            saved = item["lite_evaluator"].setdefault("research_requests", {})
            fingerprint = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
            if body.request_id in saved:
                previous = saved[body.request_id]
                if not isinstance(previous, dict) or previous.get("fingerprint") != fingerprint:
                    raise HTTPException(409, "This request ID belongs to different validation inputs. Start a new request.")
                return builds.view(item, runtime, github)
            if len(saved) >= 30:
                raise HTTPException(429, "This problem reached its 30 research-validation limit.")
            if any(b["id"] in builds._RUNNING for b in item["lite_evaluator"]["builds"]):
                raise HTTPException(409, "A validation job is already running.")
            build = next(b for b in item["lite_evaluator"]["builds"] if b["id"] == current["id"])
            build["validation"].update(research_data="running", research_error=None)
            build.pop("human_approval", None)
            lite_release.queue_registration(item, build)
            job = secrets.token_hex(8)
            saved[body.request_id] = {"job_id": job, "fingerprint": fingerprint}
            builds._RUNNING.add(build["id"])
            store.save(item)
            try:
                pool.submit(worker, store, project_id, build["id"], job, body.model_dump(), runtime)
            except (RuntimeError, OSError):
                builds._RUNNING.discard(build["id"])
                saved.pop(body.request_id, None)
                build["validation"].update(research_data="failed", research_error="The validation job could not start. Retry this request.")
                lite_release.queue_registration(item, build)
                store.save(item)
                raise HTTPException(503, "The validation job could not start. Your release is saved. Retry this request.") from None
        return read_view(project_id, request)

    @app.post("/api/projects/{project_id}/lite/evaluator/approve")
    def approve(project_id: str, body: Approval, request: Request):
        read_view(project_id, request)
        with editing(project_id, request) as item:
            current = builds.view(item, runtime, github)["release"]
            if not current or current["id"] != body.build_id:
                raise HTTPException(409, "The evaluator version changed. Review the current release.")
            validation = current["validation"]
            evidence = validation.get("research_evidence") or {}
            if not body.approved or validation["research_data"] != "validated" or evidence.get("report_sha256") != body.research_report_sha256:
                raise HTTPException(409, "Review a successful validation on the declared research data before approval.")
            actor = access.owner(request)
            if not actor:
                raise HTTPException(401, "Sign in before approving the release.")
            build = next(b for b in item["lite_evaluator"]["builds"] if b["id"] == current["id"])
            build["human_approval"] = {"approved_by": hashlib.sha256(actor.encode()).hexdigest(), "approved_at": now(),
                "commit": current["evidence"]["commit"], "contract_sha256": current["contract_sha256"],
                "research_report_sha256": body.research_report_sha256, "note": body.note}
            lite_release.queue_registration(item, build)
            store.save(item)
            lite_release.deliver_registration(store, item, build)
        return read_view(project_id, request)

    @app.post("/api/projects/{project_id}/lite/evaluator/registry/retry")
    def retry_registration(project_id: str, request: Request):
        read_view(project_id, request)
        with editing(project_id, request) as item:
            current = builds.view(item, runtime, github)["release"]
            if not current:
                raise HTTPException(409, "There is no current evaluator release.")
            build = next(b for b in item["lite_evaluator"]["builds"] if b["id"] == current["id"])
            lite_release.deliver_registration(store, item, build)
        return read_view(project_id, request)
