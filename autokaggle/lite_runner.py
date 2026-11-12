"""Portable local evaluation runner. This runs trusted lab code, not a sandbox."""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def callable_at(entry):
    module, name = entry.split(":", 1)
    return getattr(importlib.import_module(module), name)


def validate_record(record, seed, metric):
    if not isinstance(record, dict) or record.get("seed") != seed:
        raise ValueError("Result seed does not match the assigned seed.")
    if record.get("status") not in {"completed", "failed", "timeout", "truncated"}:
        raise ValueError("Result status must be completed, failed, timeout, or truncated.")
    if type(record.get("steps")) is not int or record["steps"] < 0:
        raise ValueError("Each result needs a nonnegative integer step count.")
    reason = record.get("end_reason")
    if reason is not None:
        if reason not in {"terminated", "evaluation_horizon", "environment_truncated", "step_limit"}:
            raise ValueError("Unknown episode end reason.")
        expected = "completed" if reason in {"terminated", "evaluation_horizon"} else "truncated"
        if record["status"] != expected:
            raise ValueError("Episode end reason conflicts with its status.")
    if record["status"] == "completed":
        score = record.get("score")
        if isinstance(score, bool) or not isinstance(score, (float, int)) or not math.isfinite(score):
            raise ValueError("A completed result needs a finite score.")
        if metric in {"success_rate", "accuracy"} and not 0 <= score <= 1:
            raise ValueError("Success or accuracy scores must be between zero and one.")
        if metric == "success_rate" and score not in (0, 1):
            raise ValueError("Episode success must be zero or one.")
        if metric in {"rmse", "mae"} and score < 0:
            raise ValueError("Error scores cannot be negative.")
    else:
        record["score"] = None
    return record


def summarize(records, contract):
    failed = sum(r["status"] != "completed" for r in records)
    metric = contract["metric"]
    if failed and contract["failure_policy"] == "fail_run":
        return {"status": "incomplete", "score": None, "metric": metric,
                "completed": len(records) - failed, "failed": failed}
    scores = [r["score"] if r["status"] == "completed" else 0.0 for r in records]
    return {"status": "complete", "score": sum(scores) / len(scores), "metric": metric,
            "completed": len(records) - failed, "failed": failed}


def run(package_dir, manifest_path, output_path):
    package_dir = Path(package_dir).resolve()
    contract_record = json.loads((package_dir / "contract.json").read_text())
    recorded_digest = contract_record.get("contract_sha256")
    unhashed = {k: v for k, v in contract_record.items() if k != "contract_sha256"}
    actual_digest = hashlib.sha256(json.dumps(unhashed, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    if actual_digest != recorded_digest:
        raise ValueError("The evaluation contract was changed. Obtain the current package.")
    for source, name in (("lite_runner.py", "run.py"), ("lite_gym_adapter.py", "gym_adapter.py")):
        if digest(package_dir / name) != contract_record.get("evaluator_files", {}).get(source):
            raise ValueError("A packaged evaluator file was changed. Rebuild the package through Lite.")
    contract, seeds = contract_record["contract"], contract_record["seeds"]
    manifest_path = Path(manifest_path).resolve()
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("challenge_version") != contract_record["version"]:
        raise ValueError("The manifest belongs to a different challenge version.")
    if manifest.get("contract_sha256") != actual_digest:
        raise ValueError("The manifest contract digest does not match the package.")
    code_directory = Path(manifest.get("code_directory", ".")).resolve()
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=code_directory, check=True,
        capture_output=True, text=True, timeout=10).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=code_directory,
        check=True, capture_output=True, text=True, timeout=10).stdout.strip()
    if dirty or revision != manifest.get("code_revision"):
        raise ValueError("Run the declared code commit with no changes to tracked files.")
    # Paths are local researcher choices. The web service never follows them.
    asset = Path(manifest.get("artifact_path", "")).resolve()
    if not asset.is_file() or digest(asset) != manifest.get("artifact_sha256"):
        raise ValueError("The local artifact does not match its SHA-256.")
    manifest["artifact_path"] = str(asset)
    for field in ("dependencies_path",):
        file = Path(manifest.get(field, "")).resolve()
        if not file.is_file() or digest(file) != manifest.get(field.replace("_path", "_sha256")):
            raise ValueError("The dependency lock does not match its SHA-256.")
        manifest[field] = str(file)
    records, diagnostics = [], {}
    total_started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="autokaggle-lite-") as temporary:
        temporary = Path(temporary)
        job = temporary / "job.json"
        for seed in seeds:
            target = temporary / "result.json"
            target.unlink(missing_ok=True)
            job.write_text(json.dumps({"seed": seed, "manifest": manifest, "contract": contract}))
            started = time.monotonic()
            record = {"seed": seed, "score": None, "steps": 0, "status": "failed"}
            remaining = contract["total_timeout_seconds"] - (started - total_started)
            if remaining <= 0:
                records.append({**record, "status": "timeout", "elapsed_seconds": 0.0})
                continue
            try:
                # The process timeout also covers environment reset/step and imports.
                error_log = temporary / "worker-error.txt"
                with error_log.open("wb") as errors:
                    process = subprocess.Popen([sys.executable, str(package_dir / "run.py"), "--worker", str(job), str(target)],
                        cwd=code_directory, stdout=subprocess.DEVNULL, stderr=errors,
                        start_new_session=os.name == "posix")
                try:
                    process.wait(timeout=min(contract["timeout_seconds"], remaining))
                except subprocess.TimeoutExpired:
                    if os.name == "posix":
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                    process.wait()
                    raise
                if process.returncode:
                    with error_log.open("rb") as errors:
                        errors.seek(max(0, error_log.stat().st_size - 2000))
                        diagnostics[str(seed)] = errors.read(2000).decode(errors="replace")
                    raise ValueError("The adapter did not complete.")
                record = validate_record(json.loads(target.read_text()), seed, contract["metric"])
            except subprocess.TimeoutExpired:
                record["status"] = "timeout"
            except (OSError, ValueError, TypeError, subprocess.SubprocessError):
                record["status"] = "failed"
            record["elapsed_seconds"] = round(time.monotonic() - started, 4)
            records.append(record)
    result = {"format": "bold.autokaggle.lite.results.v1", "challenge_version": contract_record["version"],
              "manifest": manifest, "results": records, "summary": summarize(records, contract),
              "evidence_level": "researcher_reported", "diagnostics": diagnostics}
    Path(output_path).write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    return result


def main():
    if len(sys.argv) == 4 and sys.argv[1] == "--worker":
        # Permit the local researcher repository and the packaged adapters.
        sys.path.insert(0, os.getcwd())
        job = json.loads(Path(sys.argv[2]).read_text())
        record = callable_at(job["contract"]["adapter_entrypoint"])(job["seed"], job["manifest"], job["contract"])
        Path(sys.argv[3]).write_text(json.dumps(record, allow_nan=False))
        return
    parser = argparse.ArgumentParser(description="Run the fixed internal evaluation contract on trusted local code.")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", default="results.json")
    args = parser.parse_args()
    result = run(Path(__file__).parent, args.manifest, args.output)
    print(json.dumps(result["summary"]))


if __name__ == "__main__":
    main()
