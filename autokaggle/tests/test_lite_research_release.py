import io
import json
from pathlib import Path
import tarfile
import time
import uuid

from fastapi.testclient import TestClient
import pytest

from autokaggle import lite_build, lite_quality, lite_release, sources
from autokaggle.tests.test_lite_build import harness, accepted, build, settle


def test_safe_archive_rejects_links_duplicates_and_expansion(tmp_path):
    for kind in ("link", "duplicate", "large", "escape"):
        archive = tmp_path / (kind + ".tar")
        with tarfile.open(archive, "w") as output:
            member = tarfile.TarInfo("../escape" if kind == "escape" else "sample")
            if kind == "link":
                member.type = tarfile.SYMTYPE
                member.linkname = "/etc/passwd"
                output.addfile(member)
            else:
                member.size = 5
                output.addfile(member, io.BytesIO(b"hello"))
                if kind == "duplicate": output.addfile(member, io.BytesIO(b"hello"))
        with pytest.raises(ValueError):
            lite_quality.extract_archive(archive, tmp_path / (kind + "-out"), max_bytes=4 if kind == "large" else 100)
        assert not (tmp_path / (kind + "-out")).exists()


def test_coding_iteration_keeps_previous_release_and_saved_conversation(harness, monkeypatch):
    app, _, root = harness
    with TestClient(app) as client:
        identifier, path = accepted(client, monkeypatch)
        first = build(client, path)["release"]
        feedback = "Add a clear diagnostic for a missing ID. Keep the metric and scientific definition unchanged."
        response = client.post(path + "/evaluator/build", json={"request_id": "revision-request", "feedback": feedback})
        assert response.status_code == 200
        view = settle(client, path + "/evaluator", lambda s: s["status"] not in lite_build.ACTIVE)
        assert view["release"]["evaluator_version"] == 2
        assert view["release"]["parent_commit"] == first["evidence"]["commit"]
        assert view["earlier_releases"][0]["commit"] == first["evidence"]["commit"]
        messages = client.get(path).json()["messages"]
        assert any(m["content"] == feedback for m in messages)
        assert "research data" in messages[-1]["content"]
        # Reopening retains the complete iteration, with no duplicate build on retry.
        assert client.post(path + "/evaluator/build", json={"request_id": "revision-request", "feedback": feedback}).json()["builds"] == 2
        assert client.get(path + "/evaluator").json()["release"]["feedback"] == feedback
        assert client.post(path + "/evaluator/build", json={"request_id": "revision-request", "feedback": "Different feedback"}).status_code == 409


def test_email_records_send_and_does_not_repeat_it(harness, monkeypatch):
    app, _, _ = harness
    delivered = []
    monkeypatch.setenv("AUTOKAGGLE_PUBLIC_BASE_URL", "https://lite.example.org")
    monkeypatch.setattr(lite_release.notifications, "email_login_available", lambda: True)
    monkeypatch.setattr(lite_release.notifications, "_send_message", delivered.append)
    with TestClient(app) as client:
        _, path = accepted(client, monkeypatch)
        build(client, path)
        release = settle(client, path + "/evaluator", lambda s: s["release"]["review_invitation"]["status"] == "sent")["release"]
        assert release["review_invitation"]["status"] == "sent"
        assert len(delivered) == 1
        assert "review=evaluator" in delivered[0].get_content()
        assert "Synthetic tests" in delivered[0].get_content()
        assert client.post(path + "/evaluator/review-email").status_code == 200
        assert len(delivered) == 1


def test_research_run_is_executed_then_requires_human_approval(harness, monkeypatch, tmp_path):
    app, _, _ = harness
    artifact = b"id,label\n0,0\n1,1\n2,0\n3,0\n4,0\n"
    import hashlib
    def fetch(url, **kwargs):
        Path(kwargs["destination"]).write_bytes(artifact)
        return b"", "text/csv", url
    monkeypatch.setattr(sources, "fetch", fetch)
    with TestClient(app) as client:
        identifier, path = accepted(client, monkeypatch)
        first = build(client, path)["release"]
        assert first["validation"]["research_data"] == "not_run"
        denied = client.post(path + "/evaluator/approve", json={"build_id": first["id"], "approved": True,
              "research_report_sha256": "a"*64, "note": "I reviewed the release."})
        assert denied.status_code == 409
        body = {"request_id": uuid.uuid4().hex, "artifact_url": "https://example.org/research.csv",
                "artifact_sha256": hashlib.sha256(artifact).hexdigest(), "artifact_bytes": len(artifact),
                "expected_fitness": 0.6, "expected_basis": "Three out of five labels agree, calculated independently by hand."}
        response = client.post(path + "/evaluator/research-check", json=body)
        assert response.status_code == 200, response.text
        view = settle(client, path + "/evaluator", lambda s: s["release"]["validation"]["research_data"] != "running")
        validation = view["release"]["validation"]
        assert validation["research_data"] == "validated", validation
        assert validation["research_evidence"]["observed_fitness"] == 0.6
        assert client.get(path + "/evaluator/research-report").json()["passed"] is True
        assert client.post(path + "/evaluator/research-check", json={**body, "expected_fitness": 0.9}).status_code == 409
        assert view["release"]["human_approval"] is None
        approval = {"build_id": first["id"], "approved": True, "research_report_sha256": validation["research_evidence"]["report_sha256"],
                    "note": "The declared rows and independent score agree."}
        approved = client.post(path + "/evaluator/approve", json=approval)
        assert approved.status_code == 200, approved.text
        assert approved.json()["release"]["human_approval"]["commit"] == first["evidence"]["commit"]
        assert approved.json()["release"]["registry"]["status"] == "not_eligible"  # no GitHub release in this unit test
        # Wrong research expectations cannot retain validation or approval.
        body.update(request_id=uuid.uuid4().hex, expected_fitness=1.0)
        assert client.post(path + "/evaluator/research-check", json=body).status_code == 200
        failed = settle(client, path + "/evaluator", lambda s: s["release"]["validation"]["research_data"] != "running")
        assert failed["release"]["validation"]["research_data"] == "failed"
        assert failed["release"]["human_approval"] is None
        assert client.post(path + "/evaluator/approve", json=approval).status_code == 409
