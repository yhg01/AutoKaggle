"""Distinct researcher and organizer artifacts; no user code is executed."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import zipfile

from .core.datasets import write_partitions
from .onboarding_setup import redact_private
from .scope_exports import public_scopes, scope_text


def description(project):
    a, d = project["answers"], project["design"]
    lines = [f"# {project['title']}", "", project["brief"], "", "## Task", "", a["objective"], "",
        f"Prediction unit: {a['prediction_unit']}", "", f"Useful result: {a['success_criterion']}", "",
        "## Evaluation contract", "", f"- Task: {d['task']}", f"- Target column: `{d['target']}`",
        f"- Metric: `{d['metric']}`", f"- Split method: `{d['split']}`", "- Final evaluation: all test rows and labels remain private.",
        "- Use only the supplied training labels. Do not retrieve or reconstruct hidden answers.",
        "- Develop against your own validation split. There is no final-test feedback during research.", "",
        "## Deliverable", "", "Submit a prediction program with this command interface:", "",
        "```sh", "python predict.py --input INPUT.csv --output predictions.csv", "```", "",
        f"The trusted runner supplies input features with a reserved `_autokaggle_id` column. Return exactly two columns: `_autokaggle_id` and `prediction`. Predictions must match the metric contract in metadata.yaml.", "",
        "The runner must not give the program access to test labels, credentials, or the network. This prototype exports the contract; it does not run arbitrary submitted programs.", "",
        "## Resource estimate", "", f"Compute: {a['compute_budget'] or 'Unknown'}", "", f"Model tokens: {a['token_budget'] or 'Unknown'}", "",
        "Scope: one credible attempt, including experiments and final evaluation.", "",
        "## Status", "", "Local prototype package. Scientific validity needs organizer review. A passed audit does not prove that leakage is absent.", ""]
    notes = scope_text(public_scopes(project))
    if notes:
        lines.extend([notes, ""])
    return redact_private(project, "\n".join(lines))


PREPARE = '''"""Copy only the approved training data into a researcher workspace."""
from pathlib import Path
import argparse
import shutil

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(Path(__file__).parent / "train.csv", args.output_dir / "train.csv")
    print("Training data prepared. Final test data are not in this package.")
'''

EVALUATE_PREPARE = '''"""Trusted organizer use only. Prepare separate inference and scoring inputs."""
from pathlib import Path
import argparse
import json
import pandas as pd

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--inference-dir", type=Path, required=True)
    p.add_argument("--truth-dir", type=Path, required=True)
    a = p.parse_args()
    infer, truth = a.inference_dir.resolve(), a.truth_dir.resolve()
    if infer == truth or infer in truth.parents or truth in infer.parents:
        p.error("Use separate, non-overlapping directories for inference inputs and truth.")
    root = Path(__file__).parent.resolve()
    if infer == root or infer in root.parents or root in infer.parents:
        p.error("Inference inputs must be outside the private organizer package.")
    if infer.exists() and (not infer.is_dir() or any(infer.iterdir())):
        p.error("The inference destination must be new or empty.")
    meta = json.loads((root / "task.json").read_text())
    data = pd.read_csv(root / "test.csv", dtype=str, keep_default_na=False)
    data.insert(0, "_autokaggle_id", [str(i) for i in range(len(data))])
    a.inference_dir.mkdir(parents=True, exist_ok=True)
    a.truth_dir.mkdir(parents=True, exist_ok=True)
    data.drop(columns=[meta["target"]]).to_csv(a.inference_dir / "test_features.csv", index=False)
    data[["_autokaggle_id", meta["target"]]].rename(columns={meta["target"]: "truth"}).to_csv(a.truth_dir / "truth.csv", index=False)
    print("Only inference-dir may be mounted in the isolated prediction runner. Keep truth-dir private.")
'''

EVALUATE = '''"""Trusted scorer. Reads a prediction file; never imports or executes submissions."""
from pathlib import Path
import argparse
import csv
import json
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, balanced_accuracy_score, roc_auc_score, mean_squared_error, mean_absolute_error

def score(truth_path, prediction_path, metric):
    for path, columns in [(truth_path, ["_autokaggle_id", "truth"]), (prediction_path, ["_autokaggle_id", "prediction"])]:
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.reader(f, strict=True)
            header = next(reader, [])
            for row in reader:
                if len(row) != len(columns):
                    raise ValueError("CSV row width does not match the header")
        if header != columns:
            raise ValueError("Expected exactly these columns in order: " + ", ".join(columns))
    truth = pd.read_csv(truth_path, dtype=str, keep_default_na=False)
    predictions = pd.read_csv(prediction_path, dtype=str, keep_default_na=False)
    if truth.empty or len(truth) != len(predictions):
        raise ValueError("Prediction count does not match truth")
    for table in (truth, predictions):
        if table["_autokaggle_id"].duplicated().any() or table["_autokaggle_id"].eq("").any():
            raise ValueError("IDs must be unique and nonempty")
    if set(truth["_autokaggle_id"]) != set(predictions["_autokaggle_id"]):
        raise ValueError("Prediction IDs do not match truth")
    joined = truth.merge(predictions, on="_autokaggle_id", validate="one_to_one")
    y, pred = joined["truth"], joined["prediction"]
    if y.eq("").any() or pred.eq("").any():
        raise ValueError("Missing labels or predictions")
    if metric in ("accuracy", "balanced_accuracy"):
        result = (accuracy_score if metric == "accuracy" else balanced_accuracy_score)(y, pred)
    else:
        y, pred = pd.to_numeric(y, errors="raise"), pd.to_numeric(pred, errors="raise")
        if not np.isfinite(y).all() or not np.isfinite(pred).all():
            raise ValueError("Predictions and truth must be finite")
        if metric == "roc_auc":
            if set(y) != {0, 1} or not pred.between(0, 1).all():
                raise ValueError("ROC AUC requires 0/1 truth and probabilities from 0 to 1")
            result = roc_auc_score(y, pred)
        elif metric == "rmse":
            result = np.sqrt(mean_squared_error(y, pred))
        elif metric == "mae":
            result = mean_absolute_error(y, pred)
        else:
            raise ValueError("Unknown metric")
    if not np.isfinite(result):
        raise ValueError("The score is not finite. Check the scale of values.")
    return {"metric": metric, "score": float(result), "rows": len(truth)}

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--truth", type=Path, required=True)
    p.add_argument("--predictions", type=Path, required=True)
    p.add_argument("--metric", choices=["accuracy", "balanced_accuracy", "roc_auc", "rmse", "mae"], required=True)
    a = p.parse_args()
    print(json.dumps(score(a.truth, a.predictions, a.metric)))
'''


def package(project, source: Path, directory: Path):
    work = directory / "package_work"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(mode=0o700)
    result = write_partitions(source, project["design"], project["_seed"], work)
    public = work / "researcher"
    private = work / "organizer"
    public.mkdir()
    private.mkdir(mode=0o700)
    shutil.copyfile(work / "train.csv", public / "train.csv")
    shutil.copyfile(work / "test.csv", private / "test.csv")
    meta = {"format": "autokaggle.task.v1", "title": project["title"], "task": project["design"]["task"],
        "target": project["design"]["target"], "metric": project["design"]["metric"],
        "metric_direction": "minimize" if project["design"]["metric"] in {"rmse", "mae"} else "maximize",
        "prediction_type": "probability_of_1" if project["design"]["metric"] == "roc_auc" else "class_label" if project["design"]["task"] == "classification" else "number",
        "split_strategy": project["design"]["split"], "train_file": "train.csv", "hidden_test": True,
        "compute_estimate_usd": project["answers"]["compute_budget"] or "unknown",
        "token_estimate_usd": project["answers"]["token_budget"] or "unknown",
        "scope_decisions": public_scopes(project),
        "sota": None, "harness_compatibility": "Generic contract; AIRS-Bench adapter not validated"}
    for folder in (public, private):
        (folder / "project_description.md").write_text(description(project))
        (folder / "task.json").write_text(redact_private(project, json.dumps(meta, indent=2)))
        # JSON is valid YAML; avoid an extra serializer and preserve exact values.
        (folder / "metadata.yaml").write_text(redact_private(project, json.dumps(meta, indent=2)) + "\n")
        (folder / "requirements.txt").write_text("pandas>=2.0\nnumpy>=1.26\nscikit-learn>=1.3\n")
    (public / "prepare.py").write_text(PREPARE)
    (public / "README.md").write_text("# Researcher package\n\nRead project_description.md. train.csv is the only dataset in this package. Hold out part of it for development. Final test inputs and labels are withheld.\n\nRun `python prepare.py --output-dir workspace` to copy the training data.\n")
    (private / "evaluate_prepare.py").write_text(EVALUATE_PREPARE)
    (private / "evaluate.py").write_text(EVALUATE)
    (private / "audit.json").write_text(json.dumps(project["analysis"], indent=2))
    (private / "trace.json").write_text(json.dumps(project.get("events", []), indent=2))
    (private / "README.md").write_text("# Private organizer package\n\nDo not share this package with researchers or agents. It contains the complete held-out rows.\n\n1. Run `python evaluate_prepare.py --inference-dir /PRIVATE/inference --truth-dir /PRIVATE/truth`.\n2. Use a separate isolated runner for submitted predict.py. Mount only inference inputs; keep labels, network, and credentials unavailable. This runner is not implemented in the prototype.\n3. Use `python evaluate.py --truth /PRIVATE/truth/truth.csv --predictions predictions.csv --metric " + project["design"]["metric"] + "`. This scorer never executes submitted code.\n\nThe scorer does not enforce a one-submission limit. A trusted run registry must enforce feedback and retry policy in production.\n")
    manifests = {}
    for kind, folder in [("researcher", public), ("organizer", private)]:
        manifest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.iterdir())}
        (folder / "manifest.json").write_text(json.dumps({"files": manifest, "revision": project["revision"]}, indent=2))
        tmp = directory / f"{kind}.zip.tmp"
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for p in sorted(folder.iterdir()):
                z.write(p, p.name)
        tmp.replace(directory / f"{kind}.zip")
        manifests[kind] = hashlib.sha256((directory / f"{kind}.zip").read_bytes()).hexdigest()
    shutil.rmtree(work)
    return {**result, "archive_sha256": manifests}
