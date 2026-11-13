"""Run a pinned evaluator on declared research assets in the existing runtime.

The web process obtains bounded public files with pinned destinations. Jobs get
only their own files. A researcher must give an independently established score.
No uploaded claim or synthetic fixture can mark research validation complete.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys


def check(root, inputs, output, python, request=None):
    root, inputs, output = Path(root), Path(inputs), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    request = request or json.loads((inputs / "research.json").read_text())
    args = [python, "evaluate.py", "--mode", "research", "--artifact", str(inputs / "artifact"),
            "--output", str(output / "results.json"), "--resources", request["resources"],
            "--provenance", request["expected_basis"]]
    if request.get("reference_sha256"):
        args += ["--reference", request.get("_reference_directory") or str(inputs / "reference")]
    done = subprocess.run(args, cwd=root, capture_output=True, text=True, timeout=request["timeout_seconds"])
    result = json.loads((output / "results.json").read_text()) if (output / "results.json").is_file() else {}
    summary = result.get("summary", {})
    observed = summary.get("score")
    manifest = result.get("manifest", {})
    complete = done.returncode == 0 and summary.get("status") == "complete" and summary.get("failed") == 0 and bool(result.get("results"))
    matches = (isinstance(observed, (int, float)) and not isinstance(observed, bool) and math.isfinite(observed)
               and math.isclose(observed, request["expected_fitness"], rel_tol=request["tolerance"], abs_tol=request["tolerance"]))
    reference_ok = not request.get("reference_sha256") or manifest.get("reference_sha256") == request["reference_sha256"]
    passed = (complete and matches and reference_ok and manifest.get("code_revision") == request["commit"]
              and manifest.get("contract_sha256") == request["contract_sha256"]
              and manifest.get("artifact_sha256") == request["artifact_sha256"] and manifest.get("evaluation_mode") == "research")
    report = {"passed": passed, "mode": "research", "commit": request["commit"], "contract_sha256": request["contract_sha256"],
              "expected_fitness": request["expected_fitness"], "observed_fitness": observed, "tolerance": request["tolerance"],
              "expected_basis": request["expected_basis"], "artifact_sha256": request["artifact_sha256"],
              "reference_sha256": request.get("reference_sha256") or request["artifact_sha256"],
              "reference_basis": "supplied_reference" if request.get("reference_sha256") else "declared_input_artifact",
              "reference_archive_sha256": request.get("reference_archive_sha256"),
              "result_sha256": hashlib.sha256((output / "results.json").read_bytes()).hexdigest() if result else None,
              "detail": "The declared research run matched its independent expected score." if passed else
                        (done.stderr[-1800:] or "The run did not match its declared score, asset, or release."),
              "resources": request["resources"]}
    (output / "research-report.json").write_text(json.dumps(report, indent=2, allow_nan=False))
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", required=True)
    parser.add_argument("--work", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    import lite_acceptance as acceptance
    inputs, work = Path(args.inputs), Path(args.work)
    request = json.loads((inputs / "research.json").read_text())
    work.mkdir(parents=True, exist_ok=True)
    root = work / "evaluator"
    env = acceptance.clean_env(work / "home")
    acceptance._git(["clone", "-q", str(inputs / "release.bundle"), str(root)], work, env)
    acceptance._git(["checkout", "-q", "--detach", request["commit"]], root, env)
    python, installed = acceptance.install(root, work, False)
    if not python:
        raise RuntimeError(installed["detail"])
    # Fetch only shared scorer assets. The declared research reference is mounted separately.
    subprocess.run([python, "fetch_assets.py", "--mode", "synthetic"], cwd=root, env=env, check=True, timeout=3600)
    if request.get("reference_archive"):
        # Archive parsing stays inside the bounded runtime, away from web credentials.
        sys.path.insert(0, str(root))
        from quality_checks import extract_archive
        reference = work / "reference-data"
        expanded = extract_archive(inputs / "reference", reference, max_bytes=request["reference_expanded_bytes"])
        request["reference_archive_sha256"] = request["reference_sha256"]
        request["reference_sha256"] = expanded["sha256"]
        request["_reference_directory"] = str(reference)
    report = check(root, inputs, args.output, python, request=request)
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
