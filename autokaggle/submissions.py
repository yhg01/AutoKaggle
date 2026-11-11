"""Persist development submissions, including failures, under a daily allowance."""
from __future__ import annotations

from datetime import datetime, timezone
import csv
import hashlib
import json
import os
from pathlib import Path
import tempfile
import secrets

from . import environment_harness, environments, onboarding_setup, workflow, research_review
from .research_policy import is_public, DISCLOSURE


class LimitReached(ValueError):
    pass


def initialize(store):
    with store.connection() as con:
        con.execute("CREATE TABLE IF NOT EXISTS draft_submissions (project TEXT NOT NULL, version TEXT NOT NULL, request TEXT NOT NULL, fingerprint TEXT NOT NULL, day TEXT NOT NULL, result TEXT NOT NULL, PRIMARY KEY(project, request))")
        if "team" not in {row[1] for row in con.execute("PRAGMA table_info(draft_submissions)")}:
            con.execute("ALTER TABLE draft_submissions ADD COLUMN team TEXT NOT NULL DEFAULT 'organizer-preview'")
        con.execute("CREATE TABLE IF NOT EXISTS submission_tokens (digest TEXT PRIMARY KEY, project TEXT NOT NULL, version TEXT NOT NULL, draft TEXT NOT NULL, team TEXT NOT NULL)")


def issue_token(store, project, team="organizer-preview"):
    current = workflow.view(project)
    if current.get("status") in {"stale", "not_built"} or not current.get("version"):
        raise ValueError("Build the current draft before creating submission access.")
    token = secrets.token_urlsafe(32)
    with store.connection() as con:
        con.execute("DELETE FROM submission_tokens WHERE project=? AND team=?", (project["id"], team))
        con.execute("INSERT INTO submission_tokens VALUES (?,?,?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), project["id"], current["version"], workflow.fingerprint(project), team))
    return token


def authenticate(store, project_id, token):
    if not token or len(token) > 100:
        return None
    with store.connection() as con:
        row = con.execute("SELECT p.body,t.version,t.draft,t.team FROM submission_tokens t JOIN projects p ON p.id=t.project WHERE t.project=? AND t.digest=?", (project_id, hashlib.sha256(token.encode()).hexdigest())).fetchone()
    if not row:
        return None
    project = json.loads(row[0])
    current = workflow.view(project)
    if current.get("status") in {"stale", "not_built"} or current.get("version") != row[1] or workflow.fingerprint(project) != row[2]:
        return None
    return project, row[3]


def submit(store, project, request_id, csv_text, team="organizer-preview", code_zip_base64=""):
    return _submit(store, project, request_id, csv_text, team, "prediction", code_zip_base64=code_zip_base64)


def submit_code(store, project, request_id, source, team="organizer-preview"):
    from .runner import CivoRunner
    runner = CivoRunner()
    return _submit(store, project, request_id, source, team, "code", runner)


def submit_repository(store, project, request_id, repository_url, ref="", team="organizer-preview"):
    payload = json.dumps({"repository_url": repository_url, "ref": ref}, sort_keys=True)
    return _submit(store, project, request_id, payload, team, "environment")


def environment_queue(store, project):
    """Frozen commits waiting for an isolated run. Seeds are only returned to the operator."""
    private = store.directory(project["id"]) / "workflow/private"
    config = project.get("environment") or {}
    seeds = json.loads((private / "seeds.json").read_text())["development"] if (private / "seeds.json").is_file() else []
    with store.connection() as con:
        rows = con.execute("SELECT request,version,result FROM draft_submissions WHERE project=?", (project["id"],)).fetchall()
    items = [{"submission": row[0], "version": row[1], **json.loads(row[2])} for row in rows if json.loads(row[2]).get("status") == "received"]
    return {"environment": {key: config.get(key) for key in ("env_repository", "env_commit", "env_private", "env_factory", "max_episode_steps", "evaluation_hours")},
            "development_seeds": seeds, "submissions": items}


def record_environment_results(store, project, submission, episodes_csv, operator):
    """Score episodes from an isolated run. Only aggregate development results are returned."""
    private = store.directory(project["id"]) / "workflow/private"
    if not (private / "seeds.json").is_file():
        raise ValueError("Build the environment challenge before recording results.")
    expected = json.loads((private / "seeds.json").read_text())["development"]
    measured = environment_harness.score_episodes(episodes_csv, expected)
    spec = json.loads((private / "challenge.json").read_text())
    metric = spec["metric"]["name"]
    with store.connection() as con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute("SELECT result FROM draft_submissions WHERE project=? AND request=?", (project["id"], submission)).fetchone()
        if row is None:
            raise ValueError("This submission does not exist.")
        current = json.loads(row[0])
        if current.get("status") != "received":
            raise ValueError("This submission is not waiting for results.")
        result = {**current, "status": "scored", "metric": metric, "score": round(measured[metric], 6), "scope": "development",
                  "success_rate": round(measured["success_rate"], 6), "mean_score": round(measured["mean_score"], 6),
                  "success_interval_95": [round(value, 6) for value in measured["success_interval_95"]],
                  "episodes": measured["episodes"], "completed_episodes": measured["completed_episodes"],
                  "provenance": {"source": "operator_reported", "operator": operator},
                  "detail": "Development score from an isolated run recorded by the operator. Final results remain private."}
        con.execute("UPDATE draft_submissions SET result=? WHERE project=? AND request=?", (json.dumps(result), project["id"], submission))
    return result


def _saved_result(connection, project_id, storage_request, digest):
    prior = connection.execute("SELECT fingerprint,result FROM draft_submissions WHERE project=? AND request=?", (project_id, storage_request)).fetchone()
    if prior is None:
        return None
    if prior[0] != digest:
        raise ValueError("This request ID already identifies a different submission.")
    return json.loads(prior[1])


def _submit(store, project, request_id, payload, team, kind, runner=None, code_zip_base64=""):
    current = workflow.view(project)
    if current.get("status") in {"stale", "not_built"} or not current.get("version"):
        raise ValueError("Build the current workflow before making a development submission.")
    private = store.directory(project["id"]) / "workflow/private"
    if kind == "environment":
        if not (private / "seeds.json").is_file():
            raise ValueError("Set the environment and seed policy, then build the draft, before making a submission.")
    elif not (private / "validation_truth.csv").is_file():
        raise ValueError("Prepare valid data before making a development submission.")
    if onboarding_setup.get(project)["competition_type"] != kind:
        raise ValueError("The submission format does not match this competition type.")
    version = current["version"]
    public_research = is_public(project) and kind == "prediction"
    bundle = research_review.unpack(code_zip_base64, version) if public_research else None
    if code_zip_base64 and not public_research:
        raise ValueError("Code ZIP attachments apply only to public-data research predictions.")
    digest_payload = payload + ("\0" + hashlib.sha256(bundle[0]).hexdigest() if bundle else "")
    digest = hashlib.sha256((version + "\0" + kind + "\0" + digest_payload).encode()).hexdigest()
    storage_request = hashlib.sha256((team + "\0" + request_id).encode()).hexdigest()
    with store.connection() as con:
        prior = _saved_result(con, project["id"], storage_request, digest)
    if prior is not None:
        return prior
    # A link that cannot be frozen is not an attempt, so it does not use the allowance.
    frozen = environments.freeze_submission(**json.loads(payload)) if kind == "environment" else None
    # Remote control checks must not hold the database write lock. A second
    # lookup below handles an attempt that was reserved during those checks.
    runner_available = kind != "code" or runner.status().get("enabled")
    with store.connection() as con:
        con.execute("BEGIN IMMEDIATE")
        prior = _saved_result(con, project["id"], storage_request, digest)
        if prior is not None:
            return prior
        if not runner_available:
            from .runner import RunnerUnavailable
            raise RunnerUnavailable("Code submissions are unavailable until the Civo sandbox passes its execution checks.")
        day = datetime.now(timezone.utc).date().isoformat()
        count = con.execute("SELECT COUNT(*) FROM draft_submissions WHERE project=? AND day=? AND team=?", (project["id"], day, team)).fetchone()[0]
        usage = con.execute("SELECT count FROM submission_usage WHERE project=? AND day=? AND team=?", (project["id"], day, team)).fetchone()
        count += usage[0] if usage else 0
        limit = onboarding_setup.get(project)["daily_submission_limit"]
        if count >= limit:
            raise LimitReached("The daily submission allowance has been used. It resets at 00:00 UTC.")
        reserved = {"status": "interrupted", "detail": "The attempt was reserved. If execution stopped, use a new request ID; the reserved attempt still counts.", "request_id": request_id}
        con.execute("INSERT INTO draft_submissions (project,version,request,fingerprint,day,result,team) VALUES (?,?,?,?,?,?,?)", (project["id"], version, storage_request, digest, day, json.dumps(reserved), team))
    if public_research:
        artifact_dir = store.directory(project["id"]) / "attempts" / storage_request
        artifact_dir.mkdir(parents=True, mode=0o700)
        (artifact_dir / "code.zip").write_bytes(bundle[0])
        (artifact_dir / "predictions.csv").write_text(payload)
        for path in artifact_dir.iterdir():
            os.chmod(path, 0o600)
        result = {"status": "review_pending", "request_id": request_id, "scope": "development",
                  "remaining_today": limit - count - 1, "version": version,
                  "artifact_id": storage_request, "code_sha256": hashlib.sha256(bundle[0]).hexdigest(),
                  "predictions_sha256": hashlib.sha256(payload.encode()).hexdigest(),
                  "reproduction": {"status": "not_run", "detail": "Code saved for reproduction. No execution has been verified."},
                  "review_attempts": 0, "detail": "Code saved. The reward-hacking review is pending."}
        _persist(store, project["id"], storage_request, result)
        return _review_attempt(store, project, storage_request, result, bundle[1])
    if kind == "environment":
        result = {"status": "received", "request_id": request_id, "scope": "development", "remaining_today": limit - count - 1, **frozen,
                  "detail": environments.EXECUTION_NOTICE}
        with store.connection() as con:
            con.execute("UPDATE draft_submissions SET result=? WHERE project=? AND request=?", (json.dumps(result), project["id"], storage_request))
        return result
    try:
        with tempfile.TemporaryDirectory(prefix="prediction-", dir=store.directory(project["id"])) as tmp:
            path = Path(tmp) / "predictions.csv"
            spec = json.loads((private / "challenge.json").read_text())
            if kind == "code":
                features = (private / "validation_features.csv").read_bytes()
                with (private / "validation_features.csv").open(newline="") as stream:
                    columns = next(csv.reader(stream))
                predictions = runner.submit(payload.encode("utf-8"), features=features,
                    training=(private.parent / "researcher/train.csv").read_bytes(),
                    expected_columns=columns, label_columns=[spec["target"]])
                if not isinstance(predictions, bytes) or not 0 < len(predictions) <= 5_000_000:
                    raise ValueError("Invalid runner result.")
                path.write_bytes(predictions)
            else:
                path.write_text(payload)
            measured = workflow.score_file(private / "validation_truth.csv", path, spec["metric"]["name"])
        result = {"status": "scored", "request_id": request_id, "metric": measured["metric"], "score": round(measured["score"], 6),
                  "scope": "development", "remaining_today": limit - count - 1, "detail": "Training-derived validation score. Final test results remain private."}
    except (ValueError, KeyError, TypeError, OverflowError, UnicodeError, csv.Error):
        result = {"status": "invalid", "request_id": request_id, "remaining_today": limit - count - 1,
                  "detail": "The prediction file does not match the published format. Check columns, IDs, count, and values."}
    except RuntimeError:
        # Worker failures and logs must not reveal hidden input values.
        result = {"status": "failed", "request_id": request_id, "remaining_today": limit - count - 1,
                  "detail": "The code attempt did not complete. Check the published environment, limits, and output contract."}
    with store.connection() as con:
        con.execute("UPDATE draft_submissions SET result=? WHERE project=? AND request=?", (json.dumps(result), project["id"], storage_request))
    return result


def _persist(store, project_id, storage_request, result):
    with store.connection() as con:
        con.execute("UPDATE draft_submissions SET result=? WHERE project=? AND request=?", (json.dumps(result), project_id, storage_request))


def _review_attempt(store, project, storage_request, result, files):
    private = store.directory(project["id"]) / "workflow/private"
    artifacts = store.directory(project["id"]) / "attempts" / storage_request
    spec = json.loads((private / "challenge.json").read_text())
    result["review_attempts"] += 1
    _persist(store, project["id"], storage_request, result)
    try:
        # Validate the predictions before a paid review. Scoring values stay outside the reviewer.
        measured = workflow.score_file(private / "validation_truth.csv", artifacts / "predictions.csv", spec["metric"]["name"])
    except (ValueError, KeyError, TypeError, OverflowError, UnicodeError, csv.Error):
        result.update(status="invalid", detail="The prediction file does not match the published format. Check columns, IDs, count, and values.")
        _persist(store, project["id"], storage_request, result)
        return result
    report = research_review.review(files, {"version": spec["version"], "target": spec["target"], "metric": spec["metric"],
                                           "output_columns": ["_autokaggle_id", "prediction"]})
    result["review"] = report
    if report["status"] == "clear":
        result.update(status="scored", metric=measured["metric"], score=round(measured["score"], 6),
                      detail="Provisional development score. Source review found no concrete concern. Reproduction is not verified. " + DISCLOSURE)
    elif report["status"] == "flagged":
        result.update(status="review_flagged", detail="The review found a possible rule violation. The score is withheld. Inspect the findings and submit a corrected attempt.")
    else:
        result.update(status="review_pending", detail="The review did not complete. The score is withheld. Retry the review without using another submission.")
    _persist(store, project["id"], storage_request, result)
    return result


def retry_review(store, project, artifact_id):
    with store.connection() as con:
        row = con.execute("SELECT version,result FROM draft_submissions WHERE project=? AND request=?", (project["id"], artifact_id)).fetchone()
    if row is None:
        raise ValueError("This attempt does not exist.")
    result = json.loads(row[1])
    if workflow.view(project).get("status") in {"stale", "not_built"} or workflow.view(project).get("version") != row[0] or not is_public(project):
        raise ValueError("This attempt belongs to a different challenge version. Rebuild and submit a new attempt.")
    if result.get("status") != "review_pending" or result.get("review_attempts", 0) >= 3:
        raise ValueError("Only an incomplete review can be retried, up to three review attempts.")
    directory = store.directory(project["id"]) / "attempts" / artifact_id
    raw = (directory / "code.zip").read_bytes()
    predictions = (directory / "predictions.csv").read_bytes()
    if hashlib.sha256(raw).hexdigest() != result["code_sha256"] or hashlib.sha256(predictions).hexdigest() != result["predictions_sha256"]:
        raise ValueError("Saved artifacts failed the integrity check.")
    import base64
    _, files, _ = research_review.unpack(base64.b64encode(raw).decode(), row[0])
    return _review_attempt(store, project, artifact_id, result, files)
