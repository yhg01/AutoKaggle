"""Remote preflight does not lock storage or bypass atomic reservation checks."""
from datetime import datetime, timezone
import hashlib
import json
import sqlite3

import pytest

from autokaggle import onboarding_setup, runner, submissions, workflow
from autokaggle.store import Store


@pytest.fixture
def case(tmp_path, monkeypatch):
    store = Store(tmp_path / "data")
    submissions.initialize(store)
    project = store.create("owner", "Submission preflight")
    project["limit"] = 5
    root = store.directory(project["id"]) / "workflow"
    private = root / "private"
    private.mkdir(parents=True)
    (root / "researcher").mkdir()
    (private / "validation_truth.csv").write_text("_autokaggle_id,truth\nvalidation-0,1\n")
    (private / "validation_features.csv").write_text("_autokaggle_id,x\nvalidation-0,3\n")
    (private / "challenge.json").write_text(json.dumps({"target": "target", "metric": {"name": "accuracy"}}))
    (root / "researcher/train.csv").write_text("x,target\n2,1\n")
    monkeypatch.setattr(workflow, "view", lambda _project: {"status": "ready_for_review", "version": "v1"})
    monkeypatch.setattr(workflow, "score_file", lambda *_args: {"score": 1., "metric": "accuracy"})
    monkeypatch.setattr(onboarding_setup, "get", lambda value: {"competition_type": "code", "daily_submission_limit": value["limit"]})

    class FakeRunner:
        checks = 0
        runs = 0
        on_status = None

        def status(self):
            self.checks += 1
            return self.on_status() if self.on_status else {"enabled": True}

        def submit(self, *_args, **_kwargs):
            self.runs += 1
            return b"_autokaggle_id,prediction\nvalidation-0,1\n"

    remote = FakeRunner()
    monkeypatch.setattr(runner, "CivoRunner", lambda: remote)
    return store, project, remote


def reserve(store, project, request_id, source, result):
    request = hashlib.sha256(("organizer-preview\0" + request_id).encode()).hexdigest()
    digest = hashlib.sha256(("v1\0code\0" + source).encode()).hexdigest()
    with store.connection() as con:
        con.execute("INSERT INTO draft_submissions (project,version,request,fingerprint,day,result,team) VALUES (?,?,?,?,?,?,?)",
                    (project["id"], "v1", request, digest, datetime.now(timezone.utc).date().isoformat(), json.dumps(result), "organizer-preview"))


def test_other_database_writes_work_during_runner_preflight(case):
    store, project, remote = case

    def preflight():
        # An independent writer fails immediately if the submission holds a
        # write reservation. No cluster or slow timing-based thread is needed.
        with sqlite3.connect(store.db, timeout=.05) as con:
            con.execute("UPDATE projects SET updated_at=? WHERE id=?", ("written-during-preflight", project["id"]))
        return {"enabled": True}

    remote.on_status = preflight
    assert submissions.submit_code(store, project, "first-attempt", "import csv")["status"] == "scored"
    with store.connection() as con:
        assert con.execute("SELECT updated_at FROM projects WHERE id=?", (project["id"],)).fetchone()[0] == "written-during-preflight"


def test_quota_is_rechecked_after_preflight(case):
    store, project, remote = case
    project["limit"] = 1

    def preflight():
        reserve(store, project, "another-attempt", "other code", {"status": "interrupted"})
        return {"enabled": True}

    remote.on_status = preflight
    with pytest.raises(submissions.LimitReached):
        submissions.submit_code(store, project, "first-attempt", "import csv")
    assert remote.runs == 0
    with store.connection() as con:
        assert con.execute("SELECT COUNT(*) FROM draft_submissions").fetchone()[0] == 1


@pytest.mark.parametrize("available", [True, False])
def test_same_attempt_completed_during_preflight_is_returned_once(case, available):
    store, project, remote = case
    cached = {"status": "scored", "request_id": "first-attempt", "score": .75, "remaining_today": 4}

    def preflight():
        reserve(store, project, "first-attempt", "import csv", cached)
        return {"enabled": available}

    remote.on_status = preflight
    assert submissions.submit_code(store, project, "first-attempt", "import csv") == cached
    assert remote.runs == 0
    with store.connection() as con:
        assert con.execute("SELECT COUNT(*) FROM draft_submissions").fetchone()[0] == 1


def test_conflicting_request_reserved_during_preflight_is_rejected(case):
    store, project, remote = case

    def preflight():
        reserve(store, project, "first-attempt", "different code", {"status": "interrupted"})
        return {"enabled": True}

    remote.on_status = preflight
    with pytest.raises(ValueError, match="different submission"):
        submissions.submit_code(store, project, "first-attempt", "import csv")
    assert remote.runs == 0


def test_cached_completion_does_not_call_runner_preflight(case):
    store, project, remote = case
    first = submissions.submit_code(store, project, "first-attempt", "import csv")
    remote.on_status = lambda: (_ for _ in ()).throw(AssertionError("Completed retries need no remote check"))
    assert submissions.submit_code(store, project, "first-attempt", "import csv") == first
    assert remote.checks == 1 and remote.runs == 1


def test_unavailable_runner_does_not_reserve_a_new_attempt(case):
    store, project, remote = case
    remote.on_status = lambda: {"enabled": False}
    with pytest.raises(runner.RunnerUnavailable):
        submissions.submit_code(store, project, "first-attempt", "import csv")
    with store.connection() as con:
        assert con.execute("SELECT COUNT(*) FROM draft_submissions").fetchone()[0] == 0
    assert remote.runs == 0


def test_quota_day_is_taken_when_reserved_after_preflight(case, monkeypatch):
    store, project, remote = case

    class Clock:
        current = datetime(2026, 10, 27, 23, 59, 59, tzinfo=timezone.utc)

        @classmethod
        def now(cls, _timezone):
            return cls.current

    def preflight():
        Clock.current = datetime(2026, 10, 28, 0, 0, 1, tzinfo=timezone.utc)
        return {"enabled": True}

    monkeypatch.setattr(submissions, "datetime", Clock)
    remote.on_status = preflight
    submissions.submit_code(store, project, "after-midnight", "import csv")
    with store.connection() as con:
        assert con.execute("SELECT day FROM draft_submissions").fetchone()[0] == "2026-10-28"
