"""Regression checks for exported evaluation and the model boundary."""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from autokaggle import advisor
from autokaggle.exports import EVALUATE, EVALUATE_PREPARE
from autokaggle.store import ANSWERS, DESIGN


@pytest.fixture
def scorer():
    namespace = {"__name__": "exported_scorer_test"}
    exec(compile(EVALUATE, "exported_evaluate.py", "exec"), namespace)
    return namespace["score"]


def files(tmp_path: Path, labels, predictions, ids=None):
    ids = ids or [str(i) for i in range(len(labels))]
    truth, prediction = tmp_path / "truth.csv", tmp_path / "predictions.csv"
    pd.DataFrame({"_autokaggle_id": ids, "truth": labels}).to_csv(truth, index=False)
    pd.DataFrame({"_autokaggle_id": ids, "prediction": predictions}).to_csv(prediction, index=False)
    return truth, prediction


@pytest.mark.parametrize("metric,labels,predictions,expected", [
    ("accuracy", [0, 0, 1, 1], [0, 1, 1, 1], 0.75),
    ("balanced_accuracy", [0, 0, 0, 1], [0, 0, 1, 0], 1 / 3),
    ("roc_auc", [0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9], 1.0),
    ("rmse", [1, 2, 3], [2, 2, 2], math.sqrt(2 / 3)),
    ("mae", [1, 2, 3], [2, 2, 2], 2 / 3),
])
def test_reference_scorer_all_metrics(scorer, tmp_path, metric, labels, predictions, expected):
    result = scorer(*files(tmp_path, labels, predictions), metric)
    assert result["score"] == pytest.approx(expected)
    assert result["rows"] == len(labels)
    assert result["metric"] == metric


@pytest.mark.parametrize("metric", ["accuracy", "balanced_accuracy"])
def test_unseen_prediction_label_is_scored_as_wrong(scorer, tmp_path, metric):
    # A valid training class can be absent from a particular test sample.
    result = scorer(*files(tmp_path, ["a", "a", "b", "b"], ["a", "c", "b", "c"]), metric)
    assert result["score"] == 0.5


def test_scoring_preserves_string_labels_and_ids(scorer, tmp_path):
    truth, prediction = files(tmp_path, ["001", "NA", "N/A", "null"], ["001", "NA", "N/A", "null"], ids=["0001", "0002", "0003", "0004"])
    assert scorer(truth, prediction, "accuracy")["score"] == 1.0


def test_shuffled_prediction_rows_join_by_identifier(scorer, tmp_path):
    truth, prediction = files(tmp_path, [0, 1, 0, 1], [0, 1, 0, 1])
    shuffled = pd.read_csv(prediction).iloc[[2, 0, 3, 1]]
    shuffled.to_csv(prediction, index=False)
    assert scorer(truth, prediction, "accuracy")["score"] == 1.0


@pytest.mark.parametrize("content", [
    "_autokaggle_id,prediction\n0,0\n",  # missing row
    "_autokaggle_id,prediction\n0,0\n2,1\n",  # wrong identifier
    "_autokaggle_id,prediction\n0,0\n0,1\n",  # duplicate identifier
    "_autokaggle_id,prediction\n,0\n1,1\n",  # blank identifier
    "_autokaggle_id,prediction\n0,\n1,1\n",  # blank prediction
    "prediction,_autokaggle_id\n0,0\n1,1\n",  # wrong column order
    "_autokaggle_id,prediction,extra\n0,0,x\n1,1,x\n",
    "_autokaggle_id,prediction,prediction\n0,0,0\n1,1,1\n",
    "_autokaggle_id,prediction\ngarbage,0,0\ngarbage,1,1\n",  # implicit pandas index
    "_autokaggle_id,prediction\n0\n1,1\n",  # short row
])
def test_malformed_prediction_files_fail(scorer, tmp_path, content):
    truth, prediction = files(tmp_path, [0, 1], [0, 1])
    prediction.write_text(content)
    with pytest.raises((ValueError, pd.errors.ParserError)):
        scorer(truth, prediction, "accuracy")


@pytest.mark.parametrize("metric", ["roc_auc", "rmse", "mae"])
@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_numeric_metrics_reject_nonfinite_predictions(scorer, tmp_path, metric, value):
    with pytest.raises(ValueError):
        scorer(*files(tmp_path, [0, 1], [value, "1"]), metric)


@pytest.mark.parametrize("labels,predictions", [([0, 1], [-0.1, 1]), ([0, 1], [0, 1.1]), (["a", "b"], [0, 1]), ([0, 0], [0, 1]), ([1, 2], [0, 1])])
def test_auc_requires_binary_truth_and_probabilities(scorer, tmp_path, labels, predictions):
    with pytest.raises(ValueError):
        scorer(*files(tmp_path, labels, predictions), "roc_auc")


@pytest.mark.parametrize("metric", ["mae", "rmse"])
def test_numeric_metric_overflow_does_not_return_infinity(scorer, tmp_path, metric):
    with pytest.raises(ValueError):
        scorer(*files(tmp_path, [1e308, 1e308], [-1e308, -1e308]), metric)


def test_unknown_metric_fails(scorer, tmp_path):
    with pytest.raises(ValueError, match="Unknown metric"):
        scorer(*files(tmp_path, [0, 1], [0, 1]), "invented_metric")


def test_evaluation_preparation_preserves_values_and_withholds_target(tmp_path):
    package_dir = tmp_path / "organizer"
    package_dir.mkdir()
    (package_dir / "evaluate_prepare.py").write_text(EVALUATE_PREPARE)
    (package_dir / "task.json").write_text(json.dumps({"target": "target"}))
    source = pd.DataFrame({"code": ["0007", "0008", "0009"], "token": ["NA", "N/A", "null"], "precise": ["0.0000000000000000000000001", "1.00000000000000001", "-0"], "target": ["class a", "class b", "class c"]})
    source.to_csv(package_dir / "test.csv", index=False)
    run = subprocess.run([sys.executable, str(package_dir / "evaluate_prepare.py"), "--inference-dir", str(tmp_path / "inference"), "--truth-dir", str(tmp_path / "private_truth")], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    features = pd.read_csv(tmp_path / "inference/test_features.csv", dtype=str, keep_default_na=False)
    truth = pd.read_csv(tmp_path / "private_truth/truth.csv", dtype=str, keep_default_na=False)
    assert features.drop(columns="_autokaggle_id").equals(source.drop(columns="target"))
    assert truth["truth"].tolist() == source["target"].tolist()
    assert truth["_autokaggle_id"].tolist() == features["_autokaggle_id"].tolist()
    assert "target" not in features
    bad = subprocess.run([sys.executable, str(package_dir / "evaluate_prepare.py"), "--inference-dir", str(tmp_path / "same"), "--truth-dir", str(tmp_path / "same")], capture_output=True, text=True)
    assert bad.returncode != 0
    assert not (tmp_path / "same").exists()


@pytest.mark.parametrize("layout", ["equal", "inference_parent", "truth_parent", "package_equal", "package_parent", "package_child", "package_symlink", "nonempty_inference"])
def test_evaluation_preparation_rejects_unsafe_directory_layouts(tmp_path, layout):
    package_dir = tmp_path / "organizer"
    package_dir.mkdir()
    (package_dir / "evaluate_prepare.py").write_text(EVALUATE_PREPARE)
    (package_dir / "task.json").write_text(json.dumps({"target": "target"}))
    (package_dir / "test.csv").write_text("feature,target\nexample,secret label\n")
    infer, truth = tmp_path / "inference", tmp_path / "truth"
    if layout == "equal":
        truth = infer
    elif layout == "inference_parent":
        truth = infer / "private_truth"
    elif layout == "truth_parent":
        infer = truth / "features"
    elif layout == "package_equal":
        infer = package_dir
    elif layout == "package_parent":
        infer = package_dir.parent
    elif layout == "package_child":
        infer = package_dir / "features"
    elif layout == "package_symlink":
        infer.symlink_to(package_dir, target_is_directory=True)
    elif layout == "nonempty_inference":
        infer.mkdir()
        (infer / "private_old_labels.csv").write_text("private source data")
    before = (package_dir / "test.csv").read_bytes()
    run = subprocess.run([sys.executable, str(package_dir / "evaluate_prepare.py"), "--inference-dir", str(infer), "--truth-dir", str(truth)], capture_output=True, text=True)
    assert run.returncode != 0, "Unsafe input paths were accepted"
    assert not (infer / "test_features.csv").exists()
    assert not (truth / "truth.csv").exists()
    assert (package_dir / "test.csv").read_bytes() == before
    if layout == "nonempty_inference":
        assert (infer / "private_old_labels.csv").read_text() == "private source data"


@pytest.fixture
def project():
    return {"id": "test-project", "title": "Predict stability", "brief": "Predict material stability from measurements made before the stress test. One independent material sample per row. Compute costs USD 20 and model tokens cost USD 5.",
            "answers": copy.deepcopy(ANSWERS), "design": copy.deepcopy(DESIGN), "dataset": None, "analysis": None, "advice": [], "_model_calls": 0, "_seed": 999, "_participant": "private-capability"}


def provider(monkeypatch, output, status="completed", error=None, before_call=None):
    monkeypatch.setenv("AUTOKAGGLE_MODE", "model")
    monkeypatch.setenv("OPENAI_API_KEY", "not-a-real-key")
    calls = []

    class FakeClient:
        def __init__(self, **kwargs):
            self.responses = self
            self.options = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def create(self, **kwargs):
            calls.append(kwargs)
            if before_call:
                before_call()
            if error:
                raise error
            return SimpleNamespace(status=status, output_text=output if isinstance(output, str) else json.dumps(output), model="gpt-6.1-sol", usage=SimpleNamespace(input_tokens=100, output_tokens=50))

    import openai
    monkeypatch.setattr(openai, "OpenAI", FakeClient)
    return calls


def valid_advice(**changes):
    return {"content": "Review the prediction unit and define the success criterion.", "next_questions": ["What is one observation?"], "updates": [], **changes}


@pytest.mark.parametrize("kind,effort", [("conversation", "medium"), ("review", "high")])
def test_model_request_uses_metadata_and_expected_reasoning(monkeypatch, project, kind, effort):
    calls = provider(monkeypatch, valid_advice(updates=[{"field": "objective", "value": "Predict material stability", "evidence": "Predict material stability"}]))
    result = advisor.advise(project, kind)
    assert result["mode"] == "model"
    assert project["_model_calls"] == 1
    assert calls[0]["reasoning"] == {"effort": effort}
    assert calls[0]["text"]["format"]["strict"] is True
    sent = json.loads(calls[0]["input"])
    assert "_seed" not in sent and "_participant" not in sent
    assert "private-capability" not in calls[0]["input"]
    assert result["usage"] == {"input_tokens": 100, "output_tokens": 50}
    if kind == "review":
        assert result["updates"] == []


def test_provider_failure_has_safe_rules_fallback(monkeypatch, project):
    calls = provider(monkeypatch, None, error=RuntimeError("SECRET_KEY and private source text must not be shown"))
    result = advisor.advise(project, "conversation")
    assert len(calls) == 1 and project["_model_calls"] == 1
    assert result["mode"] == "rules" and result["content"]
    assert "RuntimeError" in result["notice"]
    assert "SECRET_KEY" not in json.dumps(result)
    assert result["updates"] == []


@pytest.mark.parametrize("output,status", [
    ("not json", "completed"),
    (valid_advice(), "incomplete"),
    ({"content": "", "next_questions": [], "updates": []}, "completed"),
    ({"content": "Some advice"}, "completed"),
    (valid_advice(next_questions="wrong shape"), "completed"),
    (valid_advice(next_questions=[42]), "completed"),
    (valid_advice(updates=["not an object"]), "completed"),
    (valid_advice(updates=[{"field": "objective", "value": "missing evidence"}]), "completed"),
    (valid_advice(updates=[{"field": "objective", "value": "Predict stability", "evidence": ["wrong type"]}]), "completed"),
    (valid_advice(updates=[{"field": "objective", "value": "Predict stability", "evidence": "Predict stability", "unexpected": "extra property"}]), "completed"),
    (valid_advice(unexpected="extra property"), "completed"),
    (["wrong root type"], "completed"),
])
def test_invalid_model_result_is_not_applied(monkeypatch, project, output, status):
    provider(monkeypatch, output, status=status)
    result = advisor.advise(project, "conversation")
    assert result["mode"] == "rules"
    assert result["updates"] == []
    assert result["next_questions"] == []
    assert result["notice"]
    assert not advisor.apply_supported_updates(project, result)


def test_model_call_limit_is_reserved_before_request(monkeypatch, project):
    project["_model_calls"] = 11
    reserved = []
    calls = provider(monkeypatch, valid_advice(), before_call=lambda: reserved and all(value == 12 for value in reserved) or pytest.fail("The call was not reserved before the provider request"))
    first = advisor.advise(project, "conversation", reserve=lambda item: reserved.append(item["_model_calls"]))
    second = advisor.advise(project, "conversation", reserve=lambda item: reserved.append(item["_model_calls"]))
    assert first["mode"] == "model"
    assert second["mode"] == "rules" and "12-call" in second["notice"]
    assert len(calls) == 1 and reserved and all(value == 12 for value in reserved)
    assert project["_model_calls"] == 12


def test_failed_provider_call_also_counts_towards_limit(monkeypatch, project):
    project["_model_calls"] = 11
    calls = provider(monkeypatch, None, error=TimeoutError("private details"))
    first = advisor.advise(project, "conversation")
    second = advisor.advise(project, "conversation")
    assert first["mode"] == second["mode"] == "rules"
    assert len(calls) == 1 and project["_model_calls"] == 12


def test_rule_mode_never_calls_provider(monkeypatch, project):
    calls = provider(monkeypatch, valid_advice())
    monkeypatch.setenv("AUTOKAGGLE_MODE", "rules")
    result = advisor.advise(project, "conversation")
    assert result["mode"] == "rules"
    assert calls == [] and project["_model_calls"] == 0


def test_supported_updates_need_source_evidence_and_empty_fields(project):
    project["answers"]["objective"] = "Keep the scientist's statement."
    note = {"updates": [
        {"field": "objective", "value": "Overwrite existing answer", "evidence": "Predict material stability"},
        {"field": "rights", "value": "yes", "evidence": "Predict material stability"},
        {"field": "labels_public", "value": "no", "evidence": "Predict material stability"},
        {"field": "compute_budget", "value": "USD 20", "evidence": "Compute costs USD 20"},
        {"field": "token_budget", "value": "USD 99", "evidence": "not stated anywhere"},
        {"field": "prediction_unit", "value": "One independent material sample", "evidence": "One independent material sample per row"},
        {"field": "success_criterion", "value": "Something", "evidence": "Predict"},
    ]}
    assert advisor.apply_supported_updates(project, note)
    assert project["answers"]["objective"] == "Keep the scientist's statement."
    assert project["answers"]["rights"] == "unknown"
    assert project["answers"]["labels_public"] == "unknown"
    assert project["answers"]["compute_budget"] == "USD 20"
    assert project["answers"]["token_budget"] == ""
    assert project["answers"]["success_criterion"] == ""
    assert {item["field"] for item in note["applied"]} == {"compute_budget", "prediction_unit"}


def test_model_question_and_update_counts_are_bounded(monkeypatch, project):
    update = {"field": "objective", "value": "Predict material stability", "evidence": "Predict material stability"}
    provider(monkeypatch, valid_advice(next_questions=[f"Question {i}?" for i in range(20)], updates=[update] * 20))
    result = advisor.advise(project, "conversation")
    assert result["mode"] == "model"
    assert len(result["next_questions"]) <= 3 and len(result["updates"]) == 16


def proposed_design_note():
    return {"updates": [
        {"field": "target", "value": "stable", "evidence": "Predict the binary stable column"},
        {"field": "task", "value": "classification", "evidence": "Predict the binary stable column"},
        {"field": "metric", "value": "balanced_accuracy", "evidence": "Use balanced accuracy to assess performance"},
        {"field": "split", "value": "group", "evidence": "Keep all samples from each lab together"},
        {"field": "group_column", "value": "lab", "evidence": "Keep all samples from each lab together"},
    ]}


def setup_design_evidence(project):
    project["brief"] = "Predict the binary stable column. Use balanced accuracy to assess performance. Keep all samples from each lab together."
    project["dataset"] = {"columns": [{"name": "stable"}, {"name": "lab"}, {"name": "feature"}]}


def test_design_can_be_proposed_only_from_exact_brief_evidence(project):
    setup_design_evidence(project)
    note = proposed_design_note()
    assert advisor.apply_supported_updates(project, note)
    assert project["design"]["target"] == "stable"
    assert project["design"]["task"] == "classification"
    assert project["design"]["metric"] == "balanced_accuracy"
    assert project["design"]["split"] == "group"
    assert project["design"]["group_column"] == "lab"
    assert len(note["applied"]) == 5


def test_existing_design_is_never_changed_by_model_proposal(project):
    setup_design_evidence(project)
    project["design"].update(target="stable", metric="accuracy", split="time", time_column="lab")
    original = copy.deepcopy(project["design"])
    assert not advisor.apply_supported_updates(project, proposed_design_note())
    assert project["design"] == original


def test_unsupported_design_proposals_are_ignored(project):
    setup_design_evidence(project)
    note = {"updates": [
        {"field": "target", "value": "unknown_column", "evidence": "Predict the binary stable column"},
        {"field": "task", "value": "clustering", "evidence": "Predict the binary stable column"},
        {"field": "metric", "value": "balanced_accuracy", "evidence": "not a quote from the source brief"},
        {"field": "split", "value": "random", "evidence": "Short"},
        {"field": "group_column", "value": "unknown_column", "evidence": "Keep all samples from each lab together"},
        {"field": "test_fraction", "value": "0.5", "evidence": "Predict the binary stable column"},
    ]}
    original = copy.deepcopy(project["design"])
    assert not advisor.apply_supported_updates(project, note)
    assert project["design"] == original


@pytest.mark.parametrize("left,right", [('"', '"'), ("'", "'"), ("“", "”"), ("‘", "’")])
def test_one_outer_quote_pair_can_wrap_exact_source_evidence(project, left, right):
    setup_design_evidence(project)
    note = proposed_design_note()
    note["updates"].insert(0, {"field": "objective", "value": "Predict stability", "evidence": "Predict the binary stable column"})
    for proposal in note["updates"]:
        proposal["evidence"] = left + proposal["evidence"] + right
    original_updates = copy.deepcopy(note["updates"])
    assert advisor.apply_supported_updates(project, note)
    assert project["answers"]["objective"] == "Predict stability"
    assert project["design"]["target"] == "stable"
    assert project["design"]["metric"] == "balanced_accuracy"
    assert project["design"]["split"] == "group"
    assert len(note["applied"]) == 6
    assert all(change["evidence"] in project["brief"] for change in note["applied"])
    assert note["updates"] == original_updates


@pytest.mark.parametrize("evidence", [
    '"Predict the binary stable column’',  # mismatched quotes
    '\'"Predict the binary stable column"\'',  # two added pairs
    '"Predict the binary  stable column"',  # altered source spacing
    '"Predict the binary ... column"',  # abbreviated source
    '"Predict"',  # fewer than eight source characters
    ' "Predict the binary stable column" ',  # added whitespace outside the quotes
    None,
    ["Predict the binary stable column"],
])
def test_quote_normalization_does_not_weaken_exact_evidence_check(project, evidence):
    setup_design_evidence(project)
    note = {"updates": [{"field": "target", "value": "stable", "evidence": evidence}]}
    assert not advisor.apply_supported_updates(project, note)
    assert project["design"]["target"] == ""
    assert note["applied"] == []


def test_evidence_already_quoted_in_source_is_preserved(project):
    evidence = '"Predict material stability"'
    project["brief"] = f"The scientist wrote {evidence} in the initial brief."
    note = {"updates": [{"field": "objective", "value": "Predict material stability", "evidence": evidence}]}
    assert advisor.apply_supported_updates(project, note)
    assert note["applied"] == [{"field": "objective", "evidence": evidence}]


def test_all_supported_answer_and_design_updates_are_retained(monkeypatch, project):
    setup_design_evidence(project)
    project["brief"] += " One independent sample per row. Balanced accuracy above 0.8 is useful. Compute costs USD 20. Model tokens cost USD 5. Dates are recorded in measured_at."
    project["dataset"]["columns"].append({"name": "measured_at"})
    updates = [
        {"field": "objective", "value": "Predict stability", "evidence": "Predict the binary stable column"},
        {"field": "prediction_unit", "value": "One independent sample", "evidence": "One independent sample per row"},
        {"field": "success_criterion", "value": "Balanced accuracy above 0.8", "evidence": "Balanced accuracy above 0.8 is useful"},
        {"field": "compute_budget", "value": "USD 20", "evidence": "Compute costs USD 20"},
        {"field": "token_budget", "value": "USD 5", "evidence": "Model tokens cost USD 5"},
        *proposed_design_note()["updates"],
        {"field": "time_column", "value": "measured_at", "evidence": "Dates are recorded in measured_at"},
    ]
    calls = provider(monkeypatch, valid_advice(updates=updates))
    note = advisor.advise(project, "conversation")
    assert len(updates) == 11
    assert note["updates"] == updates
    assert advisor.apply_supported_updates(project, note)
    assert len(note["applied"]) == 11
    assert project["design"]["target"] == "stable"
    assert project["design"]["metric"] == "balanced_accuracy"
    assert project["design"]["split"] == "group"
    assert project["design"]["group_column"] == "lab"
    assert project["design"]["time_column"] == "measured_at"
    assert project["answers"]["token_budget"] == "USD 5"
    assert "provisional defaults" in calls[0]["instructions"]
    assert "without added quotation marks" in calls[0]["instructions"]


def test_advice_api_persists_call_limit_and_evidenced_update(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from autokaggle.app import create_app
    from autokaggle.store import Store

    calls = provider(monkeypatch, valid_advice(updates=[{"field": "objective", "value": "Predict material stability", "evidence": "Predict material stability"}]))
    app = create_app(tmp_path / "data")
    try:
        with TestClient(app) as client:
            item = client.post("/api/projects", json={"brief": "Predict material stability from initial measurements."}).json()
            owner = client.cookies.get("autokaggle_owner")
            stored = app.state.store.get(item["id"], owner)
            stored["_model_calls"] = 11
            app.state.store.save(stored)
            endpoint = f"/api/projects/{item['id']}/advise"
            first = client.post(endpoint, json={"kind": "conversation"})
            assert first.status_code == 200, first.text
            state = first.json()
            assert state["answers"]["objective"] == "Predict material stability"
            assert state["advice"][-1]["applied"] == [{"field": "objective", "evidence": "Predict material stability"}]
            assert "_model_calls" not in state
            assert Store(tmp_path / "data").get(item["id"], owner)["_model_calls"] == 12
            second = client.post(endpoint, json={"kind": "conversation"})
            assert second.status_code == 200, second.text
            assert second.json()["advice"][-1]["mode"] == "rules"
            assert "12-call" in second.json()["notices"][0]
            assert len(calls) == 1
    finally:
        app.state.pool.shutdown(wait=True)
