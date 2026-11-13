"""Acceptance checks for a Lite evaluator. Standard library only.

The application imports the validation helpers. The same file runs inside the
build runtime in two modes:

  check  — in the coding agent's workspace, to test work in progress.
  clone  — in a clean runtime, from a fresh clone of the candidate commit.

A passing workspace check is not the readiness test. Only the clone run counts.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time

LOCK_FORMAT = "bold.autokaggle.lite.evaluator.lock.v1"
TRUSTED = ("evaluate.py", "fetch_assets.py", "run.py", "gym_adapter.py", "quality_checks.py")
GENERATED = ("README.md", "evaluation.yaml", "contract.json", ".gitignore")
MAX_FILE, MAX_TOTAL, MAX_FILES = 2 * 1024 * 1024, 10 * 1024 * 1024, 200
REQUIREMENT = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?(?:\[[A-Za-z0-9,._-]+\])?==[A-Za-z0-9][A-Za-z0-9.!+_-]*")
MODULE = re.compile(r"[A-Za-z_]\w*")
IGNORE = "assets/\nresults*.json\n.venv/\n__pycache__/\n*.pyc\n"


def sha256(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def collect(root, spec):
    """Return (files, errors): the agent-authored files that may be published."""
    root = Path(root)
    files, errors, total = {}, [], 0
    reserved = set(TRUSTED) | set(GENERATED) | {"evaluator.lock.json", "check.py"}
    candidates = [p for p in sorted(root.glob("*.py")) if p.name not in reserved]
    candidates += [root / name for name in ("requirements.lock", "assets.json", "NOTES.md", "quality.json", "coverage.json") if (root / name).exists() or (root / name).is_symlink()]
    for folder in ("fixtures", "tests"):
        if (root / folder).is_dir() and not (root / folder).is_symlink():
            candidates += [p for p in sorted((root / folder).rglob("*")) if not p.is_dir() or p.is_symlink()]
    for path in candidates:
        name = path.relative_to(root).as_posix()
        if path.is_symlink() or not path.is_file():
            errors.append(f"{name}: links and special files cannot be published.")
            continue
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        size = path.stat().st_size
        if size > MAX_FILE:
            errors.append(f"{name}: larger than 2 MiB. Declare large inputs in assets.json and keep fixtures small.")
            continue
        total += size
        files[name] = path.read_bytes()
    if len(files) > MAX_FILES or total > MAX_TOTAL:
        errors.append("The evaluator has too many or too large files. Keep at most 200 files and 10 MiB.")
    return files, errors


def parse_requirements(data):
    lines = []
    for raw in data.decode("utf-8", errors="strict").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if not REQUIREMENT.fullmatch(line):
            raise ValueError(f"requirements.lock: '{raw.strip()[:80]}' is not a pinned name==version requirement.")
        lines.append(line)
    if len(lines) > 200:
        raise ValueError("requirements.lock: at most 200 pinned packages.")
    return lines


def parse_assets(data):
    assets = json.loads(data)
    if not isinstance(assets, list) or len(assets) > 50:
        raise ValueError("assets.json: use a list of at most 50 assets.")
    seen = set()
    for asset in assets:
        if not isinstance(asset, dict):
            raise ValueError("assets.json: each asset must be an object.")
        local = asset.get("source") == "local"
        required = {"path", "source", "sha256", "bytes", "mode"} if local else {"path", "url", "sha256", "bytes"}
        if set(asset) != required or (local and asset["mode"] != "research"):
            raise ValueError("assets.json: use path, url, sha256, bytes; or path, source=local, sha256, bytes, mode=research.")
        path = asset["path"]
        if (not isinstance(path, str) or not path.startswith("assets/") or ".." in Path(path).parts
                or path.endswith("/") or not re.fullmatch(r"[A-Za-z0-9._/-]{8,200}", path) or path in seen):
            raise ValueError("assets.json: asset paths must be distinct plain paths under assets/.")
        seen.add(path)
        if not local and (not isinstance(asset["url"], str) or not re.fullmatch(r"https://[^\s\"'<>]{4,1900}", asset["url"])):
            raise ValueError(f"assets.json: {path} needs an https URL.")
        if not isinstance(asset["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", asset["sha256"]):
            raise ValueError(f"assets.json: {path} needs a SHA-256 digest.")
        if type(asset["bytes"]) is not int or not 0 < asset["bytes"] <= (1024 if local else 20) * 1024 ** 3:
            raise ValueError(f"assets.json: {path} needs its size in bytes.")
    return assets


def parse_expected(data, files):
    expected = json.loads(data)
    if not isinstance(expected, dict) or set(expected) - {"tolerance", "cases"} or not isinstance(expected.get("cases"), dict):
        raise ValueError("fixtures/expected.json: use tolerance and cases.")
    tolerance = expected.get("tolerance", 1e-9)
    if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)) or not 0 <= tolerance <= 1e-6:
        raise ValueError("fixtures/expected.json: tolerance must be between 0 and 1e-6.")
    cases = expected["cases"]
    if set(cases) != {"valid", "wrong", "invalid"}:
        raise ValueError("fixtures/expected.json: define exactly the valid, wrong, and invalid cases.")
    for name, case in cases.items():
        if not isinstance(case, dict) or not isinstance(case.get("artifact"), str) or not isinstance(case.get("basis"), str) or len(case["basis"].strip()) < 20:
            raise ValueError(f"fixtures/expected.json: {name} needs an artifact path and a written basis.")
        if not case["artifact"].startswith("fixtures/") or case["artifact"] not in files:
            raise ValueError(f"fixtures/expected.json: {name} artifact must be a file under fixtures/.")
        if name == "invalid":
            if set(case) != {"artifact", "basis"}:
                raise ValueError("fixtures/expected.json: the invalid case has only artifact and basis.")
            continue
        score = case.get("expected_score")
        if set(case) != {"artifact", "basis", "expected_score"} or isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score):
            raise ValueError(f"fixtures/expected.json: {name} needs a finite expected_score.")
    if len({case["artifact"] for case in cases.values()}) != 3:
        raise ValueError("fixtures/expected.json: the three cases need different artifacts.")
    return {"tolerance": float(tolerance), "cases": cases}


def imported_modules(source):
    names = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call) and (getattr(node.func, "id", "") in {"__import__", "exec", "eval", "import_module", "run_path", "run_module"}
                                             or getattr(node.func, "attr", "") in {"import_module", "run_path", "run_module"}):
            names.add("<dynamic import or execution>")
    return names


def check_contributions(files, spec):
    """Return a list of problems in the agent-authored files. Empty means structurally acceptable."""
    errors = []
    adapter = spec["adapter"]
    required = ["requirements.lock", "assets.json", "fixtures/expected.json", "fixtures/check_expected.py"]
    if not adapter["packaged"]:
        required.append(adapter["module"] + ".py")
    if spec.get("loader"):
        required.append(spec["loader"].split(":")[0] + ".py")
    errors += [f"{name}: required file is missing." for name in required if name not in files]
    for name, data in files.items():
        if name.endswith(".py"):
            try:
                ast.parse(data.decode("utf-8"))
            except (SyntaxError, UnicodeDecodeError, ValueError) as exc:
                errors.append(f"{name}: not valid Python ({str(exc)[:120]}).")
    for name, parser in (("requirements.lock", parse_requirements), ("assets.json", parse_assets)):
        if name in files:
            try:
                parser(files[name])
            except (ValueError, UnicodeDecodeError) as exc:
                errors.append(str(exc) if str(exc).startswith(name) else f"{name}: {str(exc)[:160]}")
    if "fixtures/expected.json" in files:
        try:
            parse_expected(files["fixtures/expected.json"], files)
        except (ValueError, UnicodeDecodeError) as exc:
            errors.append(str(exc) if str(exc).startswith("fixtures/") else f"fixtures/expected.json: {str(exc)[:160]}")
    if "fixtures/check_expected.py" in files:
        try:
            used = imported_modules(files["fixtures/check_expected.py"].decode("utf-8"))
            forbidden = sorted(used & set(spec["independent_forbidden"]))
            if forbidden:
                errors.append("fixtures/check_expected.py: the expected scores must be calculated without the evaluator code. Remove: " + ", ".join(forbidden) + ".")
        except (SyntaxError, UnicodeDecodeError, ValueError):
            pass
    return errors


def lock_document(spec, hashes):
    return {"format": LOCK_FORMAT, "evaluator_version": spec["evaluator_version"], "problem_id": spec["problem_id"],
            "contract_version": spec["contract_version"], "contract_sha256": spec["contract_sha256"],
            "metric": spec["metric"], "direction": spec["direction"], "artifact_type": spec["artifact_type"],
            "adapter": spec["adapter"]["entrypoint"], "loader": spec.get("loader"),
            "repository": spec.get("repository") or "local:evaluator-release", "files": dict(sorted(hashes.items()))}


def _run(argv, cwd, timeout, env):
    started = time.monotonic()
    try:
        done = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout, errors="replace")
        return done.returncode, done.stdout, done.stderr, round(time.monotonic() - started, 2)
    except subprocess.TimeoutExpired as exc:
        text = lambda value: value.decode(errors="replace") if isinstance(value, bytes) else (value or "")
        return None, text(exc.stdout), text(exc.stderr) + f"\nStopped after {timeout} seconds.", round(time.monotonic() - started, 2)


def _tail(text, limit=1500):
    text = text.strip()
    return text if len(text) <= limit else "…" + text[-limit:]


def _last_json(text):
    for line in reversed(text.strip().splitlines()):
        try:
            value = json.loads(line)
            if isinstance(value, dict):
                return value
        except ValueError:
            continue
    return None


def run_cases(root, python, spec, env):
    """Run the independent calculation and the three scoring cases. Return test records."""
    root = Path(root)
    tests = []

    def record(name, passed, detail, **extra):
        tests.append({"name": name, "passed": bool(passed), "detail": detail[:2000], **extra})
        return passed

    files = {p.relative_to(root).as_posix(): b"" for p in (root / "fixtures").rglob("*") if p.is_file()}
    try:
        expected = parse_expected((root / "fixtures/expected.json").read_bytes(), files)
    except (OSError, ValueError) as exc:
        record("expected scores", False, str(exc))
        return tests
    tolerance, cases = expected["tolerance"], expected["cases"]
    contract = json.loads((root / "contract.json").read_text())
    limit = contract["contract"]["total_timeout_seconds"] + 120
    close = lambda a, b: math.isclose(a, b, rel_tol=tolerance, abs_tol=tolerance)

    code, out, err, seconds = _run([python, "fixtures/check_expected.py"], root, limit, env)
    calculated = _last_json(out) if code == 0 else None
    ok = bool(calculated) and all(isinstance(calculated.get(k), (int, float)) and not isinstance(calculated.get(k), bool)
                                   and close(calculated[k], cases[k]["expected_score"]) for k in ("valid", "wrong"))
    record("independent calculation", ok,
           "The separate calculation reproduced both declared expected scores." if ok else
           "The separate calculation did not reproduce the declared expected scores. " + _tail(err or out),
           calculated={k: calculated.get(k) for k in ("valid", "wrong")} if calculated else None,
           declared={k: cases[k]["expected_score"] for k in ("valid", "wrong")}, seconds=seconds)

    observed = {}
    for name in ("valid", "wrong"):
        output = root / f"results.{name}.json"
        output.unlink(missing_ok=True)
        mode = ["--mode", "synthetic"] if (root / "quality.json").is_file() else []
        code, out, err, seconds = _run([python, "evaluate.py", "--artifact", cases[name]["artifact"], "--output", output.name, *mode], root, limit, env)
        summary = _last_json(out)
        fitness = summary.get("fitness") if summary else None
        results = json.loads(output.read_text()) if output.is_file() else {}
        complete = (code == 0 and isinstance(fitness, (int, float)) and not isinstance(fitness, bool)
                    and summary.get("failed") == 0 and len(results.get("results", [])) == len(contract["seeds"]))
        ok = complete and close(fitness, cases[name]["expected_score"])
        observed[name] = fitness if complete else None
        detail = (f"Observed {fitness!r}; expected {cases[name]['expected_score']!r}." if complete else
                  "The scoring command did not complete every seed. " + _tail(err or out))
        record(f"{name} example", ok, detail, artifact=cases[name]["artifact"], expected=cases[name]["expected_score"],
               observed=fitness if complete else None, exit_code=code, seconds=seconds, basis=cases[name]["basis"][:600])
        output.unlink(missing_ok=True)
    if observed.get("valid") is not None and observed.get("wrong") is not None:
        worse = observed["wrong"] < observed["valid"] if spec["direction"] == "maximize" else observed["wrong"] > observed["valid"]
        record("wrong example scores worse", worse, f"valid {observed['valid']!r}, wrong {observed['wrong']!r}, direction {spec['direction']}.")

    output = root / "results.invalid.json"
    output.unlink(missing_ok=True)
    mode = ["--mode", "synthetic"] if (root / "quality.json").is_file() else []
    code, out, err, seconds = _run([python, "evaluate.py", "--artifact", cases["invalid"]["artifact"], "--output", output.name, *mode], root, limit, env)
    summary = _last_json(out)
    rejected = code not in (0, None) and (summary is None or summary.get("completed") == 0)
    record("invalid artifact rejected", rejected,
           "The invalid artifact received no completed score. " + (err.strip().splitlines() or [""])[-1][:400] if rejected else
           "The invalid artifact was not rejected. " + _tail(out or err, 600), artifact=cases["invalid"]["artifact"],
           exit_code=code, seconds=seconds, basis=cases["invalid"]["basis"][:600])
    output.unlink(missing_ok=True)
    if (root / "quality.json").is_file():
        target = root / "results.coverage.json"
        target.unlink(missing_ok=True)
        code, out, err, seconds = _run([python, "quality_checks.py", str(target)], root, limit, env)
        coverage = json.loads(target.read_text()) if target.is_file() else {}
        passed = code == 0 and coverage.get("passed") is True
        errors = coverage.get("errors", [])
        failures = "\n".join(str(error)[-1500:] for error in errors[:3]) if isinstance(errors, list) else ""
        missing = [key for key, value in coverage.get("requirements", {}).items() if value is not True]
        detail = ("Executed the tests mapped to each requirement." if passed else
                  ("Required tests failed: " + failures if failures else
                   "Requirements without passing tests: " + ", ".join(missing[:20]) if missing else
                   _tail(err or out or json.dumps(coverage))))
        record("contract coverage", passed, detail,
               coverage=coverage, seconds=seconds)
        target.unlink(missing_ok=True)
    return tests


def _git(args, cwd, env=None):
    done = subprocess.run(["git", "-c", "safe.directory=*", "-c", "advice.detachedHead=false", *args], cwd=cwd, env=env,
                          capture_output=True, text=True, timeout=300)
    if done.returncode:
        raise RuntimeError("git " + args[0] + " failed: " + _tail(done.stderr, 400))
    return done.stdout.strip()


def clean_env(home, extra_path=None):
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    path = os.pathsep.join(filter(None, [extra_path, os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")]))
    return {"PATH": path, "HOME": str(home), "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_INPUT": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}


def install(root, work, allow_sdist):
    """Create a new virtual environment from requirements.lock only. Return (python, record)."""
    venv = Path(work) / "venv"
    env = clean_env(Path(work) / "home")
    code, out, err, seconds = _run([sys.executable, "-m", "venv", str(venv)], work, 300, env)
    if code != 0:
        return None, {"name": "fresh environment", "passed": False, "detail": "Could not create a virtual environment. " + _tail(err), "seconds": seconds}
    python = str(venv / ("Scripts" if os.name == "nt" else "bin") / "python")
    pins = parse_requirements((Path(root) / "requirements.lock").read_bytes())
    if pins:
        command = [python, "-m", "pip", "install", "--no-input", "-r", "requirements.lock"] + ([] if allow_sdist else ["--only-binary=:all:"])
        code, out, err, more = _run(command, root, 1800, env)
        seconds += more
        if code != 0:
            return None, {"name": "fresh environment", "passed": False, "seconds": seconds,
                          "detail": "The pinned dependencies did not install in a new environment. " + _tail(err)}
    code, frozen, _, _ = _run([python, "-m", "pip", "freeze", "--all"], root, 120, env)
    return python, {"name": "fresh environment", "passed": True, "seconds": seconds,
                    "detail": f"Installed {len(pins)} pinned packages into a new virtual environment.",
                    "installed": sorted(frozen.split())[:400] if code == 0 else []}


def clone_run(source, ref, work, spec, allow_sdist):
    """Clone the candidate, install only what it declares, fetch its assets, and score its fixtures."""
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    report = {"mode": "clone", "ref": ref, "python": platform.python_version(), "platform": platform.platform(), "tests": []}
    tests = report["tests"]
    root = work / "evaluator"
    try:
        _git(["clone", "-q", str(source), str(root)], work, clean_env(work / "home"))
        _git(["checkout", "-q", "--detach", ref], root, clean_env(work / "home"))
        head = _git(["rev-parse", "HEAD"], root)
        tests.append({"name": "fresh clone", "passed": head == ref, "detail": f"Checked out {head}."})
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        tests.append({"name": "fresh clone", "passed": False, "detail": str(exc)[:1500]})
        return report
    files, errors = collect(root, spec)
    errors += check_contributions(files, spec)
    lock = json.loads((root / "evaluator.lock.json").read_text())
    changed = [name for name, digest in lock["files"].items() if not (root / name).is_file() or sha256(root / name) != digest]
    if errors or changed:
        tests.append({"name": "release contents", "passed": False, "detail": "; ".join(errors + ["changed or missing: " + n for n in changed])[:1500]})
        return report
    tests.append({"name": "release contents", "passed": True, "detail": f"{len(lock['files'])} files match the release lock."})
    python, record = install(root, work, allow_sdist)
    tests.append(record)
    if not python:
        return report
    env = clean_env(work / "home", str(Path(python).parent))
    assets = parse_assets((root / "assets.json").read_bytes())
    code, out, err, seconds = _run([python, "fetch_assets.py", "--mode", "synthetic"], root, 3600, env)
    tests.append({"name": "declared assets", "passed": code == 0, "seconds": seconds,
                  "detail": f"Retrieved and verified {len(assets)} declared assets." if code == 0 else "A declared asset could not be retrieved or verified. " + _tail(err or out)})
    if code != 0:
        return report
    tests += run_cases(root, python, spec, env)
    dirty = _git(["status", "--porcelain", "--untracked-files=no"], root)
    tests.append({"name": "checkout unchanged", "passed": not dirty, "detail": "Scoring left tracked files unchanged." if not dirty else "Scoring changed tracked files: " + dirty[:400]})
    return report


def workspace_check(root, spec):
    """Agent-side check: validate, commit a scratch snapshot, and score the fixtures in the current environment."""
    root = Path(root)
    report = {"mode": "check", "tests": []}
    files, errors = collect(root, spec)
    errors += check_contributions(files, spec)
    if errors:
        report["tests"].append({"name": "required files", "passed": False, "detail": "\n".join(errors)})
        return report
    report["tests"].append({"name": "required files", "passed": True, "detail": f"{len(files)} files are acceptable for publication."})
    (root / ".gitignore").write_text(IGNORE + "BUILD_TASK.md\nBUILD_REPORT.json\nbuild.json\nsources/\ncheck.py\n")
    tracked = [*files, *[n for n in TRUSTED + ("contract.json", ".gitignore") if (root / n).is_file()]]
    (root / "evaluator.lock.json").write_text(json.dumps(lock_document(spec, {n: sha256(root / n) for n in tracked}), indent=2) + "\n")
    env = clean_env(root / ".check-home")
    env.update(GIT_AUTHOR_NAME="evaluator build", GIT_AUTHOR_EMAIL="build@localhost", GIT_COMMITTER_NAME="evaluator build", GIT_COMMITTER_EMAIL="build@localhost")
    try:
        if not (root / ".git").exists():
            _git(["init", "-q"], root, env)
        _git(["read-tree", "--empty"], root, env)
        _git(["add", "-f", "--", *tracked, "evaluator.lock.json"], root, env)
        _git(["commit", "-q", "--allow-empty", "-m", "workspace check"], root, env)
    except (RuntimeError, OSError) as exc:
        report["tests"].append({"name": "scratch commit", "passed": False, "detail": str(exc)[:800]})
        return report
    env = clean_env(root / ".check-home", str(Path(sys.executable).parent))
    code, out, err, _ = _run([sys.executable, "fetch_assets.py", "--mode", "synthetic"], root, 3600, env)
    report["tests"].append({"name": "declared assets", "passed": code == 0, "detail": "Assets verified." if code == 0 else _tail(err or out)})
    if code == 0:
        report["tests"] += run_cases(root, sys.executable, spec, env)
    return report


def main():
    parser = argparse.ArgumentParser(description="Check a Lite evaluator.")
    sub = parser.add_subparsers(dest="mode", required=True)
    check = sub.add_parser("check")
    check.add_argument("--workspace", default=".")
    clone = sub.add_parser("clone")
    for name in ("--source", "--ref", "--work", "--spec", "--report"):
        clone.add_argument(name, required=True)
    clone.add_argument("--allow-sdist", action="store_true")
    args = parser.parse_args()
    if args.mode == "check":
        spec = json.loads((Path(args.workspace) / "build.json").read_text())
        report = workspace_check(args.workspace, spec)
    else:
        spec = json.loads(Path(args.spec).read_text())
        report = clone_run(args.source, args.ref, args.work, spec, args.allow_sdist)
    report["passed"] = bool(report["tests"]) and all(test["passed"] for test in report["tests"])
    if args.mode == "clone":
        Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
    for test in report["tests"]:
        print(("PASS  " if test["passed"] else "FAIL  ") + test["name"] + " — " + test["detail"][:900])
    print("RESULT: " + ("all checks passed" if report["passed"] else "not passing"))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
