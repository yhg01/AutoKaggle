"""Persist development submissions, including failures, under a daily allowance."""
from __future__ import annotations

from datetime import datetime, timezone
import csv
import hashlib
import json
from pathlib import Path
import tempfile
import secrets

from . import onboarding_setup, workflow


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


def submit(store, project, request_id, csv_text, team="organizer-preview"):
    return _submit(store, project, request_id, csv_text, team, "prediction")


def submit_code(store, project, request_id, source, team="organizer-preview"):
    from .runner import CivoRunner
    runner = CivoRunner()
    return _submit(store, project, request_id, source, team, "code", runner)


def _saved_result(connection, project_id, storage_request, digest):
    prior = connection.execute("SELECT fingerprint,result FROM draft_submissions WHERE project=? AND request=?", (project_id, storage_request)).fetchone()
    if prior is None:
        return None
    if prior[0] != digest:
        raise ValueError("This request ID already identifies a different submission.")
    return json.loads(prior[1])


def _submit(store, project, request_id, payload, team, kind, runner=None):
    current = workflow.view(project)
    if current.get("status") in {"stale", "not_built"} or not current.get("version"):
        raise ValueError("Build the current workflow before making a development submission.")
    private = store.directory(project["id"]) / "workflow/private"
    if not (private / "validation_truth.csv").is_file():
        raise ValueError("Prepare valid data before making a development submission.")
    if onboarding_setup.get(project)["competition_type"] != kind:
        raise ValueError("The submission format does not match this competition type.")
    version = current["version"]
    digest = hashlib.sha256((version + "\0" + kind + "\0" + payload).encode()).hexdigest()
    storage_request = hashlib.sha256((team + "\0" + request_id).encode()).hexdigest()
    with store.connection() as con:
        prior = _saved_result(con, project["id"], storage_request, digest)
    if prior is not None:
        return prior
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
        limit = onboarding_setup.get(project)["daily_submission_limit"]
        if count >= limit:
            raise LimitReached("The daily submission allowance has been used. It resets at 00:00 UTC.")
        reserved = {"status": "interrupted", "detail": "The attempt was reserved. If execution stopped, use a new request ID; the reserved attempt still counts.", "request_id": request_id}
        con.execute("INSERT INTO draft_submissions (project,version,request,fingerprint,day,result,team) VALUES (?,?,?,?,?,?,?)", (project["id"], version, storage_request, digest, day, json.dumps(reserved), team))
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
