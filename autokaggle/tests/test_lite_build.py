"""Evaluator build, release, and clean-clone acceptance tests for internal Lite.

A stand-in agent writes the evaluator files, so these tests need no model service.
They run the real runner, the real acceptance checks, and real Git clones.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fastapi.testclient import TestClient
import httpx
import pytest

from autokaggle import lite, lite_acceptance as acceptance, lite_build, lite_providers, lite_publish
from autokaggle.app import create_app
from autokaggle.lite_gateway import Gateway

AGENT = r'''
import json, os, sys
from pathlib import Path
work, mode = Path(sys.argv[1]), sys.argv[2]
if mode == "silent":
    raise SystemExit(3)
if mode == "blocked":
    (work / "BUILD_REPORT.json").write_text(json.dumps({"status": "blocked", "summary": "The label file version is not defined.",
        "blockers": [{"field": "source_revision", "reason": "Which label release should scoring use? The two releases differ in 40 rows."},
                     {"field": "not_a_field", "reason": "An unknown field is kept as other."}], "decisions": []}))
    raise SystemExit(0)
(work / "toy_adapter.py").write_text("""
import csv, random
TRUTH = [0, 1, 1, 0, 1]
def evaluate(seed, manifest, contract):
    with open(manifest["artifact_path"]) as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ["id", "label"]:
            raise ValueError("The prediction file needs exactly the columns id,label.")
        rows = list(reader)
    if sorted(int(r["id"]) for r in rows) != list(range(5)):
        raise ValueError("Predict every id from 0 to 4 once.")
    random.Random(seed).shuffle(rows)
    return {"seed": seed, "status": "completed", "steps": 5, "score": sum(int(r["label"]) == TRUTH[int(r["id"])] for r in rows) / 5}
""")
(work / "requirements.lock").write_text("# standard library only\n")
(work / "assets.json").write_text("[]")
for name, labels in (("valid", [0, 1, 1, 0, 1]), ("wrong", [0, 1, 1, 1, 0])):
    (work / "fixtures" / name).mkdir(parents=True)
    (work / "fixtures" / name / "predictions.csv").write_text("id,label\n" + "".join(f"{i},{v}\n" for i, v in enumerate(labels)))
(work / "fixtures" / "invalid").mkdir()
(work / "fixtures" / "invalid" / "predictions.csv").write_text("row,guess\n0,1\n")
valid = 0.9 if mode == "wrong-expectation" else 1.0
(work / "fixtures" / "expected.json").write_text(json.dumps({"tolerance": 1e-9, "cases": {
    "valid": {"artifact": "fixtures/valid/predictions.csv", "expected_score": valid, "basis": "Every label equals the published answer, so accuracy is one."},
    "wrong": {"artifact": "fixtures/wrong/predictions.csv", "expected_score": 0.6, "basis": "Rows 3 and 4 are flipped, so three of five are correct."},
    "invalid": {"artifact": "fixtures/invalid/predictions.csv", "basis": "The header is row,guess instead of id,label."}}}))
header = "import toy_adapter\n" if mode == "cheat" else ""
(work / "fixtures" / "check_expected.py").write_text(header + f"""
import csv, json
truth = [0, 1, 1, 0, 1]
def accuracy(name):
    rows = list(csv.DictReader(open(f"fixtures/{{name}}/predictions.csv")))
    return sum(int(r["label"]) == truth[int(r["id"])] for r in rows) / 5
print(json.dumps({{"valid": {valid} if {valid} != 1.0 else accuracy("valid"), "wrong": accuracy("wrong")}}))
""")
if mode == "token":
    config = json.loads(Path(os.environ["OPENCODE_CONFIG"]).read_text())
    (work / "NOTES.md").write_text("token " + config["provider"]["lite"]["options"]["apiKey"])
if mode == "edit-trusted":
    (work / "evaluate.py").write_text("print('{\"fitness\": 1.0}')\n")
    (work / "extra.txt").write_text("not publishable")
(work / "BUILD_REPORT.json").write_text(json.dumps({"status": "ready", "summary": "Built a five-row accuracy scorer.", "blockers": [], "decisions": ["Used csv from the standard library."]}))
'''


def contract(**changes):
    return {"title": "Toy label accuracy", "objective": "Measure label accuracy on five fixed rows.", "task_kind": "batch",
            "source_url": "https://github.com/example/toy-labels", "source_revision": "a" * 40, "inputs": "Five rows with ids 0 to 4.",
            "allowed_data": "Only the five published rows.", "answer_exposure": "visible", "artifact_type": "predictions",
            "outputs": "CSV with columns id,label and one row per id.", "adapter_entrypoint": "toy_adapter:evaluate", "metric": "accuracy",
            "success_definition": "A row is correct when its label equals the published answer.",
            "evaluation_protocol": "Score all five rows in each seeded run. Seeds change row order only.", "evaluation_count": 3,
            "failure_policy": "zero", "timeout_seconds": 20, "total_timeout_seconds": 60, "training_policy": "No training.",
            "compute_budget": "One CPU for one minute", "dependencies": "Python 3.11 or later; standard library only", **changes}


@pytest.fixture
def harness(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOKAGGLE_PRIVATE_MODE", "0")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-provider-key")
    script = tmp_path / "agent.py"
    script.write_text(AGENT)
    mode = {"value": "ok"}
    monkeypatch.setattr(lite_build, "default_runtime", lambda: lite_build.LocalRuntime())
    monkeypatch.setattr(lite_build, "agent_command", lambda model: ["{python}", str(script), "{work}", mode["value"]])
    app = create_app(tmp_path / "app")
    yield app, mode, tmp_path
    app.state.pool.shutdown(wait=True)


def accepted(client, monkeypatch, **changes):
    created = client.post("/api/lite/projects", json={"organizer_email": "lab@example.org", "storage_accepted": True}).json()
    path = f"/api/projects/{created['id']}/lite"
    revise(client, monkeypatch, path, **changes)
    return created["id"], path


def revise(client, monkeypatch, path, **changes):
    monkeypatch.setattr(lite, "propose", lambda state: {"id": uuid.uuid4().hex, "contract": contract(**changes), "evidence": {},
                                                        "summary": "Review the contract.", "question": "", "created_at": "test"})
    assert client.post(path + "/message", json={"request_id": uuid.uuid4().hex, "message": "Define the experiment."}).status_code == 200
    state = settle(client, path, lambda s: s["status"] != "working")
    assert client.post(path + "/accept", json={"proposal_id": state["proposal"]["id"]}).status_code == 200


def settle(client, path, done, seconds=120):
    deadline = time.monotonic() + seconds
    while True:
        state = client.get(path).json()
        if done(state):
            return state
        assert time.monotonic() < deadline, state
        time.sleep(0.1)


def build(client, path, expect=200):
    response = client.post(path + "/evaluator/build", json={"request_id": uuid.uuid4().hex})
    assert response.status_code == expect, response.text
    if expect != 200:
        return response.json()
    return settle(client, path + "/evaluator", lambda s: s["status"] not in lite_build.ACTIVE)


def test_ready_release_scores_from_a_collaborator_clone_and_binds_evidence(harness, monkeypatch, tmp_path):
    app, mode, _ = harness
    with TestClient(app) as client:
        identifier, path = accepted(client, monkeypatch)
        before = client.get(path + "/evaluator").json()
        assert before["status"] == "not_built" and before["draft"] and before["release"] is None
        assert client.get(path + "/evaluator/bundle").status_code == 409
        state = build(client, path)
        assert state["status"] == "ready" and not state["draft"], state
        release = state["release"]
        package = client.get(path).json()["package"]
        assert release["contract_version"] == package["version"] == state["contract"]["version"]
        names = [t["name"] for t in release["tests"]]
        assert names == ["fresh clone", "release contents", "fresh environment", "declared assets", "independent calculation",
                         "valid example", "wrong example", "wrong example scores worse", "invalid artifact rejected", "checkout unchanged"]
        assert all(t["passed"] for t in release["tests"])
        evidence = release["evidence"]
        assert evidence["expected_fitness"] == evidence["observed_fitness"] == 1.0 and evidence["tag"] == "v1"
        assert release["model"]["agent"] == "opencode" and release["runtime"]["kind"] == "local"
        job = Path(app.state.store.directory(identifier)) / "lite-evaluator" / "jobs" / release["id"]
        assert not (job / "work").exists() and not (job / "home").exists()

        # A collaborator clones the downloaded release and scores an artifact with one command.
        bundle = tmp_path / "evaluator.bundle"
        bundle.write_bytes(client.get(release["bundle_url"]).content)
        clone = tmp_path / "collaborator"
        subprocess.run(["git", "clone", "-q", str(bundle), str(clone)], check=True)
        subprocess.run(["git", "checkout", "-q", "v1"], cwd=clone, check=True, capture_output=True)
        assert subprocess.run(["git", "rev-parse", "HEAD"], cwd=clone, capture_output=True, text=True).stdout.strip() == evidence["commit"]
        own = tmp_path / "my-predictions.csv"
        own.write_text("id,label\n0,0\n1,1\n2,0\n3,0\n4,0\n")
        done = subprocess.run([sys.executable, "evaluate.py", "--artifact", str(own), "--output", "results.json"], cwd=clone, capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
        summary = json.loads(done.stdout.strip().splitlines()[-1])
        assert summary["fitness"] == 0.6 and summary["direction"] == "maximize" and summary["evaluator_revision"] == evidence["commit"]
        # The same result file is accepted by the existing Lite results control.
        results = json.loads((clone / "results.json").read_text())
        saved = client.post(path + "/results", json={"request_id": "collaborator-result", "manifest": results["manifest"], "results": results["results"]})
        assert saved.status_code == 200, saved.text
        assert saved.json()["results"][-1]["summary"]["score"] == 0.6
        # A file that violates the format gets no fitness, even though the zero failure rule lets the runner report 0.0.
        bad = tmp_path / "bad.csv"
        bad.write_text("row,guess\n0,1\n")
        refused = subprocess.run([sys.executable, "evaluate.py", "--artifact", str(bad), "--output", "bad.json"], cwd=clone, capture_output=True, text=True)
        answer = json.loads(refused.stdout.strip().splitlines()[-1])
        assert refused.returncode == 2 and answer["fitness"] is None and answer["status"] == "no_completed_seed" and answer["completed"] == 0
        assert "exactly the columns id,label" in refused.stderr
        # A changed release file or a missing Git checkout is refused.
        (clone / "toy_adapter.py").write_text((clone / "toy_adapter.py").read_text() + "\n# changed\n")
        changed = subprocess.run([sys.executable, "evaluate.py", "--artifact", str(own)], cwd=clone, capture_output=True, text=True)
        assert changed.returncode == 1 and "differs from the release" in changed.stderr

        config = client.get(release["config_url"]).text
        assert f'version: "{package["version"]}"' in config and 'direction: "maximize"' in config
        assert "python evaluate.py --artifact fixtures/valid/predictions.csv" in client.get(release["readme_url"]).text
        yaml = pytest.importorskip("yaml")
        parsed = yaml.safe_load(config)
        frozen = json.loads(client.get(path + "/config").text)
        assert parsed["protocol"]["seeds"] == frozen["seeds"] and parsed["contract"]["sha256"] == frozen["contract_sha256"]
        assert parsed["metric"] == {"name": "accuracy", "definition": frozen["contract"]["success_definition"], "direction": "maximize", "aggregation": "mean over the fixed seeds",
                                    "failure_policy": "zero", "success_definition": frozen["contract"]["success_definition"]}


def test_contract_change_requires_a_new_build_and_keeps_the_earlier_release(harness, monkeypatch, tmp_path):
    app, mode, _ = harness
    with TestClient(app) as client:
        identifier, path = accepted(client, monkeypatch)
        first = build(client, path)["release"]
        revise(client, monkeypatch, path, evaluation_count=4)
        stale = client.get(path + "/evaluator").json()
        assert stale["status"] == "stale" and stale["draft"] and stale["release"] is None and stale["latest"] is None
        assert client.get(path + "/evaluator/bundle").status_code == 409
        second = build(client, path)
        assert second["status"] == "ready" and second["release"]["evaluator_version"] == 2
        assert second["release"]["contract_version"] != first["contract_version"]
        assert [e["commit"] for e in second["earlier_releases"]] == [first["evidence"]["commit"]]
        repo = Path(app.state.store.directory(identifier)) / "lite-evaluator" / "repo.git"
        tags = subprocess.run(["git", "tag"], env={**os.environ, "GIT_DIR": str(repo)}, capture_output=True, text=True).stdout.split()
        assert tags == ["v1", "v2"]
        log = subprocess.run(["git", "log", "--format=%H", "main"], env={**os.environ, "GIT_DIR": str(repo)}, capture_output=True, text=True).stdout.split()
        assert log == [second["release"]["evidence"]["commit"], first["evidence"]["commit"]]


@pytest.mark.parametrize("agent_mode,status,text", [
    ("blocked", "blocked", "decision or input"),
    ("silent", "failed", "could not reach the model service"),
    ("wrong-expectation", "failed", "valid example"),
    ("cheat", "failed", "without the evaluator code"),
    ("token", "failed", "model token"),
])
def test_incomplete_builds_stay_draft_and_show_the_cause(harness, monkeypatch, agent_mode, status, text):
    app, mode, _ = harness
    mode["value"] = agent_mode
    with TestClient(app) as client:
        identifier, path = accepted(client, monkeypatch)
        state = build(client, path)
        assert state["status"] == status and state["draft"] and state["release"] is None, state
        assert text in state["latest"]["cause"], state["latest"]["cause"]
        assert client.get(path + "/evaluator/bundle").status_code == 409
        if agent_mode == "blocked":
            assert state["latest"]["blockers"] == [
                {"field": "source_revision", "reason": "Which label release should scoring use? The two releases differ in 40 rows."},
                {"field": "other", "reason": "An unknown field is kept as other."}]
        repo = Path(app.state.store.directory(identifier)) / "lite-evaluator" / "repo.git"
        if repo.exists():
            refs = subprocess.run(["git", "for-each-ref"], env={**os.environ, "GIT_DIR": str(repo)}, capture_output=True, text=True).stdout
            assert refs.strip() == ""
        # A later correct build for the same contract becomes the release.
        mode["value"] = "ok"
        assert build(client, path)["status"] == "ready"


def test_release_uses_application_files_and_only_publishable_agent_files(harness, monkeypatch, tmp_path):
    app, mode, _ = harness
    mode["value"] = "edit-trusted"
    with TestClient(app) as client:
        _, path = accepted(client, monkeypatch)
        release = build(client, path)["release"]
        bundle = tmp_path / "evaluator.bundle"
        bundle.write_bytes(client.get(release["bundle_url"]).content)
        subprocess.run(["git", "clone", "-q", str(bundle), str(tmp_path / "clone")], check=True)
        clone = tmp_path / "clone"
        assert (clone / "evaluate.py").read_bytes() == (lite_build.HERE / "lite_evaluator_cli.py").read_bytes()
        assert (clone / "run.py").read_bytes() == (lite_build.HERE / "lite_runner.py").read_bytes()
        tracked = set(subprocess.run(["git", "ls-files"], cwd=clone, capture_output=True, text=True).stdout.split())
        assert tracked == {".gitignore", ".gitattributes", "revision.txt", "README.md", "assets.json", "contract.json", "evaluate.py", "evaluation.yaml", "evaluator.lock.json",
                           "fetch_assets.py", "gym_adapter.py", "requirements.lock", "run.py", "toy_adapter.py", "fixtures/check_expected.py",
                           "fixtures/expected.json", "fixtures/valid/predictions.csv", "fixtures/wrong/predictions.csv", "fixtures/invalid/predictions.csv"}


def test_build_requests_are_gated_and_idempotent(harness, monkeypatch):
    app, mode, _ = harness
    with TestClient(app) as client:
        created = client.post("/api/lite/projects", json={"organizer_email": "lab@example.org", "storage_accepted": True}).json()
        path = f"/api/projects/{created['id']}/lite"
        assert "Resolve these contract fields first" in build(client, path, expect=422)["detail"]
        _, path = accepted(client, monkeypatch, source_url="local:my-laptop", adapter_entrypoint="run:evaluate")
        blocked = build(client, path)
        assert blocked["status"] == "blocked" and {b["field"] for b in blocked["latest"]["blockers"]} == {"source_url", "adapter_entrypoint"}
        assert blocked["latest"]["model"] is None
        revise(client, monkeypatch, path)
        corrected = client.get(path + "/evaluator").json()
        assert corrected["status"] == "not_built" and corrected["latest"] is None
        _, path = accepted(client, monkeypatch)
        request = {"request_id": "one-build-request"}
        assert client.post(path + "/evaluator/build", json=request).status_code == 200
        assert client.post(path + "/evaluator/build", json=request).status_code == 200
        state = settle(client, path + "/evaluator", lambda s: s["status"] not in lite_build.ACTIVE)
        assert state["status"] == "ready" and state["builds"] == 1
        monkeypatch.delenv("OPENROUTER_API_KEY")
        assert not client.get(path + "/evaluator").json()["available"]
        assert build(client, path, expect=503)["detail"].startswith("OpenRouter is not configured")
        with TestClient(app) as other:
            assert other.get(path + "/evaluator").status_code == 404
            assert other.post(path + "/evaluator/build", json={"request_id": "another-request"}).status_code == 404


def test_freeze_reports_decisions_that_block_a_portable_evaluator(tmp_path):
    from autokaggle.store import Store
    store = Store(tmp_path / "store")
    project = store.create("o" * 40, "Example")
    project["lite"] = lite.initial()
    project["lite"]["contract"] = contract(answer_exposure="private", artifact_type="checkpoint", task_kind="environment", max_steps=5,
                                           adapter_entrypoint="gym_adapter:evaluate", env_id="Toy-v0", seed_method="reset", metric="rmse", failure_policy="fail_run")
    with pytest.raises(ValueError):
        lite_build.freeze(project, store.directory(project["id"]))
    lite.build(project, store.directory(project["id"]))
    spec, data, blockers = lite_build.freeze(project, store.directory(project["id"]))
    assert [b["field"] for b in blockers] == ["answer_exposure"]
    assert spec["direction"] == "minimize" and spec["loader"] == "loader:load" and spec["adapter"]["packaged"]
    assert spec["contract_sha256"] == json.loads(data)["contract_sha256"] and "gym_adapter" in spec["independent_forbidden"]


def test_release_file_rules_reject_unpinned_or_unsafe_declarations(tmp_path):
    assert acceptance.parse_requirements(b"# note\nnumpy==2.2.6\ngymnasium[classic-control]==1.2.0  # extra\n") == ["numpy==2.2.6", "gymnasium[classic-control]==1.2.0"]
    for bad in (b"numpy>=2", b"--index-url https://example.org/simple", b"git+https://github.com/x/y", b"./local", b"numpy==2.2.6 --hash=sha256:aa", b"-r other.txt"):
        with pytest.raises(ValueError):
            acceptance.parse_requirements(bad)
    good = {"path": "assets/labels.gz", "url": "https://example.org/labels.gz", "sha256": "a" * 64, "bytes": 10}
    assert acceptance.parse_assets(json.dumps([good]).encode()) == [good]
    for change in ({"url": "http://example.org/x"}, {"url": "file:///etc/passwd"}, {"path": "assets/../secret"}, {"path": "data/labels.gz"},
                   {"sha256": "abc"}, {"bytes": 0}, {"extra": 1}):
        with pytest.raises(ValueError):
            acceptance.parse_assets(json.dumps([{**good, **change}]).encode())
    assert "<dynamic import or execution>" in acceptance.imported_modules("import importlib\nimportlib.import_module('toy_adapter')")
    assert acceptance.imported_modules("import csv\nfrom toy_adapter import evaluate\nmodel.eval()") == {"csv", "toy_adapter"}
    (tmp_path / "fixtures").mkdir()
    (tmp_path / "fixtures" / "big.bin").write_bytes(b"0" * (acceptance.MAX_FILE + 1))
    (tmp_path / "link.py").symlink_to("/etc/hosts")
    (tmp_path / "check.py").write_text("x = 1")
    files, errors = acceptance.collect(tmp_path, {})
    assert files == {} and len(errors) == 2


def test_yaml_export_is_the_json_subset():
    yaml = pytest.importorskip("yaml")
    value = {"a": "text: with #symbols\nand lines", "b": [1, 2.5, True, None, "x"], "c": {}, "d": [], "e": [{"k": "v", "n": [1]}], "key with space": {"z": -1}}
    assert yaml.safe_load("\n".join(lite_build.to_yaml(value))) == value


def test_gateway_keeps_the_provider_key_and_bounds_the_job():
    seen = []

    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append((self.path, self.headers["Authorization"], body))
            data = json.dumps({"model": body["model"], "choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 3}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with Gateway("provider-secret", "lab/model", max_requests=2, upstream=f"http://127.0.0.1:{server.server_address[1]}/api/v1",
                     request_fields=lite_providers.reasoning("openrouter", "medium")) as gateway:
            url = f"http://127.0.0.1:{gateway.port}/v1/chat/completions"
            auth = {"Authorization": "Bearer " + gateway.token}
            assert httpx.post(url, json={"model": "lab/model"}, headers={"Authorization": "Bearer wrong"}).status_code == 401
            assert httpx.post(url, json={"model": "other/model"}, headers=auth).status_code == 403
            assert httpx.get(f"http://127.0.0.1:{gateway.port}/v1/models", headers=auth).status_code == 404
            first = httpx.post(url, json={"model": "lab/model", "reasoning_effort": "high", "messages": []}, headers=auth)
            assert first.status_code == 200 and "provider-secret" not in first.text
            assert httpx.post(url, json={"model": "lab/model"}, headers=auth).status_code == 200
            assert httpx.post(url, json={"model": "lab/model"}, headers=auth).status_code == 429
            assert gateway.usage == {"requests": 2, "rejected": 3, "input_tokens": 14, "output_tokens": 6, "models": ["lab/model"],
                                     "provider_errors": 0, "last_provider_status": 200}
        assert [(path, key) for path, key, _ in seen] == [("/api/v1/chat/completions", "Bearer provider-secret")] * 2
        assert seen[0][2]["reasoning"] == {"effort": "medium"} and "reasoning_effort" not in seen[0][2]
        with pytest.raises(httpx.HTTPError):
            httpx.post(url, json={"model": "lab/model"}, headers=auth, timeout=2)
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.skipif(os.getenv("AUTOKAGGLE_TEST_DOCKER") != "1", reason="Set AUTOKAGGLE_TEST_DOCKER=1 to run the container runtime test.")
def test_docker_runtime_builds_in_one_container_and_tests_in_another(tmp_path, monkeypatch):
    runtime = lite_build.DockerRuntime()
    assert runtime.available()[0], runtime.available()[1]
    monkeypatch.setenv("AUTOKAGGLE_PRIVATE_MODE", "0")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-provider-key")
    monkeypatch.setattr(lite_build, "default_runtime", lambda: runtime)
    monkeypatch.setattr(lite_build, "agent_command", lambda model: ["{python}", "-c", AGENT, "{work}", "ok"])
    app = create_app(tmp_path / "app")
    try:
        with TestClient(app) as client:
            _, path = accepted(client, monkeypatch)
            response = client.post(path + "/evaluator/build", json={"request_id": uuid.uuid4().hex})
            assert response.status_code == 200, response.text
            state = settle(client, path + "/evaluator", lambda s: s["status"] not in lite_build.ACTIVE, seconds=1800)
            assert state["status"] == "ready", state
            release = state["release"]
            assert release["runtime"]["kind"] == "docker" and release["runtime"]["image_id"].startswith("sha256:")
            assert release["evidence"]["platform"].startswith("Linux") and all(t["passed"] for t in release["tests"])
    finally:
        app.state.pool.shutdown(wait=True)


class FakeModel:
    """Stands in for the OpenAI client. Records each request and replays prepared replies."""
    calls = []
    replies = []

    def __init__(self, **options):
        self.options = options
        self.chat = self
        self.completions = self

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def create(self, **request):
        FakeModel.calls.append({**self.options, **request})
        content = FakeModel.replies.pop(0)
        usage = type("Usage", (), {"model_dump": lambda self: {"prompt_tokens": 1, "completion_tokens": 1}})()
        message = type("Message", (), {"content": content})()
        return type("Response", (), {"choices": [type("Choice", (), {"finish_reason": "stop", "message": message})()], "model": request["model"], "usage": usage})()


REPLY = json.dumps({"summary": "A five-row accuracy task.", "question": "", "question_field": "", "open_decisions": [], "resolved_decisions": [],
                    "updates": [{"field": "metric", "value_json": "\"accuracy\"", "basis": "suggestion", "evidence": "Proposed for review."}]})


def test_deepseek_interview_sends_the_same_context_and_passes_the_same_validation(monkeypatch):
    import openai
    monkeypatch.setattr(openai, "OpenAI", FakeModel)
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    state = lite.initial()
    state["messages"].append({"id": "m1", "role": "user", "content": "Measure label accuracy on five fixed rows."})
    FakeModel.calls, FakeModel.replies = [], [REPLY, "   ", REPLY]
    reference = lite.propose(state)
    proposal = lite_providers.propose_deepseek(lite, state)
    first, blank, second = FakeModel.calls
    assert first["base_url"] == "https://openrouter.ai/api/v1" and first["api_key"] == "openrouter-key"
    assert blank["base_url"] == second["base_url"] == "https://api.deepseek.com" and second["api_key"] == "deepseek-key"
    # Both providers receive the same interview context. Only the output instruction differs.
    assert json.loads(second["messages"][1]["content"]) == json.loads(first["messages"][1]["content"]) == json.loads(json.dumps(lite_providers.material(lite, state)))
    assert second["messages"][0]["content"].startswith(first["messages"][0]["content"]) and json.dumps(lite.model_schema()) in second["messages"][0]["content"]
    assert second["model"] == "deepseek-v4-pro" and second["response_format"] == {"type": "json_object"}
    assert second["extra_body"] == {"thinking": {"type": "enabled"}, "reasoning_effort": "high"}
    assert proposal["contract"] == reference["contract"] == {"metric": "accuracy"} and proposal["model"] == "deepseek-v4-pro"
    FakeModel.replies = ["", ""]
    with pytest.raises(ValueError, match="invalid contract"):
        lite_providers.propose_deepseek(lite, state)


def test_provider_selection_keeps_openrouter_as_the_unchanged_default(harness, monkeypatch):
    app, mode, _ = harness
    seen = []
    assert getattr(lite.propose, "_lite_provider_router", False)
    monkeypatch.setattr(lite_providers, "propose_deepseek", lambda module, state: seen.append("deepseek") or "deepseek proposal")
    import openai
    monkeypatch.setattr(openai, "OpenAI", FakeModel)
    FakeModel.calls, FakeModel.replies = [], [REPLY]
    state = lite.initial()
    assert lite.propose(state)["contract"] == {"metric": "accuracy"} and FakeModel.calls[0]["base_url"] == "https://openrouter.ai/api/v1" and not seen
    assert lite_build.settings()["provider"] == "openrouter" and lite_build.settings()["model"] == "openai/gpt-6.1-sol"
    assert lite_providers.reasoning("openrouter", "medium") == {"reasoning": {"effort": "medium"}}
    assert lite_providers.agent_model("openrouter", "openai/gpt-6.1-sol", "medium") == {"name": "openai/gpt-6.1-sol"}

    monkeypatch.setenv("AUTOKAGGLE_LITE_PROVIDER", "deepseek")
    assert lite.propose(state) == "deepseek proposal" and seen == ["deepseek"]
    chosen = lite_build.settings()
    assert chosen["provider"] == "deepseek" and chosen["model"] == "deepseek-v4-pro"
    assert lite_providers.reasoning("deepseek", "none") == {"thinking": {"type": "disabled"}}
    assert lite_providers.agent_model("deepseek", "deepseek-v4-pro", "medium")["interleaved"] == {"field": "reasoning_content"}
    assert "interleaved" not in lite_providers.agent_model("deepseek", "deepseek-v4-pro", "none")
    with TestClient(app) as client:
        _, path = accepted_with_stub(client, monkeypatch)
        view = client.get(path + "/evaluator").json()
        assert not view["available"] and view["unavailable_reason"].startswith("DeepSeek is not configured. Add DEEPSEEK_API_KEY")
        assert build(client, path, expect=503)["detail"].startswith("DeepSeek is not configured")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
        state = build(client, path)
        assert state["status"] == "ready" and state["release"]["model"]["provider"] == "DeepSeek" and state["settings"]["provider"] == "DeepSeek"
    monkeypatch.setenv("AUTOKAGGLE_LITE_PROVIDER", "another")
    with pytest.raises(ValueError):
        lite_providers.selected()


def accepted_with_stub(client, monkeypatch):
    """Accept the test contract while a provider is selected. The stub replaces the whole routed interview call."""
    created = client.post("/api/lite/projects", json={"organizer_email": "lab@example.org", "storage_accepted": True}).json()
    path = f"/api/projects/{created['id']}/lite"
    revise(client, monkeypatch, path)
    return created["id"], path


def test_gateway_applies_deepseek_reasoning_and_requests_stream_usage():
    seen = []

    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            seen.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            data = b'data: {"model":"deepseek-v4-pro","choices":[]}\n\ndata: {"choices":[],"usage":{"prompt_tokens":5,"completion_tokens":2}}\n\ndata: [DONE]\n\n'
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with Gateway("deepseek-key", "deepseek-v4-pro", upstream=f"http://127.0.0.1:{server.server_address[1]}",
                     request_fields=lite_providers.reasoning("deepseek", "medium")) as gateway:
            reply = httpx.post(f"http://127.0.0.1:{gateway.port}/v1/chat/completions", headers={"Authorization": "Bearer " + gateway.token},
                               json={"model": "deepseek-v4-pro", "stream": True, "thinking": {"type": "disabled"}, "reasoning": {"effort": "low"}, "messages": []})
            assert reply.status_code == 200 and "[DONE]" in reply.text
            assert gateway.usage["input_tokens"] == 5 and gateway.usage["output_tokens"] == 2
        path, body = seen[0]
        assert path == "/chat/completions" and body["thinking"] == {"type": "enabled"} and body["reasoning_effort"] == "high"
        assert "reasoning" not in body and body["stream_options"] == {"include_usage": True}
    finally:
        server.shutdown()
        server.server_close()


def fake_hub(kind, root, login="lab-bot"):
    """GitHub stand-in. Each repository is a bare Git directory, so the real push and ref checks of either client run against it."""
    base = lite_publish.GitHub if kind == "command" else lite_publish.TokenGitHub

    class Fake(base):
        def __init__(self):
            self.root, self.login, self.repos, self.created = Path(root), login, {}, []
            self.root.mkdir(parents=True, exist_ok=True)
            self.command, self._token = "gh", "unused-token"

        def environment(self):
            return {"PATH": os.environ["PATH"]}

        def available(self):
            return True, ""

        def account(self):
            return self.login

        def repository(self, reference):
            kind, _, rest = reference.partition("/")
            for repo in self.repos.values():
                if (kind == "repositories" and str(repo["id"]) == rest) or (kind == "repos" and repo["full_name"].lower() == rest.lower()):
                    return dict(repo)
            return None

        def create(self, account, name, description):
            repo = {"id": 1000 + len(self.created), "full_name": f"{account}/{name}", "owner": account, "name": name,
                    "url": f"https://github.com/{account}/{name}", "private": True, "description": description}
            subprocess.run(["git", "init", "-q", "--bare", str(self.root / f"{repo['id']}.git")], check=True)
            self.repos[repo["id"]] = repo
            self.created.append(repo["full_name"])
            return dict(repo)

        def git_url(self, repository):
            return str(self.root / f"{repository['id']}.git")

        def git_options(self):
            return []

        def refs(self, identifier):
            done = subprocess.run(["git", "for-each-ref", "--format=%(refname) %(objectname)"], cwd=self.root / f"{identifier}.git", capture_output=True, text=True, check=True)
            return dict(line.split() for line in done.stdout.splitlines())

    return Fake()


@pytest.fixture(params=["command", "token"])
def published(request, harness, monkeypatch, tmp_path):
    if request.param == "token":
        pytest.importorskip("dulwich")
    hub = fake_hub(request.param, tmp_path / "github")
    monkeypatch.setenv("AUTOKAGGLE_LITE_GITHUB_OWNER", "bold-test")
    monkeypatch.setattr(lite_publish, "default_client", lambda: hub)
    app = create_app(tmp_path / "publishing-app")
    yield app, hub
    app.state.pool.shutdown(wait=True)


def test_publishing_creates_one_private_repository_and_pushes_the_tested_commit(published, monkeypatch, tmp_path):
    app, hub = published
    with TestClient(app) as client:
        identifier, path = accepted(client, monkeypatch)
        assert client.post(path + "/evaluator/publish").status_code == 409  # No tested release yet.
        state = build(client, path)
        assert state["publishing"] == {"automatic": False, "available": True, "reason": "", "owner": "bold-test", "repository": None}
        commit = state["release"]["evidence"]["commit"]
        assert state["release"]["published"] is None and hub.created == []

        done = client.post(path + "/evaluator/publish")
        assert done.status_code == 200, done.text
        record = done.json()["release"]["published"]
        name = "lite-eval-toy-label-accuracy-" + identifier.replace("-", "")[:8]
        assert hub.created == ["bold-test/" + name]
        assert record["url"] == "https://github.com/bold-test/" + name and record["commit"] == commit and record["tag"] == "v1"
        assert record["by"] == "lab-bot" and record["refs_pushed"] == 2 and record["address_recorded"] is True
        assert done.json()["publishing"]["repository"] == {"url": record["url"], "name": "bold-test/" + name}
        assert hub.repos[1000]["private"] and identifier in hub.repos[1000]["description"]
        assert hub.refs(1000) == {"refs/heads/main": commit, "refs/tags/v1": commit}

        # A collaborator clones the published repository. It is the tested commit and it names its own address.
        clone = tmp_path / "from-github"
        subprocess.run(["git", "clone", "-q", hub.git_url(hub.repos[1000]), str(clone)], check=True)
        subprocess.run(["git", "checkout", "-q", "v1"], cwd=clone, check=True, capture_output=True)
        assert json.loads((clone / "evaluator.lock.json").read_text())["repository"] == record["url"]
        assert f"git clone {record['url']}.git evaluator" in (clone / "README.md").read_text()
        scored = subprocess.run([sys.executable, "evaluate.py", "--artifact", "fixtures/valid/predictions.csv"], cwd=clone, capture_output=True, text=True)
        answer = json.loads(scored.stdout.strip().splitlines()[-1])
        assert scored.returncode == 0 and answer["fitness"] == 1.0 and answer["evaluator_revision"] == commit
        assert json.loads((clone / "results.json").read_text())["manifest"]["code_repository"] == record["url"]

        # A retry reuses the same repository and pushes nothing.
        again = client.post(path + "/evaluator/publish").json()["release"]["published"]
        assert hub.created == ["bold-test/" + name] and again["refs_pushed"] == 0 and again["commit"] == commit

        # A new contract version becomes a new release in the same repository, even after the title changed.
        revise(client, monkeypatch, path, title="Renamed toy problem", evaluation_count=4)
        second = build(client, path)
        assert second["release"]["evaluator_version"] == 2 and second["release"]["published"] is None
        reply = client.post(path + "/evaluator/publish")
        assert reply.status_code == 200, reply.text
        later = reply.json()["release"]["published"]
        newer = second["release"]["evidence"]["commit"]
        assert hub.created == ["bold-test/" + name] and later["address_recorded"] is True
        assert hub.refs(1000) == {"refs/heads/main": newer, "refs/tags/v1": commit, "refs/tags/v2": newer}


def test_publishing_never_overwrites_or_exposes_a_repository(published, monkeypatch, tmp_path):
    app, hub = published
    with TestClient(app) as client:
        identifier, path = accepted(client, monkeypatch)
        name = "lite-eval-toy-label-accuracy-" + identifier.replace("-", "")[:8]
        build(client, path)
        # A repository of that name which was not created for this problem is left alone.
        foreign = hub.create("bold-test", name, "Someone else's work")
        refused = client.post(path + "/evaluator/publish")
        assert refused.status_code == 502 and "was not created for this problem" in refused.json()["detail"]
        assert hub.refs(foreign["id"]) == {}
        # A repository left by an interrupted first attempt is adopted through its description.
        hub.repos[foreign["id"]]["description"] = lite_publish.MARKER + identifier
        hub.repos[foreign["id"]]["private"] = False
        public = client.post(path + "/evaluator/publish")
        assert public.status_code == 502 and "is not private" in public.json()["detail"] and hub.refs(foreign["id"]) == {}
        hub.repos[foreign["id"]]["private"] = True
        first = client.post(path + "/evaluator/publish")
        assert first.status_code == 200 and len(hub.created) == 1, first.text
        commit = first.json()["release"]["published"]["commit"]

        # Commits made outside the application are not overwritten.
        other = tmp_path / "outside"
        subprocess.run(["git", "clone", "-q", hub.git_url(foreign), str(other)], check=True)
        (other / "extra.txt").write_text("edited by hand\n")
        git = ["git", "-c", "user.name=someone", "-c", "user.email=someone@example.org"]
        subprocess.run([*git, "add", "."], cwd=other, check=True)
        subprocess.run([*git, "commit", "-q", "-m", "manual edit"], cwd=other, check=True)
        subprocess.run([*git, "push", "-q", "origin", "HEAD:main"], cwd=other, check=True, capture_output=True)
        manual = hub.refs(foreign["id"])["refs/heads/main"]
        revise(client, monkeypatch, path, evaluation_count=4)
        build(client, path)
        diverged = client.post(path + "/evaluator/publish")
        assert diverged.status_code == 502 and "Nothing was overwritten" in diverged.json()["detail"], diverged.text
        assert hub.refs(foreign["id"]) == {"refs/heads/main": manual, "refs/tags/v1": commit}

        # A removed repository is not replaced silently.
        del hub.repos[foreign["id"]]
        gone = client.post(path + "/evaluator/publish")
        assert gone.status_code == 502 and "no longer exists" in gone.json()["detail"] and len(hub.created) == 1
        fresh = client.post(path + "/evaluator/publish", json={"new_repository": True})
        assert fresh.status_code == 200 and len(hub.created) == 2, fresh.text
        assert fresh.json()["release"]["published"]["repository_id"] == 1001
        assert set(hub.refs(1001)) == {"refs/heads/main", "refs/tags/v1", "refs/tags/v2"}


def test_publishing_is_off_without_an_owner_and_flags_releases_built_before_it(harness, monkeypatch, tmp_path):
    app, mode, _ = harness
    hub = fake_hub("command", tmp_path / "github")
    monkeypatch.setattr(lite_publish, "default_client", lambda: hub)
    app = create_app(tmp_path / "second-app")
    try:
        with TestClient(app) as client:
            identifier, path = accepted(client, monkeypatch)
            state = build(client, path)
            assert state["publishing"]["available"] is False and state["publishing"]["owner"] is None
            off = client.post(path + "/evaluator/publish")
            assert off.status_code == 503 and "not configured" in off.json()["detail"] and hub.created == []
            monkeypatch.setenv("AUTOKAGGLE_LITE_GITHUB_OWNER", "not a name")
            assert "one GitHub account" in client.get(path + "/evaluator").json()["publishing"]["reason"]
            # The release was built before an owner was set. It is published unchanged and the gap is stated.
            monkeypatch.setenv("AUTOKAGGLE_LITE_GITHUB_OWNER", "bold-test")
            record = client.post(path + "/evaluator/publish").json()["release"]["published"]
            assert record["commit"] == state["release"]["evidence"]["commit"]
            assert record["address_recorded"] is False and record["lock_repository"] == lite_publish.LOCAL
    finally:
        app.state.pool.shutdown(wait=True)


def test_github_client_uses_the_gh_command_and_bounds_its_errors(tmp_path, monkeypatch):
    calls = tmp_path / "calls.jsonl"
    stub = tmp_path / "gh"
    stub.write_text(f"""#!{sys.executable}
import json, sys
args = sys.argv[1:]
body = sys.stdin.read() if "--input" in args else ""
open({str(calls)!r}, "a").write(json.dumps({{"args": args, "body": body}}) + "\\n")
path = args[args.index("-X") + 2]
repo = {{"id": 7, "full_name": "bold-test/x", "name": "x", "owner": {{"login": "bold-test"}}, "html_url": "https://github.com/bold-test/x", "private": True, "description": None}}
if path == "user": print(json.dumps({{"login": "lab-bot"}}))
elif path == "users/bold-test": print(json.dumps({{"type": "Organization"}}))
elif path == "users/lab-bot": print(json.dumps({{"type": "User"}}))
elif path == "users/stranger": print(json.dumps({{"type": "User"}}))
elif path in ("orgs/bold-test/repos", "user/repos", "repos/bold-test/x"): print(json.dumps(repo))
elif path == "repos/bold-test/missing": print('{{"message": "Not Found"}}'); sys.stderr.write("gh: Not Found (HTTP 404)\\n"); sys.exit(1)
else: sys.stderr.write("gh: Bad credentials (HTTP 401)\\n"); sys.exit(1)
""")
    stub.chmod(0o755)
    monkeypatch.setenv("GH_TOKEN", "server-secret")
    monkeypatch.setenv("OPENROUTER_API_KEY", "provider-secret")
    hub = lite_publish.GitHub(str(stub))
    assert hub.available() == (True, "") and hub.account() == "lab-bot"
    assert "OPENROUTER_API_KEY" not in hub.environment() and hub.environment()["GH_TOKEN"] == "server-secret"
    assert hub.repository("repos/bold-test/missing") is None
    assert hub.repository("repos/bold-test/x") == {"id": 7, "full_name": "bold-test/x", "owner": "bold-test", "name": "x",
                                                   "url": "https://github.com/bold-test/x", "private": True, "description": ""}
    assert hub.create("bold-test", "x", "d")["id"] == 7 and hub.create("lab-bot", "x", "d")["id"] == 7
    sent = [json.loads(line) for line in calls.read_text().splitlines()]
    created = [c for c in sent if "POST" in c["args"]]
    assert [c["args"][c["args"].index("POST") + 1] for c in created] == ["orgs/bold-test/repos", "user/repos"]
    assert all(json.loads(c["body"])["private"] is True and json.loads(c["body"])["auto_init"] is False for c in created)
    assert "server-secret" not in calls.read_text()
    with pytest.raises(lite_publish.PublishError, match="another person's account"):
        hub.create("stranger", "x", "d")
    with pytest.raises(lite_publish.PublishError, match="Bad credentials") as failure:
        hub.repository("repositories/9")
    assert "server-secret" not in str(failure.value)
    assert hub.git_url({"full_name": "bold-test/x"}) == "https://github.com/bold-test/x.git"
    assert lite_publish.GitHub(str(tmp_path / "absent")).available()[0] is False


def test_repository_names_are_stable_and_distinct_per_problem(monkeypatch):
    name = lite_publish.repository_name("25BC2D7D-2f5d-4232-a0ef-be0b696a651f", "  Fashion-MNIST: test accuracy!  ")
    assert name == "lite-eval-fashion-mnist-test-accuracy-25bc2d7d"
    assert lite_publish.repository_name("abcdef12-0000", "???") == "lite-eval-problem-abcdef12"
    assert len(lite_publish.repository_name("abcdef12-0000", "x" * 300)) <= 100
    assert lite_publish.repository_name("11111111-a", "Pendulum") != lite_publish.repository_name("22222222-a", "Pendulum")
    monkeypatch.delenv("AUTOKAGGLE_LITE_GITHUB_OWNER", raising=False)
    assert lite_publish.planned_address({"repository_name": "n"}) is None
    monkeypatch.setenv("AUTOKAGGLE_LITE_GITHUB_OWNER", "bold-test")
    assert lite_publish.planned_address({"repository_name": "n"}) == "https://github.com/bold-test/n"
    assert lite_publish.planned_address({"repository_name": "n", "github": {"url": "https://github.com/bold-test/moved"}}) == "https://github.com/bold-test/moved"


def test_token_client_reaches_github_over_https_without_any_command(monkeypatch):
    seen = []
    repo = {"id": 7, "full_name": "bold-test/x", "name": "x", "owner": {"login": "bold-test"}, "html_url": "https://github.com/bold-test/x", "private": True, "description": None}

    def handler(request):
        seen.append(request)
        path = request.url.path
        if path == "/user":
            return httpx.Response(200, json={"login": "lab-bot"})
        if path == "/users/bold-test":
            return httpx.Response(200, json={"type": "Organization"})
        if path in ("/orgs/bold-test/repos", "/repos/bold-test/x"):
            return httpx.Response(201 if request.method == "POST" else 200, json=repo)
        if path == "/repos/bold-test/missing":
            return httpx.Response(404, json={"message": "Not Found"})
        return httpx.Response(403, json={"message": "Resource not accessible by personal access token"})

    hub = lite_publish.TokenGitHub("server-token", transport=httpx.MockTransport(handler))
    monkeypatch.setattr(lite_publish.subprocess, "run", lambda *a, **k: pytest.fail("The token client must not start a command."))
    assert hub.account() == "lab-bot"
    assert hub.repository("repos/bold-test/missing") is None
    assert hub.repository("repos/bold-test/x")["url"] == "https://github.com/bold-test/x"
    assert hub.create("bold-test", "x", "d")["id"] == 7
    created = next(r for r in seen if r.method == "POST")
    assert created.url == "https://api.github.com/orgs/bold-test/repos"
    assert json.loads(created.content) == {"name": "x", "private": True, "description": "d", "auto_init": False, "has_wiki": False, "has_projects": False}
    assert all(r.headers["Authorization"] == "Bearer server-token" and r.url.host == "api.github.com" for r in seen)
    # A token that still awaits organization approval is refused with GitHub's own reason and no token text.
    with pytest.raises(lite_publish.PublishError, match=r"Resource not accessible by personal access token \(HTTP 403\)") as failure:
        hub.repository("repositories/9")
    assert "server-token" not in str(failure.value)
    assert hub.git_url({"full_name": "bold-test/x"}) == "https://github.com/bold-test/x.git"
    if hub.available()[0]:  # The Git library is installed.
        client, path = hub._remote({"full_name": "bold-test/x"})
        assert "Http" in type(client).__name__ and path == b"/bold-test/x.git"
    else:
        assert "dulwich" in hub.available()[1]
    broken = lite_publish.TokenGitHub("server-token", transport=httpx.MockTransport(lambda request: httpx.Response(401, json={"message": "Bad credentials"})))
    assert broken.available() == (False, "The GitHub token on this server is not usable. It may have expired or may still await approval.") or "dulwich" in broken.available()[1]


def test_a_server_token_selects_the_token_client(monkeypatch):
    monkeypatch.delenv("AUTOKAGGLE_LITE_GITHUB_TOKEN", raising=False)
    assert type(lite_publish.default_client()) is lite_publish.GitHub
    monkeypatch.setenv("AUTOKAGGLE_LITE_GITHUB_TOKEN", " server-token ")
    client = lite_publish.default_client()
    assert type(client) is lite_publish.TokenGitHub and client._token == "server-token"
    assert "AUTOKAGGLE_LITE_GITHUB_TOKEN" not in lite_publish.GitHub().environment()


def test_container_runtime_can_be_described_for_a_user_with_no_account_entry(monkeypatch):
    import getpass, pwd
    monkeypatch.setattr(pwd, "getpwuid", lambda uid: (_ for _ in ()).throw(KeyError(uid)))
    monkeypatch.setattr(getpass, "getuser", lambda: (_ for _ in ()).throw(KeyError("no account")))
    runtime = lite_build.DockerRuntime()
    assert runtime.user == f"uid{os.getuid()}" and runtime.tag.startswith(runtime.user + "_autokaggle-lite-build:")


def publication_settled(client, path):
    return settle(client, path + '/evaluator', lambda s: s['status'] not in lite_build.ACTIVE and
                  (s.get('release', {}).get('publication') or {}).get('status') not in {'queued', 'publishing'})


def test_automatic_publication_versions_one_repository(published, monkeypatch):
    app, hub = published
    monkeypatch.setenv('AUTOKAGGLE_LITE_AUTO_PUBLISH', '1')
    with TestClient(app) as client:
        identifier, path = accepted(client, monkeypatch)
        build(client, path)
        first = publication_settled(client, path)
        release = first['release']
        assert first['publishing']['automatic']
        assert release['publication']['status'] == 'published'
        assert release['published']['commit'] == release['evidence']['commit']
        assert release['published']['zip_url'].endswith('/archive/' + release['evidence']['commit'] + '.zip')
        assert len(hub.created) == 1
        revise(client, monkeypatch, path, evaluation_count=4)
        build(client, path)
        second = publication_settled(client, path)['release']
        assert len(hub.created) == 1 and second['published']['tag'] == 'v2'
        assert hub.refs(1000) == {'refs/heads/main': second['evidence']['commit'],
                                  'refs/tags/v1': release['evidence']['commit'], 'refs/tags/v2': second['evidence']['commit']}


def test_failed_automatic_push_keeps_tested_release_and_reuses_repository(published, monkeypatch):
    app, hub = published
    monkeypatch.setenv('AUTOKAGGLE_LITE_AUTO_PUBLISH', '1')
    original = hub.push
    def fail(*args):
        raise RuntimeError('credential-that-must-not-appear')
    monkeypatch.setattr(hub, 'push', fail)
    with TestClient(app) as client:
        identifier, path = accepted(client, monkeypatch)
        build(client, path)
        state = publication_settled(client, path)
        assert state['status'] == 'ready' and len(hub.created) == 1
        release = state['release']
        assert release['publication']['status'] == 'failed' and release['published'] is None
        assert 'credential-that-must-not-appear' not in json.dumps(state)
        assert client.get(path + '/evaluator/bundle').status_code == 200
        monkeypatch.setattr(hub, 'push', original)
        retry = client.post(path + '/evaluator/publish')
        assert retry.status_code == 200, retry.text
        saved = retry.json()['release']
        assert saved['publication']['status'] == 'published' and saved['publication']['attempts'] == 2
        assert saved['evidence']['commit'] == release['evidence']['commit'] and len(hub.created) == 1


def test_failed_build_never_auto_publishes(published, monkeypatch):
    app, hub = published
    monkeypatch.setenv('AUTOKAGGLE_LITE_AUTO_PUBLISH', '1')
    monkeypatch.setattr(lite_build, 'agent_command', lambda model: ['{python}', '-c', 'raise SystemExit(3)'])
    with TestClient(app) as client:
        _, path = accepted(client, monkeypatch)
        state = build(client, path)
        assert state['status'] == 'failed' and not hub.created


def test_auto_publisher_skips_a_changed_contract(published, monkeypatch):
    app, hub = published
    with TestClient(app) as client:
        identifier, path = accepted(client, monkeypatch)
        release = build(client, path)['release']
        revise(client, monkeypatch, path, evaluation_count=4)
        monkeypatch.setenv('AUTOKAGGLE_LITE_AUTO_PUBLISH', '1')
        monkeypatch.setattr(lite_build, '_work', lambda *args: None)
        lite_build.work(app.state.store, identifier, release['id'], lite_build.LocalRuntime(), {}, 'unused', github=hub)
        state = client.get(path + '/evaluator').json()
        assert state['status'] == 'stale' and state['release'] is None and not hub.created


def test_publication_locks_contract_and_duplicate_builds(published, monkeypatch):
    app, hub = published
    monkeypatch.setenv('AUTOKAGGLE_LITE_AUTO_PUBLISH', '1')
    entered, proceed = threading.Event(), threading.Event()
    original = hub.create
    def slow(*args):
        entered.set()
        assert proceed.wait(20)
        return original(*args)
    monkeypatch.setattr(hub, 'create', slow)
    with TestClient(app) as client:
        _, path = accepted(client, monkeypatch)
        client.post(path + '/evaluator/build', json={'request_id': uuid.uuid4().hex})
        assert entered.wait(120)
        try:
            state = client.get(path + '/evaluator').json()
            assert state['release']['publication']['status'] == 'publishing'
            assert client.post(path + '/evaluator/publish').status_code == 409
            assert client.post(path + '/evaluator/build', json={'request_id': uuid.uuid4().hex}).status_code == 409
            assert client.post(path + '/message', json={'request_id': uuid.uuid4().hex, 'message': 'Change the task.'}).status_code == 409
        finally:
            proceed.set()
        assert publication_settled(client, path)['release']['publication']['status'] == 'published'
        assert len(hub.created) == 1


def test_interrupted_publication_has_retry_state():
    build = {'id': 'interrupted', 'status': 'ready', 'publication': {'status': 'publishing', 'project_id': 'p1', 'attempts': 1}}
    public = lite_build._public(build)
    assert public['status'] == 'ready' and public['publication']['status'] == 'failed'
    assert 'Retry publication' in public['publication']['error']
    assert build['publication']['status'] == 'publishing'  # A read must not mutate storage.


def test_publisher_rejects_main_that_differs_from_tested_release():
    class Refs:
        def local_refs(self, repo):
            return {'refs/heads/main': 'b' * 40, 'refs/tags/v1': 'a' * 40}
    with pytest.raises(lite_publish.PublishError, match='does not match its tested commit'):
        lite_publish.push_release(None, {}, 'a' * 40, 1, Refs())


def test_rollout_cannot_enable_lite_auto_publish_on_full():
    from autokaggle.deploy.rollout import update
    with pytest.raises(ValueError, match='only be changed on the Lite service'):
        update(None, 'web', b'', '', {}, auto_publish=True)


def test_downloaded_git_archive_scores_without_git_metadata(harness, monkeypatch, tmp_path):
    import io, zipfile
    app, _, _ = harness
    with TestClient(app) as client:
        identifier, path = accepted(client, monkeypatch)
        release = build(client, path)['release']
        commit = release['evidence']['commit']
        repo = app.state.store.directory(identifier) / 'lite-evaluator/repo.git'
        zipped = subprocess.run(['git', '--git-dir', str(repo), 'archive', '--format=zip', commit], capture_output=True, check=True).stdout
        unpacked = tmp_path / 'download'
        with zipfile.ZipFile(io.BytesIO(zipped)) as archive:
            archive.extractall(unpacked)
        assert (unpacked / 'revision.txt').read_text().strip() == commit
        # Put the archive inside an unrelated checkout. It must not record the parent's revision.
        subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
        result = subprocess.run([sys.executable, 'evaluate.py', '--artifact', 'fixtures/valid/predictions.csv'], cwd=unpacked, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        summary = json.loads(result.stdout.strip().splitlines()[-1])
        assert summary['fitness'] == 1 and summary['evaluator_revision'] == commit
        (unpacked / 'toy_adapter.py').write_text('raise RuntimeError("changed")')
        rejected = subprocess.run([sys.executable, 'evaluate.py', '--artifact', 'fixtures/valid/predictions.csv'], cwd=unpacked, capture_output=True, text=True)
        assert rejected.returncode == 1 and 'differs from the release' in rejected.stderr


@pytest.mark.parametrize('phase', ['build', 'publication'])
def test_poll_rechecks_completion_before_reporting_interruption(harness, monkeypatch, phase):
    """The saved row can be older than the in-memory worker registry."""
    import copy
    app, _, _ = harness
    with TestClient(app) as client:
        identifier, path = accepted(client, monkeypatch)
        initial = build(client, path)
        assert initial['status'] == 'ready', initial
        store = app.state.store
        completed = lite_build._reload(store, identifier)
        build_id = completed['lite_evaluator']['builds'][-1]['id']
        old = copy.deepcopy(completed)
        record = old['lite_evaluator']['builds'][-1]
        if phase == 'build':
            record.update(status='testing', stage='Scoring the examples from a fresh clone')
            lite_build._RUNNING.add(build_id)
        else:
            record['publication'] = {'status': 'publishing', 'project_id': identifier}
            completed['lite_evaluator']['builds'][-1]['publication'] = {'status': 'published', 'project_id': identifier}
            lite_build._PUBLISHING.add(identifier)
        store.save(old)
        original = lite_build.view
        first = True

        def finish_between_read_and_view(project, *args, **kwargs):
            nonlocal first
            if first:
                first = False
                with store.lock(identifier):
                    store.save(completed)
                    lite_build._RUNNING.discard(build_id)
                    lite_build._PUBLISHING.discard(identifier)
            return original(project, *args, **kwargs)

        monkeypatch.setattr(lite_build, 'view', finish_between_read_and_view)
        try:
            response = client.get(path + '/evaluator')
            assert response.status_code == 200
            result = response.json()
            assert result['status'] == 'ready' and result['release'], result
            assert not result['release'].get('interrupted')
            if phase == 'publication':
                assert result['release']['publication']['status'] == 'published'
        finally:
            lite_build._RUNNING.discard(build_id)
            lite_build._PUBLISHING.discard(identifier)
