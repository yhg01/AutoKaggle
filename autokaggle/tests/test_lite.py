"""Contract, package, evidence, access, and recovery tests for internal Lite."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import time
import uuid
import zipfile
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from autokaggle import lite
from autokaggle.app import create_app
from autokaggle.store import Store


def contract(**changes):
    return {"bold_project_url": "https://bold-lab-ai.github.io/bold-os/project.html#id=diverging-runs", "title": "A small reproducible experiment", "objective": "Measure policy success under fixed conditions.",
        "task_kind": "environment", "source_url": "https://github.com/example/environment", "source_revision": "a"*40,
        "inputs": "A scalar observation", "allowed_data": "Only the declared training environment", "answer_exposure": "environment_generated",
        "artifact_type": "checkpoint", "outputs": "An integer action", "adapter_entrypoint": "adapter:evaluate",
        "metric": "success_rate", "success_definition": "The environment reaches its success state.",
        "evaluation_protocol": "One fresh process per seed; reset state; no adaptation.", "evaluation_count": 3,
        "failure_policy": "zero", "timeout_seconds": 5, "total_timeout_seconds": 15, "max_steps": 10,
        "training_policy": "Train from scratch", "compute_budget": "One CPU for 15 seconds", "dependencies": "Python 3.11; standard library",
        **changes}


def fixture_project(tmp_path, **changes):
    store = Store(tmp_path / "store")
    project = store.create("o"*40, "Example")
    project["lite"] = lite.initial()
    project["lite"]["contract"] = contract(**changes)
    return store, project


def proposal(c=None):
    return {"id": uuid.uuid4().hex, "contract": c or contract(), "evidence": {}, "summary": "Review the extracted contract.", "question": "", "created_at": "test"}


def manifest_for(project, directory):
    revision = project["lite"]["package"]["version"]
    with zipfile.ZipFile(directory / "lite" / revision / "research.zip") as z:
        result = json.loads(z.read("manifest.example.json"))
    result.update(code_repository="local:research-checkout", code_revision="a"*40,
        artifact_url="local:checkpoint.bin", artifact_sha256="b"*64, dependencies_sha256="c"*64,
        training_provenance="Local training run 1; fixed data and seeds.")
    return result


def records_for(project, directory):
    revision = project["lite"]["package"]["version"]
    document = json.loads((directory / "lite" / revision / "contract.json").read_text())
    return [{"seed": s, "status": "completed", "score": 1, "steps": 3} for s in document["seeds"]]


def test_six_groups_and_optional_reference():
    c = contract()
    assert lite.ready(c)
    assert len(lite.checklist(c)) == 6
    assert "baseline" not in {f for g in lite.checklist(c) for f in g["missing"]}
    del c["total_timeout_seconds"]
    assert not lite.ready(c)


def parsed_response(updates):
    return SimpleNamespace(model="live-interface-regression", usage=None,
        choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=json.dumps({
            "summary": "Review these proposed values.", "question": "Which environment should we use?", "updates": updates})))])


def test_invalid_exposure_enum_keeps_other_source_extraction():
    state = lite.initial()
    state["messages"].append({"role": "user", "content": "Measure ascension success."})
    result = lite.parse_proposal(state, parsed_response([
        {"field": "objective", "value_json": '"Measure ascension success."', "basis": "researcher", "evidence": "Measure ascension success."},
        {"field": "answer_exposure", "value_json": '"Trusted internal evaluation. Fixed seeds are visible."', "basis": "suggestion", "evidence": "Suggested protocol"},
    ]))
    assert result["contract"]["objective"] == "Measure ascension success."
    assert "answer_exposure" not in result["contract"]
    assert result["validation_notes"][0]["field"] == "answer_exposure"
    assert state["contract"] == {}


def test_source_quote_gets_pinned_citation_and_unmatched_quote_is_suggestion():
    state = lite.initial()
    state["sources"] = [{"kind": "repository", "url": "https://github.com/example/env", "commit": "a"*40,
                         "files": [{"text": 'Use info["success"] for the measured outcome.'}]}]
    result = lite.parse_proposal(state, parsed_response([
        {"field": "success_definition", "value_json": '"Environment success flag"', "basis": "source", "evidence": 'Use info["success"]'},
        {"field": "compute_budget", "value_json": "One GPU hour", "basis": "source", "evidence": "This phrase is not in the source"},
    ]))
    assert result["evidence"]["success_definition"]["source_revision"] == "a"*40
    assert result["evidence"]["compute_budget"]["basis"] == "suggestion"
    assert result["contract"]["compute_budget"] == "One GPU hour"


def test_unbounded_steps_is_explicit_and_wrong_number_is_not_invented():
    state = lite.initial()
    result = lite.parse_proposal(state, parsed_response([
        {"field": "max_steps", "value_json": "null", "basis": "suggestion", "evidence": "No step cutoff"},
        {"field": "evaluation_count", "value_json": "a hundred or so", "basis": "suggestion", "evidence": "Not decided"},
    ]))
    assert result["contract"]["max_steps"] is None
    assert "evaluation_count" not in result["contract"]
    assert result["validation_notes"]


@pytest.mark.parametrize("patch", [
    {"artifact_type": "predictions"}, {"metric": "rmse", "failure_policy": "zero"},
    {"source_url": "http://localhost/private"}, {"evaluation_count": True},
    {"evaluation_count": 0}, {"seed_start": 3, "seed_end": 1},
    {"seed_start": 1, "seed_end": 2}, {"adapter_entrypoint": "../shell:run"},
    {"environment_imports": ["os.system('bad')"]}, {"timeout_seconds": float("nan")},
    {"total_timeout_seconds": 0}, {"unknown": "unsupported"},
])
def test_invalid_contract_rejected(patch):
    with pytest.raises((ValueError, TypeError)):
        lite.clean_contract(contract(**patch))


def test_gym_adapter_requires_explicit_seed_and_success_policy():
    c = contract(adapter_entrypoint="gym_adapter:evaluate")
    missing = {f for group in lite.checklist(c) for f in group["missing"]}
    assert {"seed_method", "env_id", "success_key"} <= missing
    assert lite.ready({**c, "seed_method": "core_disp", "env_id": "Research-v0", "success_key": "goal_reached"})


def test_batch_contract_does_not_require_episodes():
    c = contract(task_kind="batch", artifact_type="predictions", metric="rmse", failure_policy="fail_run")
    del c["max_steps"]
    assert lite.ready(lite.clean_contract(c))


def test_package_versions_seeds_and_no_contact_leak(tmp_path):
    store, project = fixture_project(tmp_path)
    project["setup"] = {"organizer_email": "private@example.org"}
    directory = store.directory(project["id"])
    first = lite.build(project, directory)
    content = (directory / "lite" / first["version"] / "contract.json").read_bytes()
    second = lite.build(project, directory)
    assert first["version"] == second["version"]
    assert content == (directory / "lite" / second["version"] / "contract.json").read_bytes()
    with zipfile.ZipFile(directory / "lite" / first["version"] / "research.zip") as z:
        assert {"README.md", "AGENTS.md", "contract.json", "run.py", "adapter.py", "gym_adapter.py", "manifest.example.json", "results.example.json"} <= set(z.namelist())
        assert not any(b"private@example.org" in z.read(name) for name in z.namelist())
        assert b"not a blind holdout" in z.read("README.md")
    project["lite"]["contract"]["evaluation_count"] = 4
    assert lite.view(project)["package"]["status"] == "stale"
    new = lite.build(project, directory)
    assert new["version"] != first["version"]
    assert (directory / "lite" / first["version"] / "research.zip").exists()


def test_pending_proposal_cannot_build_or_reuse_artifacts(tmp_path):
    store, project = fixture_project(tmp_path)
    lite.build(project, store.directory(project["id"]))
    project["lite"]["proposal"] = proposal()
    assert lite.view(project)["package"]["status"] == "stale"
    assert not lite.view(project)["ready"]
    with pytest.raises(ValueError, match="pending proposal"):
        lite.build(project, store.directory(project["id"]))


def test_historical_result_uses_its_frozen_contract(tmp_path):
    store, project = fixture_project(tmp_path)
    directory = store.directory(project["id"])
    lite.build(project, directory)
    old_manifest = manifest_for(project, directory)
    old_records = records_for(project, directory)
    project["lite"]["contract"].update(task_kind="batch", metric="rmse", failure_policy="fail_run", evaluation_count=2)
    lite.build(project, directory)
    historical = lite.record_results(project, directory, "old-run-finishes", old_manifest, old_records)
    assert historical["historical_version"] is True
    assert historical["summary"]["metric"] == "success_rate"
    assert historical["summary"]["completed"] == 3
    assert len(project["lite"]["package_history"]) == 2


def test_local_source_is_a_reference_and_is_not_fetched():
    assert lite.clean_contract(contract(source_url="local:private-dataset.csv"))["source_url"] == "local:private-dataset.csv"


def test_revision_context_carries_checked_results_without_artifact_contents():
    state = lite.initial()
    state["results"] = [{"version": f"version-{i}", "summary": {"score": 0, "completed": 10, "failed": 90},
        "evidence_level": "evidence_checked", "independently_reproduced": False,
        "limitations": "This is a researcher report. No independent run was performed.",
        "manifest": {"artifact_url": "https://private.example/model?token=private-token"},
        "records": [{"status": "completed", "private_note": "must not enter model context"}]*10 + [{"status": "truncated"}]*90} for i in range(5)]
    context = lite.result_context(state)
    assert len(context) == 3 and context[0]["version"] == "version-2"
    assert context[-1]["summary"]["failed"] == 90
    assert context[-1]["status_counts"] == {"completed": 10, "failed": 0, "timeout": 0, "truncated": 90}
    assert context[-1]["independently_reproduced"] is False
    assert "private-token" not in json.dumps(context)
    assert "private_note" not in json.dumps(context)


def test_lite_handoff_checks_membership_before_consuming_and_returns_lite(app, monkeypatch):
    identities = {
        "owner": {"owner": "account_"+"a"*40, "email": "owner@example.org"},
        "lab": {"owner": "account_"+"b"*40, "email": "lab@example.org"},
        "outside": {"owner": "account_"+"c"*40, "email": "outside@example.org"},
    }
    access = app.state.access
    access.enabled = True
    monkeypatch.setattr(access, "user", lambda request: identities.get(request.cookies.get("test_identity")))
    monkeypatch.setenv("AUTOKAGGLE_LITE_MEMBERS", "owner@example.org,lab@example.org")
    with TestClient(app) as owner, TestClient(app) as lab, TestClient(app) as outside:
        owner.cookies.set("test_identity", "owner")
        lab.cookies.set("test_identity", "lab")
        outside.cookies.set("test_identity", "outside")
        created = owner.post("/api/lite/projects", json={"organizer_email": "owner@example.org", "storage_accepted": True})
        assert created.status_code == 200, created.text
        identifier = created.json()["id"]
        root = f"/api/projects/{identifier}"
        code = owner.post(root+"/handoff").json()["code"]
        denied = outside.post("/api/handoffs/redeem", json={"code": code, "accepted": True})
        assert denied.status_code == 403
        with app.state.store.connection() as con:
            assert con.execute("SELECT used FROM handoff_codes WHERE project=?", (identifier,)).fetchone()[0] == 0
            assert con.execute("SELECT count(*) FROM collaborators WHERE project=?", (identifier,)).fetchone()[0] == 0
        joined = lab.post("/api/handoffs/redeem", json={"code": code, "accepted": True})
        assert joined.status_code == 200, joined.text
        assert joined.json()["redirect"] == f"/lite?project={identifier}"
        assert lab.get(root+"/lite").status_code == 200
        member = owner.get(root+"/handoff").json()["members"][0]["id"]
        assert owner.delete(root+"/handoff/"+member).status_code == 200
        assert lab.get(root+"/lite").status_code == 404
        replacement = owner.post(root+"/handoff").json()["code"]
        assert lab.post("/api/handoffs/redeem", json={"code": replacement, "accepted": True}).status_code == 200
        member = lab.get(root+"/handoff").json()["members"][0]["id"]
        assert lab.delete(root+"/handoff/"+member).status_code == 200
        assert lab.get(root+"/lite").status_code == 404
        owner.post(root+"/handoff")
        assert owner.delete(root+"/handoff/codes").status_code == 200


def test_result_bindings_failure_scoring_and_replay(tmp_path):
    store, project = fixture_project(tmp_path)
    directory = store.directory(project["id"])
    lite.build(project, directory)
    manifest, records = manifest_for(project, directory), records_for(project, directory)
    records[1].update(status="timeout", score=10000)
    result = lite.record_results(project, directory, "request-1", manifest, records)
    assert result["summary"]["score"] == pytest.approx(2/3)
    assert result["records"][1]["score"] is None
    assert result["evidence_level"] == "evidence_checked"
    assert result["independently_reproduced"] is False
    assert "did not fetch" in result["limitations"]
    assert lite.record_results(project, directory, "request-1", manifest, records)["id"] == result["id"]
    records[0]["score"] = 0
    with pytest.raises(ValueError, match="different result"):
        lite.record_results(project, directory, "request-1", manifest, records)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "wrong_seed", "nan", "fractional_success", "wrong_version", "wrong_digest", "bad_commit"])
def test_bad_results_rejected(tmp_path, mutation):
    store, project = fixture_project(tmp_path)
    directory = store.directory(project["id"])
    lite.build(project, directory)
    manifest, records = manifest_for(project, directory), records_for(project, directory)
    if mutation == "missing": records.pop()
    elif mutation == "duplicate": records[1] = records[0]
    elif mutation == "wrong_seed": records[0]["seed"] = -1
    elif mutation == "nan": records[0]["score"] = float("nan")
    elif mutation == "fractional_success": records[0]["score"] = 0.5
    elif mutation == "wrong_version": manifest["challenge_version"] = "old"
    elif mutation == "wrong_digest": manifest["contract_sha256"] = "bad"
    elif mutation == "bad_commit": manifest["code_revision"] = "main"
    with pytest.raises(ValueError): lite.record_results(project, directory, mutation, manifest, records)
    assert project["lite"]["results"] == []


def test_rmse_failure_does_not_reward_failure(tmp_path):
    store, project = fixture_project(tmp_path, task_kind="batch", metric="rmse", failure_policy="fail_run")
    directory = store.directory(project["id"])
    lite.build(project, directory)
    manifest, records = manifest_for(project, directory), records_for(project, directory)
    records[0].update(status="failed", score=None)
    result = lite.record_results(project, directory, "failure-1", manifest, records)
    assert result["summary"]["status"] == "incomplete"
    assert result["summary"]["score"] is None


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOKAGGLE_PRIVATE_MODE", "0")
    app = create_app(tmp_path / "app")
    yield app
    app.state.pool.shutdown(wait=True)


def create(client):
    response = client.post("/api/lite/projects", json={"organizer_email": "lab@example.org", "storage_accepted": True})
    assert response.status_code == 200, response.text
    return response.json(), "/api/projects/" + response.json()["id"] + "/lite"


def wait(client, path):
    for _ in range(100):
        state = client.get(path).json()
        if state["status"] != "working":
            return state
        time.sleep(0.01)
    raise AssertionError("Worker did not finish")


def test_http_full_flow_and_private_access(app, monkeypatch):
    monkeypatch.setattr(lite, "propose", lambda state: proposal())
    with TestClient(app) as client:
        state, path = create(client)
        identifier = state["id"]
        payload = {"request_id": "first-request", "message": "Use this fixed evaluation setup."}
        assert client.post(path+"/message", json=payload).status_code == 200
        state = wait(client, path)
        assert not state["contract"]
        assert client.post(path+"/message", json=payload).status_code == 200
        assert len([m for m in client.get(path).json()["messages"] if m["role"] == "user"]) == 1
        assert client.post(path+"/accept", json={"proposal_id": state["proposal"]["id"]}).status_code == 200
        state = client.post(path+"/build", json={"request_id": "build-request"}).json()
        assert state["package"]["status"] == "ready"
        archive = client.get(path+"/package")
        assert archive.status_code == 200
        config = client.get(path+"/config")
        assert config.status_code == 200
        assert 'filename="contract.json"' in config.headers['content-disposition']
        with zipfile.ZipFile(io.BytesIO(archive.content)) as zipped:
            assert config.content == zipped.read('contract.json')
        assert state['package']['config_url'] == path+'/config'
        assert client.get(path+"/preview").status_code == 200
        assert client.get(path+"/readme.md").status_code == 200
        assert client.get("/api/projects").json()["projects"] == []
        assert client.get("/api/lite/projects").json()["projects"][0]["id"] == identifier
        assert client.post(f"/api/projects/{identifier}/conversation/messages", json=payload).status_code == 409
        store = app.state.store
        item = store.get(identifier, client.cookies["autokaggle_owner"])
        directory = store.directory(identifier)
        result = client.post(path+"/results", json={"request_id": "submit-results", "manifest": manifest_for(item, directory), "results": records_for(item, directory)})
        assert result.status_code == 200, result.text
        assert result.json()["results"][0]["summary"]["score"] == 1
        with TestClient(app) as other:
            assert other.get(path).status_code == 404
            assert other.get(path+"/package").status_code == 404
            assert other.get(path+"/config").status_code == 404
        assert client.request("DELETE", f"/api/projects/{identifier}", json={"confirm": True}).status_code == 200
        assert client.get(path).status_code == 404


def test_separate_lite_host_default_preserves_project_without_workbench(app, monkeypatch):
    with TestClient(app) as client:
        monkeypatch.setenv("AUTOKAGGLE_DEFAULT_INTERFACE", "lite")
        assert client.get("/", follow_redirects=False).headers["location"] == "/lite"
        response = client.get("/?project=example&view=review", follow_redirects=False)
        assert response.headers["location"] == "/lite?project=example"
        monkeypatch.delenv("AUTOKAGGLE_DEFAULT_INTERFACE")
        assert client.get("/", follow_redirects=False).status_code == 200


def test_worker_count_supports_bounded_parallel_interviews(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOKAGGLE_WORKERS", "5")
    instance = create_app(tmp_path / "parallel")
    assert instance.state.pool._max_workers == 5
    instance.state.pool.shutdown(wait=True)
    for value in ("0", "9", "invalid"):
        monkeypatch.setenv("AUTOKAGGLE_WORKERS", value)
        with pytest.raises(ValueError):
            create_app(tmp_path / value)


def test_fixed_horizon_is_explicit_and_requires_finite_environment_limit():
    assert lite.clean_contract(contract(horizon_policy="fixed_horizon"))["horizon_policy"] == "fixed_horizon"
    for c in (contract(horizon_policy="fixed_horizon", max_steps=None),
              contract(horizon_policy="fixed_horizon", task_kind="batch", artifact_type="predictions")):
        with pytest.raises(ValueError, match="fixed horizon"):
            lite.clean_contract(c)
    state = lite.initial()
    state["contract"] = contract()
    parsed = lite.parse_proposal(state, parsed_response([
        {"field": "horizon_policy", "value_json": '"fixed_horizon"', "basis": "suggestion", "evidence": "Explicit finite horizon"}]))
    assert parsed["contract"]["horizon_policy"] == "fixed_horizon"


def test_config_download_blocks_stale_contract(app, monkeypatch):
    monkeypatch.setattr(lite, "propose", lambda state: proposal())
    with TestClient(app) as client:
        _, path = create(client)
        assert client.get(path+"/config").status_code == 409
        client.post(path+"/message", json={"request_id":"config-message", "message":"Define the experiment."})
        state = wait(client, path)
        client.post(path+"/accept", json={"proposal_id":state["proposal"]["id"]})
        client.post(path+"/build", json={"request_id":"config-build"})
        assert client.get(path+"/config").status_code == 200
        client.post(path+"/message", json={"request_id":"config-revision", "message":"Revise the experiment."})
        wait(client, path)
        assert client.get(path+"/config").status_code == 409


def test_failed_worker_can_retry_without_duplicate_message(app, monkeypatch):
    def fail(state): raise ValueError("Model unavailable")
    monkeypatch.setattr(lite, "propose", fail)
    with TestClient(app) as client:
        _, path = create(client)
        client.post(path+"/message", json={"request_id": "first-message", "message": "A research objective"})
        assert wait(client, path)["status"] == "error"
        monkeypatch.setattr(lite, "propose", lambda state: proposal())
        assert client.post(path+"/retry", json={"request_id": "retry-message"}).status_code == 200
        state = wait(client, path)
        assert state["status"] == "idle"
        assert len([m for m in state["messages"] if m["role"] == "user"]) == 1


def test_restart_recovers_lite_pending_job(tmp_path):
    store, project = fixture_project(tmp_path)
    project["lite"].update(status="working", job_id="pending")
    store.save(project)
    restarted = Store(store.root).get(project["id"], "o"*40)
    assert restarted["lite"]["status"] == "error"
    assert restarted["lite"]["job_id"] is None


def test_hosted_lite_membership_is_not_any_valid_login(monkeypatch):
    class Access:
        enabled = True
        def is_admin(self, request): return False
        def user(self, request): return {"email": "external@example.org"}
    monkeypatch.delenv("AUTOKAGGLE_LITE_MEMBERS", raising=False)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc: lite.require_member(Access(), None)
    assert exc.value.status_code == 403
    monkeypatch.setenv("AUTOKAGGLE_LITE_MEMBERS", "external@example.org")
    lite.require_member(Access(), None)


def test_pdf_upload_rejects_non_pdf_and_source_import_needs_link(app):
    with TestClient(app) as client:
        _, path = create(client)
        assert client.post(path+"/paper", files={"file": ("bad.pdf", b"not pdf", "application/pdf")}).status_code == 422
        assert client.post(path+"/import", json={"request_id": "empty-import"}).status_code == 422
        assert client.post(path+"/import", json={"request_id": "bad-source", "paper_url": "file:///etc/passwd"}).status_code == 422


@pytest.mark.parametrize("slow", [False, True])
def test_local_runner_executes_adapter_and_binds_artifact(tmp_path, slow):
    from autokaggle.lite_runner import run
    store, project = fixture_project(tmp_path, timeout_seconds=1 if slow else 5, total_timeout_seconds=1 if slow else 15)
    directory = store.directory(project["id"])
    lite.build(project, directory)
    package = tmp_path / "package"
    with zipfile.ZipFile(directory / "lite" / project["lite"]["package"]["version"] / "research.zip") as z: z.extractall(package)
    repo = tmp_path / "code"
    repo.mkdir()
    (repo / "adapter.py").write_text("def evaluate(seed, manifest, contract):\n" + ("    import time; time.sleep(2)\n" if slow else "") + "    return {'seed': seed, 'status': 'completed', 'steps': 1, 'score': 1}\n")
    (repo / "checkpoint.bin").write_bytes(b"small real artifact")
    (repo / "requirements.lock").write_text("standard-library\n")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.org", "commit", "-qm", "Fixture"], cwd=repo, check=True)
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()
    manifest = manifest_for(project, directory)
    manifest.update(code_directory=str(repo), code_revision=revision, artifact_path=str(repo/"checkpoint.bin"),
        artifact_sha256=hashlib.sha256((repo/"checkpoint.bin").read_bytes()).hexdigest(), dependencies_path=str(repo/"requirements.lock"),
        dependencies_sha256=hashlib.sha256((repo/"requirements.lock").read_bytes()).hexdigest())
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    result = run(package, path, tmp_path / "result.json")
    assert result["summary"]["score"] == (0 if slow else 1)
    if slow:
        assert [r["status"] for r in result["results"]] == ["timeout"]*3
        assert result["results"][1]["elapsed_seconds"] == 0
    assert result["evidence_level"] == "researcher_reported"
    manifest["artifact_sha256"] = "0"*64
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="SHA-256"): run(package, path, tmp_path / "invalid.json")


def test_local_runner_contract_tamper_rejected(tmp_path):
    from autokaggle.lite_runner import run
    store, project = fixture_project(tmp_path)
    directory = store.directory(project["id"])
    lite.build(project, directory)
    package = directory / "lite" / project["lite"]["package"]["version"]
    path = package / "contract.json"
    record = json.loads(path.read_text())
    record["seeds"][0] += 1
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="changed"): run(package, tmp_path/"unused.json", tmp_path/"result.json")


def test_http_repeated_accept_does_not_duplicate_history(app, monkeypatch):
    monkeypatch.setattr(lite, "propose", lambda state: proposal())
    with TestClient(app) as client:
        _, path = create(client)
        client.post(path+"/message", json={"request_id": "accept-replay", "message": "Use this experiment."})
        pending = wait(client, path)["proposal"]
        assert client.post(path+"/accept", json={"proposal_id": pending["id"]}).status_code == 200
        before = client.get(path).json()
        assert client.post(path+"/accept", json={"proposal_id": pending["id"]}).status_code == 200
        assert client.get(path).json() == before


def decision_response(updates=None, **assessment):
    response = parsed_response(updates or [])
    payload = json.loads(response.choices[0].message.content)
    payload.update(assessment)
    response.choices[0].message.content = json.dumps(payload)
    return response


def test_populated_open_decision_blocks_build_and_preserves_historical_results(tmp_path):
    store, project = fixture_project(tmp_path)
    directory = store.directory(project['id'])
    lite.build(project, directory)
    manifest, records = manifest_for(project, directory), records_for(project, directory)
    gap = {'field': 'outputs', 'reason': 'The random-number generator remains unknown.'}
    project['lite']['open_decisions'] = [gap]
    assert not lite.view(project)['ready']
    assert lite.view(project)['package']['status'] == 'stale'
    with pytest.raises(ValueError, match='outputs'):
        lite.build(project, directory)
    saved = lite.record_results(project, directory, 'historical-run', manifest, records)
    assert saved['summary']['completed'] == 3
    assert project['lite']['results'][-1]['id'] == saved['id']


def test_gap_resolution_requires_explicit_reason_and_matching_valid_update():
    state = lite.initial()
    state['contract'] = contract()
    state['open_decisions'] = [{'field': 'outputs', 'reason': 'Define the RNG.'}, {'field': 'inputs', 'reason': 'Define dtype.'}]
    update = {'field': 'outputs', 'value_json': '"Integer action; uniform random choice."', 'basis': 'suggestion', 'evidence': 'Proposed choice.'}
    for assessment in ({}, {'open_decisions': []}, {'open_decisions': [], 'resolved_decisions': []}):
        assert lite.parse_proposal(state, decision_response([update], **assessment))['open_decisions'] == state['open_decisions']
    resolution = [{'field': 'outputs', 'reason': 'The updated policy specifies its RNG.'}]
    assert lite.parse_proposal(state, decision_response(open_decisions=[], resolved_decisions=resolution))['open_decisions'] == state['open_decisions']
    result = lite.parse_proposal(state, decision_response([update], open_decisions=[], resolved_decisions=resolution))
    assert result['open_decisions'] == [state['open_decisions'][1]]
    before = copy.deepcopy(state)
    with pytest.raises(ValueError, match='invalid contract'):
        lite.parse_proposal(state, decision_response(open_decisions=[{'field': 'unsupported', 'reason': 'Unknown field.'}]))
    assert state == before


def test_optional_reference_never_blocks_and_dynamic_gaps_count_once():
    assert lite.ready(contract(), [{'field': 'baseline', 'reason': 'No known baseline.'}])
    c = contract(adapter_entrypoint='gym_adapter:evaluate', env_id='Test-v0', seed_method='reset', success_key='success')
    gaps = [{'field': field, 'reason': 'Needs a decision.'} for field in ('env_id', 'seed_method', 'success_key')]
    missing = [field for group in lite.checklist(c, gaps) for field in group['missing']]
    assert sorted(missing) == sorted(item['field'] for item in gaps)


def test_accepted_gap_blocks_downloads_manual_edit_and_stale_accept(app, monkeypatch):
    pending = proposal()
    monkeypatch.setattr(lite, 'propose', lambda state: copy.deepcopy(pending))
    with TestClient(app) as client:
        _, path = create(client)
        def propose_and_accept():
            client.post(path+'/message', json={'request_id': uuid.uuid4().hex, 'message': 'Review the current contract.'})
            wait(client, path)
            response = client.post(path+'/accept', json={'proposal_id': pending['id']})
            assert response.status_code == 200
            return response.json()
        propose_and_accept()
        assert client.post(path+'/build', json={'request_id': uuid.uuid4().hex}).status_code == 200
        first_config = client.get(path+'/config').content
        original = pending['id']
        pending = {**proposal(), 'open_decisions': [{'field':'outputs','reason':'Define RNG.'}, {'field':'inputs','reason':'Define dtype.'}]}
        state = propose_and_accept()
        assert not state['ready']
        for route in ('config', 'package'):
            assert client.get(path+'/'+route).status_code == 409
        assert client.post(path+'/accept', json={'proposal_id': original}).status_code == 422
        pending = {**proposal(), 'open_decisions': state['open_decisions']}
        client.post(path+'/message', json={'request_id':uuid.uuid4().hex,'message':'I will define the output.'})
        wait(client, path)
        edited = {**pending['contract'], 'outputs': 'Uniform integer action using Python random.Random(seed).'}
        state = client.post(path+'/accept', json={'proposal_id':pending['id'],'contract':edited}).json()
        assert state['open_decisions'] == [{'field':'inputs','reason':'Define dtype.'}]
        pending = {**proposal(), 'open_decisions': [], 'resolved_decisions': [{'field':'inputs','reason':'Scalar float32.'}]}
        state = propose_and_accept()
        assert state['ready'] and state['package']['status'] == 'stale'
        assert client.get(path+'/config').status_code == 409
        client.post(path+'/build', json={'request_id':uuid.uuid4().hex})
        assert client.get(path+'/config').content == first_config


@pytest.mark.parametrize("invalid", [{"steps": 100}, {"elapsed_seconds": float("inf")}, {"elapsed_seconds": 8}, {"secret_log": "not an episode field"}])
def test_result_limits_and_fields_are_checked(tmp_path, invalid):
    store, project = fixture_project(tmp_path)
    directory = store.directory(project["id"])
    lite.build(project, directory)
    records = records_for(project, directory)
    records[0].update(invalid)
    with pytest.raises(ValueError): lite.record_results(project, directory, "invalid-record", manifest_for(project, directory), records)


def test_actual_pdf_upload_extracts_and_preserves_private_source(app):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer = PdfWriter()
    page = writer.add_blank_page(width=500, height=600)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 10 30 Td (" + b"A paper about source evidence and a reproducible evaluation. "*5 + b") Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    buffer = io.BytesIO()
    writer.write(buffer)
    with TestClient(app) as client:
        state, path = create(client)
        response = client.post(path+"/paper", files={"file": ("source.pdf", buffer.getvalue(), "application/pdf")})
        assert response.status_code == 200, response.text
        assert len(response.json()["sources"][0]["sha256"]) == 64
        assert "text" not in response.json()["sources"][0]
        assert response.json()["contract"] == {}


def test_gym_adapter_requires_success_information_and_preserves_truncation(monkeypatch):
    import sys
    from autokaggle.lite_gym_adapter import evaluate
    events = []
    class Env:
        unwrapped = None
        def __init__(self): self.unwrapped = self
        def seed(self, **kwargs): events.append(kwargs)
        def reset(self, **kwargs): return 0, {}
        def step(self, action): return 1, 0, True, False, {"goal": True}
        def close(self): events.append("closed")
    class Policy:
        def reset(self): events.append("policy reset")
        def act(self, observation): return 0
    env = Env()
    monkeypatch.setitem(sys.modules, "gymnasium", SimpleNamespace(make=lambda *a, **k: env))
    monkeypatch.setitem(sys.modules, "test_policy", SimpleNamespace(load=lambda path: Policy()))
    settings = contract(adapter_entrypoint="gym_adapter:evaluate", env_id="Test-v0", seed_method="core_disp", success_key="goal")
    result = evaluate(123, {"policy_loader": "test_policy:load", "artifact_path": "unused"}, settings)
    assert result["score"] == 1 and result["status"] == "completed"
    assert {"core": 123, "disp": 123, "reseed": False} in events
    env.step = lambda action: (1, 0, False, True, {"goal": True})
    assert evaluate(123, {"policy_loader": "test_policy:load", "artifact_path": "unused"}, settings)["status"] == "truncated"
    env.step = lambda action: (1, 0, True, False, {})
    with pytest.raises(ValueError, match="success key"):
        evaluate(123, {"policy_loader": "test_policy:load", "artifact_path": "unused"}, settings)


@pytest.mark.parametrize("flag", ["false", "true", 2, -1, {}, [True]])
def test_gym_success_status_cannot_turn_arbitrary_values_into_success(monkeypatch,flag):
    import sys
    from autokaggle.lite_gym_adapter import evaluate
    class Env:
        def reset(self,**kwargs):return 0,{}
        def step(self,action):return 0,0,True,False,{"goal":flag}
        def close(self):pass
    monkeypatch.setitem(sys.modules,"gymnasium",SimpleNamespace(make=lambda *a,**k:Env()))
    monkeypatch.setitem(sys.modules,"test_policy",SimpleNamespace(load=lambda path:SimpleNamespace(act=lambda obs:0)))
    c=contract(adapter_entrypoint="gym_adapter:evaluate",env_id="Test-v0",seed_method="reset",success_key="goal")
    with pytest.raises(ValueError,match="boolean"):
        evaluate(1,{"policy_loader":"test_policy:load","artifact_path":"unused"},c)
