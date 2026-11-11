"""Score one artifact with this pinned evaluator release. Standard library only.

    python evaluate.py --artifact PATH [--output results.json]

Prints one JSON line with the fitness and writes the per-seed result file.
Exit status: 0 complete, 2 no completed score, 1 the release or inputs are not usable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def stop(message):
    print("evaluate: " + message, file=sys.stderr)
    raise SystemExit(1)


def explain(record, manifest, contract):
    """Repeat one failed seed with its output visible. The runner itself discards worker output."""
    if record["status"] == "timeout":
        print(f"evaluate: seed {record['seed']} exceeded the time limit.", file=sys.stderr)
        return
    if record["status"] == "truncated":
        print(f"evaluate: seed {record['seed']} stopped before completion ({record.get('end_reason', 'truncated')}).", file=sys.stderr)
        return
    with tempfile.TemporaryDirectory(prefix="evaluate-") as temporary:
        job, target = Path(temporary) / "job.json", Path(temporary) / "result.json"
        job.write_text(json.dumps({"seed": record["seed"], "manifest": manifest, "contract": contract}))
        try:
            done = subprocess.run([sys.executable, str(ROOT / "run.py"), "--worker", str(job), str(target)], cwd=ROOT,
                                  capture_output=True, text=True, errors="replace", timeout=contract["timeout_seconds"])
            cause = done.stderr.strip()[-2000:] or "The adapter returned an invalid record."
        except subprocess.TimeoutExpired:
            cause = "The repeated seed exceeded the time limit."
    print(f"evaluate: seed {record['seed']} failed. Cause:\n{cause}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Score one artifact under the pinned evaluation contract.")
    parser.add_argument("--artifact", required=True, help="Prediction file, policy, or checkpoint in the declared format.")
    parser.add_argument("--output", default="results.json", help="Where to write the per-seed result file.")
    parser.add_argument("--artifact-url", default="", help="Where collaborators can retrieve this artifact.")
    parser.add_argument("--resources", default="Not recorded.", help="Hardware and time used to produce the artifact.")
    parser.add_argument("--provenance", default="Not recorded.", help="Training code, data versions, and seeds.")
    args = parser.parse_args()

    try:
        lock = json.loads((ROOT / "evaluator.lock.json").read_text())
        assets = json.loads((ROOT / "assets.json").read_text())
        contract = json.loads((ROOT / "contract.json").read_text())
    except (OSError, ValueError):
        stop("this is not a complete evaluator release. Clone the pinned release again.")
    for name, expected in lock["files"].items():
        if not (ROOT / name).is_file() or digest(ROOT / name) != expected:
            stop(f"{name} is missing or differs from the release. Check out the pinned release again.")
    for asset in assets:
        if not (ROOT / asset["path"]).is_file() or digest(ROOT / asset["path"]) != asset["sha256"]:
            stop(f"{asset['path']} is missing or does not match its SHA-256. Run: python fetch_assets.py")
    artifact = Path(args.artifact).resolve()
    if not artifact.is_file():
        stop(f"{args.artifact} is not a file.")
    try:
        revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        stop("run this from a Git clone of the evaluator release, so the result records its exact revision.")

    manifest = {"format": "bold.autokaggle.lite.submission.v1", "challenge_version": lock["contract_version"],
                "contract_sha256": lock["contract_sha256"], "code_repository": lock["repository"], "code_revision": revision,
                "code_directory": str(ROOT), "artifact_url": args.artifact_url or "local:" + artifact.name,
                "artifact_path": str(artifact), "artifact_sha256": digest(artifact),
                "dependencies_path": str(ROOT / "requirements.lock"), "dependencies_sha256": digest(ROOT / "requirements.lock"),
                "resources": args.resources, "training_provenance": args.provenance,
                "evaluator_version": lock["evaluator_version"]}
    if lock.get("loader"):
        manifest["policy_loader"] = lock["loader"]

    sys.path.insert(0, str(ROOT))
    import run as runner
    with tempfile.TemporaryDirectory(prefix="evaluate-") as temporary:
        manifest_path = Path(temporary) / "manifest.json"
        manifest_path.write_text(json.dumps(manifest))
        try:
            result = runner.run(ROOT, manifest_path, args.output)
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            stop(str(exc))
    summary = result["summary"]
    failed = [record for record in result["results"] if record["status"] != "completed"]
    if failed:
        explain(failed[0], result["manifest"], contract["contract"])
    # With the zero failure rule the runner reports 0.0 even when no seed completed. That is not a measured fitness.
    scored = summary["status"] == "complete" and summary["completed"] > 0
    print(json.dumps({"fitness": summary["score"] if scored else None, "metric": summary["metric"], "direction": lock["direction"],
                      "status": summary["status"] if scored or summary["status"] != "complete" else "no_completed_seed",
                      "completed": summary["completed"], "failed": summary["failed"],
                      "seeds": len(result["results"]), "contract_version": lock["contract_version"],
                      "evaluator_version": lock["evaluator_version"], "evaluator_revision": revision,
                      "results": str(Path(args.output).resolve())}))
    raise SystemExit(0 if scored else 2)


if __name__ == "__main__":
    main()
