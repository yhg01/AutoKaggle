import copy
import hashlib
import json
from pathlib import Path

import pytest

from autokaggle import lite_quality as quality


def plan(contract=None):
    contract = contract or {"outputs": "Return primary and secondary scores."}
    return {"schema": quality.SCHEMA, "requirements": [
        {"id": f"R{i:03d}", "field": key, "quote": value if isinstance(value, str) else json.dumps(value, sort_keys=True),
         "kind": "protocol", "behavior": "Check the declared behavior."}
        for i, (key, value) in enumerate(contract.items(), 1) if key != "title"],
        "result_requirements": {"metrics": ["primary", "secondary"], "outputs": ["curve"], "reference_required": True}}


def test_plan_rejects_omitted_contract_fields_and_invented_evidence():
    c = {"metric_definition": "Return both distances.", "inputs": "All windows are required."}
    p = plan(c)
    assert quality.parse_plan(p, c) == p
    p["requirements"].pop()
    with pytest.raises(ValueError, match="omits contract fields"):
        quality.parse_plan(p, c)
    p = plan(c)
    p["requirements"][0]["quote"] = "Only one distance."
    with pytest.raises(ValueError, match="exact accepted"):
        quality.parse_plan(p, c)


@pytest.mark.parametrize("mutation", ["missing_metric", "nan", "missing_output", "escape", "wrong_reference", "wrong_mode"])
def test_completed_scalar_cannot_hide_missing_evidence(tmp_path, mutation):
    (tmp_path / "curve.json").write_text('[1,2,3]')
    manifest = {"output_directory": str(tmp_path), "evaluation_mode": "research", "reference_sha256": "a" * 64}
    record = {"status": "completed", "score": 1, "metrics": {"primary": 1, "secondary": 2},
              "outputs": {"curve": "curve.json"}, "reference": {"identity": "reference v1", "sha256": "a" * 64, "mode": "research"}}
    valid = quality.result_evidence(copy.deepcopy(record), manifest, plan())
    assert valid["output_files"]["curve"]["sha256"] == hashlib.sha256(b"[1,2,3]").hexdigest()
    if mutation == "missing_metric": record["metrics"].pop("secondary")
    if mutation == "nan": record["metrics"]["secondary"] = float("nan")
    if mutation == "missing_output": record["outputs"] = {}
    if mutation == "escape": record["outputs"]["curve"] = "../curve.json"
    if mutation == "wrong_reference": record["reference"]["sha256"] = "b" * 64
    if mutation == "wrong_mode": record["reference"]["mode"] = "synthetic"
    with pytest.raises(ValueError): quality.result_evidence(record, manifest, plan())


def test_directory_digest_binds_paths_content_and_rejects_links(tmp_path):
    root = tmp_path / "shards"
    root.mkdir()
    (root / "a").write_bytes(b"abc")
    first = quality.digest(root)
    (root / "a").rename(root / "b")
    assert quality.digest(root) != first
    (root / "b").write_bytes(b"abd")
    second = quality.digest(root)
    assert second != first
    (root / "alias").symlink_to(root / "b")
    with pytest.raises(ValueError, match="links"): quality.digest(root)


@pytest.mark.parametrize("body, mapped, passes", [
    ("self.assertEqual(2+2,4)", "test_sample.Check.test_score", True),
    ("self.skipTest('no asset')", "test_sample.Check.test_score", False),
    ("self.assertEqual(2+2,5)", "test_sample.Check.test_score", False),
    ("self.assertEqual(2+2,4)", "test_sample.Check.test_nonexistent", False),
])
def test_coverage_requires_real_passing_tests(tmp_path, body, mapped, passes):
    # Use a separate interpreter so unittest imports cannot leak between cases.
    import subprocess, sys
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_sample.py").write_text("import unittest\nclass Check(unittest.TestCase):\n def test_score(self):\n  " + body + "\n")
    (tmp_path / "coverage.json").write_text(json.dumps({"R001": [mapped]}))
    (tmp_path / "quality.json").write_text(json.dumps(plan()))
    (tmp_path / "contract.json").write_text(json.dumps({"contract": {"outputs": "Return primary and secondary scores."}}))
    result = subprocess.run([sys.executable, quality.__file__, str(tmp_path / "report.json")], cwd=tmp_path, capture_output=True)
    assert (result.returncode == 0) == passes
    assert json.loads((tmp_path / "report.json").read_text())["passed"] == passes


def test_reported_metadata_preserves_outputs_without_claiming_file_verification():
    record = {'metrics': {'primary': 0.5, 'secondary': 0.2}, 'evaluation_mode': 'research',
              'outputs': {'curve': 'curve.json'}, 'output_files': {'curve': {'path': 'curve.json', 'bytes': 30, 'sha256': 'a'*64}},
              'reference': {'identity': 'licensed reference version 1', 'sha256': 'b'*64, 'mode': 'research'},
              'output_directory': '123'}
    assert quality.validate_metadata(copy.deepcopy(record)) == record
    for change in ('path', 'digest', 'metric', 'mode'):
        altered = copy.deepcopy(record)
        if change == 'path': altered['outputs']['curve'] = '../outside'
        if change == 'digest': altered['output_files']['curve']['sha256'] = 'bad'
        if change == 'metric': altered['metrics']['secondary'] = float('inf')
        if change == 'mode': altered['reference']['mode'] = 'synthetic'
        with pytest.raises(ValueError): quality.validate_metadata(altered)
