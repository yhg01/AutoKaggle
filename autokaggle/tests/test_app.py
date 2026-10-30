from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import time
import zipfile

from fastapi.testclient import TestClient
import pandas as pd
import pytest

from autokaggle.app import create_app
from autokaggle.advisor import apply_supported_updates, model_context
from autokaggle.core import datasets


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOKAGGLE_MODE", "rules")
    obj = create_app(tmp_path / "data")
    yield obj
    obj.state.pool.shutdown(wait=True)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


def create_example(client, name="materials"):
    response = client.post("/api/projects", json={})
    assert response.status_code == 200
    item = response.json()
    response = client.post(f"/api/projects/{item['id']}/example", json={"name": name})
    assert response.status_code == 200, response.text
    return response.json()


def ready(client):
    item = create_example(client)
    response = client.post(f"/api/projects/{item['id']}/analyze")
    assert response.status_code == 200, response.text
    item = response.json()
    assert not item["analysis"]["summary"]["blockers"], item["analysis"]
    assert item["analysis"]["baseline"]["status"] == "complete"
    response = client.post(f"/api/projects/{item['id']}/prepare", json={"acknowledge_review": True})
    assert response.status_code == 200, response.text
    return response.json()


def test_complete_packages_and_participant_boundary(client, app, tmp_path):
    item = ready(client)
    root = f"/api/projects/{item['id']}"
    assert item["prepared"]["train_rows"] == 480
    assert item["prepared"]["test_rows"] == 120
    assert not any(k.startswith("_") for k in item)
    public_bytes = client.get(root + "/download/researcher").content
    private_bytes = client.get(root + "/download/organizer").content
    public_zip = zipfile.ZipFile(io.BytesIO(public_bytes))
    private_zip = zipfile.ZipFile(io.BytesIO(private_bytes))
    assert "test.csv" not in public_zip.namelist()
    assert "evaluate.py" not in public_zip.namelist()
    assert "test.csv" in private_zip.namelist()
    assert "prepare.py" in public_zip.namelist()
    train = pd.read_csv(public_zip.open("train.csv"))
    test = pd.read_csv(private_zip.open("test.csv"))
    assert len(train) == 480 and len(test) == 120
    assert "sample_id" not in train
    assert not set(map(tuple, train.to_numpy())) & set(map(tuple, test.to_numpy()))
    link = client.get(root + "/participant-link").json()["url"]
    token = link.rsplit("/", 1)[1]
    with TestClient(app) as anonymous:
        assert anonymous.get(root).status_code == 404
        assert anonymous.get(root + "/download/organizer").status_code == 404
        assert anonymous.get(root + "/participant-link").status_code == 404
        view = anonymous.get(f"/api/challenges/{token}").json()
        assert set(view) == {"title", "brief", "metric", "train_rows", "download_url", "limitations"}
        assert anonymous.get(view["download_url"]).content == public_bytes
        assert anonymous.get(f"/api/challenges/{token}/download/organizer").status_code == 404
        assert anonymous.get("/data/" + item["id"] + "/dataset.csv").status_code == 404
    private_zip.extractall(tmp_path / "private")
    public_zip.extractall(tmp_path / "public")
    subprocess.run([sys.executable, str(tmp_path / "public/prepare.py"), "--output-dir", str(tmp_path / "workspace")], check=True, capture_output=True)
    assert (tmp_path / "workspace/train.csv").read_bytes() == public_zip.read("train.csv")
    subprocess.run([sys.executable, str(tmp_path / "private/evaluate_prepare.py"), "--inference-dir", str(tmp_path / "inputs"), "--truth-dir", str(tmp_path / "truth")], check=True, capture_output=True)
    assert "stable" not in pd.read_csv(tmp_path / "inputs/test_features.csv")
    truth = pd.read_csv(tmp_path / "truth/truth.csv")
    predictions = truth.rename(columns={"truth": "prediction"}).sample(frac=1, random_state=2)
    predictions.to_csv(tmp_path / "predictions.csv", index=False)
    run = subprocess.run([sys.executable, str(tmp_path / "private/evaluate.py"), "--truth", str(tmp_path / "truth/truth.csv"), "--predictions", str(tmp_path / "predictions.csv"), "--metric", "balanced_accuracy"], check=True, capture_output=True, text=True)
    assert json.loads(run.stdout)["score"] == 1.0
    # Duplicate IDs must fail, even if a perfect answer is supplied.
    predictions.iloc[0, 0] = predictions.iloc[1, 0]
    predictions.to_csv(tmp_path / "predictions.csv", index=False)
    bad = subprocess.run([sys.executable, str(tmp_path / "private/evaluate.py"), "--truth", str(tmp_path / "truth/truth.csv"), "--predictions", str(tmp_path / "predictions.csv"), "--metric", "balanced_accuracy"], capture_output=True)
    assert bad.returncode != 0


def test_leakage_blocker_and_repair(client):
    item = create_example(client, "leakage")
    root = f"/api/projects/{item['id']}"
    audit = client.post(root + "/analyze").json()
    assert audit["analysis"]["summary"]["blockers"] > 0
    assert client.post(root + "/prepare", json={"acknowledge_review": True}).status_code == 422
    client.patch(root, json={"design": {"exclude_columns": ["sample_id", "post_test_result"]}})
    audit = client.post(root + "/analyze").json()
    assert audit["analysis"]["summary"]["blockers"] == 0
    assert client.post(root + "/prepare", json={"acknowledge_review": True}).status_code == 200


def test_advice_keeps_the_reviewed_revision_after_an_edit(client):
    item = create_example(client)
    root = f"/api/projects/{item['id']}"
    advised = client.post(root + "/advise", json={"kind": "conversation"}).json()
    note = advised["advice"][-1]
    assert note["revision"] == advised["revision"]
    edited = client.patch(root, json={"title": "Revised scientific task"}).json()
    assert edited["revision"] > note["revision"]
    assert edited["advice"][-1]["revision"] == note["revision"]


def test_public_label_declaration_blocks(client):
    item = create_example(client)
    root = f"/api/projects/{item['id']}"
    client.patch(root, json={"answers": {"labels_public": "yes", "data_origin": "public"}})
    audit = client.post(root + "/analyze").json()
    finding = next(c for c in audit["analysis"]["checks"] if c["id"] == "public_labels")
    assert finding["severity"] == "blocker"
    assert client.post(root + "/prepare", json={"acknowledge_review": True}).status_code == 422


def test_edit_revokes_old_participant_link_and_downloads(client):
    item = ready(client)
    root = f"/api/projects/{item['id']}"
    link = client.get(root + "/participant-link").json()["url"]
    token = link.rsplit("/", 1)[1]
    changed = client.patch(root, json={"answers": {"objective": "A changed scientific objective."}}).json()
    assert not changed["prepared"] and changed["analysis"] is None
    assert client.get(f"/api/challenges/{token}").status_code == 404
    assert client.get(root + "/download/researcher").status_code == 404


def test_prepare_is_idempotent_and_confirmation_required(client):
    item = create_example(client)
    root = f"/api/projects/{item['id']}"
    client.post(root + "/analyze")
    assert client.post(root + "/prepare", json={"acknowledge_review": False}).status_code == 422
    first = client.post(root + "/prepare", json={"acknowledge_review": True}).json()
    second = client.post(root + "/prepare", json={"acknowledge_review": True}).json()
    assert first["prepared"] == second["prepared"]


def test_invalid_upload_preserves_existing_dataset(client):
    item = create_example(client)
    root = f"/api/projects/{item['id']}"
    for filename, content in [("bad.csv", b"x,x\n1,2\n"), ("bad.csv", b"a,b\n1\n"), ("bad.zip", b"hello")]:
        r = client.post(root + "/dataset", files={"file": (filename, content)})
        assert r.status_code == 422
        assert client.get(root).json()["dataset"] == item["dataset"]


def test_upload_config_uses_the_csv_byte_limit(client):
    config = client.get("/api/config").json()
    assert config["max_upload_mb"] == 200
    assert config["max_upload_bytes"] == datasets.MAX_BYTES == 200 * 1024 * 1024


def test_upload_byte_boundary_and_failed_replacement(client, app, monkeypatch):
    item = create_example(client)
    root = f"/api/projects/{item['id']}"
    content = b"x,y\n1,2\n"
    monkeypatch.setattr(datasets, "MAX_BYTES", len(content))
    accepted = client.post(root + "/dataset", files={"file": ("boundary.csv", content)})
    assert accepted.status_code == 200, accepted.text
    previous = accepted.json()
    directory = app.state.store.directory(item["id"])
    assert (directory / "dataset.csv").read_bytes() == content
    rejected = client.post(root + "/dataset", files={"file": ("too-large.csv", content + b"\n")})
    assert rejected.status_code == 422
    assert "200 MB" in rejected.json()["detail"]
    assert "Google Drive" in rejected.json()["detail"]
    assert "Anyone with the link" in rejected.json()["detail"]
    assert "Viewer" in rejected.json()["detail"]
    assert client.get(root).json()["dataset"] == previous["dataset"]
    assert client.get(root).json()["revision"] == previous["revision"]
    assert (directory / "dataset.csv").read_bytes() == content
    assert not (directory / "upload.tmp").exists()


def test_real_csv_upload_and_regression(client):
    item = client.post("/api/projects", json={"title": "Regression"}).json()
    root = f"/api/projects/{item['id']}"
    import numpy as np
    rng = np.random.default_rng(10)
    x = rng.normal(size=160)
    frame = pd.DataFrame({"x": x, "target": 2*x + rng.normal(0, 0.2, 160)})
    r = client.post(root + "/dataset", files={"file": ("regression.csv", frame.to_csv(index=False).encode())})
    assert r.status_code == 200
    client.patch(root, json={"answers": {"objective": "Predict a measurement", "prediction_unit": "Independent experiment", "success_criterion": "MAE under 0.5", "data_origin": "synthetic", "labels_public": "no", "rights": "yes"}, "design": {"target": "target", "task": "regression", "metric": "mae"}})
    audit = client.post(root + "/analyze").json()
    assert audit["analysis"]["summary"]["blockers"] == 0
    assert audit["analysis"]["baseline"]["score"] < audit["analysis"]["baseline"]["dummy_score"]


def test_background_harness_and_no_dataset_path(client):
    item = create_example(client)
    root = f"/api/projects/{item['id']}"
    assert client.post(root + "/run").status_code == 200
    for _ in range(100):
        state = client.get(root).json()
        if state["harness"]["status"] != "running":
            break
        time.sleep(0.03)
    assert state["harness"]["status"] == "complete"
    assert state["analysis"]["baseline"]["status"] == "complete"
    assert len(state["advice"]) == 2
    assert {x["stage"] for x in state["events"]} >= {"scope", "audit", "trial", "review"}
    blank = client.post("/api/projects", json={"brief": "I want to study catalysts"}).json()
    route = f"/api/projects/{blank['id']}"
    client.post(route + "/run")
    for _ in range(100):
        state = client.get(route).json()
        if state["harness"]["status"] != "running":
            break
        time.sleep(0.03)
    assert state["harness"]["status"] == "complete"
    assert state["analysis"] is None
    assert "Attach a CSV" in state["advice"][0]["content"]


def test_session_isolation_and_cross_origin(client, app):
    item = create_example(client)
    with TestClient(app) as other:
        other.post("/api/projects", json={})
        assert item["id"] not in [i["id"] for i in other.get("/api/projects").json()["projects"]]
        assert other.patch(f"/api/projects/{item['id']}", json={"title": "stolen"}).status_code == 404
    assert client.post("/api/projects", json={}, headers={"origin": "https://evil.example"}).status_code == 403
    assert client.get("/api/config", headers={"host": "evil.example"}).status_code == 400


def test_invalid_contract_values(client):
    item = create_example(client)
    root = f"/api/projects/{item['id']}"
    for change in [{"design": {"metric": "bad"}}, {"answers": {"rights": "no"}}, {"_seed": 123}, {"title": "x" * 181}, {"design": {"test_fraction": float("inf")}}]:
        if "test_fraction" in change.get("design", {}):
            continue
        assert client.patch(root, json=change).status_code == 422


def test_unknown_decisions_stay_unresolved(client):
    item = create_example(client)
    root = f"/api/projects/{item['id']}"
    client.patch(root, json={"answers": {"objective": "unknown", "compute_budget": "unknown"}})
    result = client.post(root + "/analyze").json()
    checks = {c["id"]: c for c in result["analysis"]["checks"]}
    assert checks["objective"]["severity"] == "blocker"
    assert checks["compute_budget"]["severity"] == "warning"
    assert result["checklist"][0]["status"] == "missing"


def test_metadata_only_model_context_and_evidenced_updates(client, app):
    item = create_example(client)
    stored = app.state.store.get(item["id"], client.cookies.get("autokaggle_owner"))
    context = model_context(stored, "conversation")
    assert "_seed" not in json.dumps(context)
    assert "_participant" not in json.dumps(context)
    assert "temperature_k" in json.dumps(context)
    assert "dataset.csv" not in json.dumps(context)
    stored["answers"]["objective"] = ""
    before_rights = stored["answers"]["rights"]
    note = {"updates": [{"field": "rights", "value": "yes", "evidence": stored["brief"][:20]}, {"field": "objective", "value": "Fake", "evidence": "not in the brief"}]}
    assert not apply_supported_updates(stored, note)
    assert stored["answers"]["rights"] == before_rights
    assert stored["answers"]["objective"] == ""
    note = {"updates": [{"field": "objective", "value": "Predict stability", "evidence": stored["brief"][:40]}]}
    assert apply_supported_updates(stored, note)


def test_persistence_and_interrupted_run_recovery(client, app):
    item = create_example(client)
    owner = client.cookies.get("autokaggle_owner")
    stored = app.state.store.get(item["id"], owner)
    stored["harness"] = {"status": "running", "stage": "scope"}
    app.state.store.save(stored)
    from autokaggle.store import Store
    reopened = Store(app.state.store.root)
    after = reopened.get(item["id"], owner)
    assert after["_seed"] == stored["_seed"]
    assert after["harness"]["status"] == "failed"
