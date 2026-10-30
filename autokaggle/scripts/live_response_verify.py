"""Verify incremental SPOCK replies and bounded repair with real model calls."""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import tempfile

from dotenv import dotenv_values
from fastapi.testclient import TestClient

MESSAGES = [
    "I study the long-term stability of compact three-planet systems. Long numerical simulations are expensive. Can we predict whether a system remains stable for one billion orbits of its innermost planet from its initial configuration? I want to use the SPOCK 2.0 dataset for this challenge.",
    "Use the corrected SPOCK 2.0 dataset: https://zenodo.org/records/14327471. It contains simulated three-planet systems and their stability outcomes. I also have a flattened CSV called spock2_systems.csv, which I can upload through Data & checks. For this first test, limit the challenge to the systems in that file.",
    "Each example is one planetary system. Use the initial masses and orbital or position-and-velocity fields as inputs. The target is the released stable column. Return one probability of stability per system. Exclude both instability-time columns and all source identifiers from the inputs because they can reveal the answer. Please propose an explicit list of allowed columns for me to review.",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--report", type=Path, default=Path("autokaggle/test-results/response-live.json"))
    parser.add_argument("--inject-evidence-error", action="store_true",
                        help="Replace one real response excerpt to exercise automatic repair.")
    args = parser.parse_args()
    key = dotenv_values(args.env_file).get("OPENROUTER_API_KEY")
    if not key:
        raise SystemExit("The private OpenRouter key is unavailable.")
    os.environ.update(OPENAI_API_KEY=key, OPENAI_BASE_URL="https://openrouter.ai/api/v1",
                      AUTOKAGGLE_MODEL="openai/gpt-6.1-sol", AUTOKAGGLE_MODE="model",
                      AUTOKAGGLE_PRIVATE_MODE="0", AUTOKAGGLE_SMTP_PASSWORD="",
                      AUTOKAGGLE_GMAIL_REFRESH_TOKEN="")
    from autokaggle.app import create_app
    from autokaggle import conversation

    report = {"model": "openai/gpt-6.1-sol", "provider": "OpenRouter", "reasoning": "medium",
              "fault_injection_requested": args.inject_evidence_error, "fault_injected": False,
              "calls": [], "turns": [], "passed": False}
    original_provider = conversation._provider
    original_fail = conversation._fail
    injected = "This deliberately invalid excerpt was never supplied by the researcher."

    def capture(*provider_args, **provider_kwargs):
        result = original_provider(*provider_args, **provider_kwargs)
        report["calls"].append({"kind": provider_args[1],
                                "question_length": len(result.get("question_text", "")),
                                "requirement_count": len(result.get("requirements", []))})
        if args.inject_evidence_error and not report["fault_injected"] and provider_args[1] == "scope":
            result = copy.deepcopy(result)
            record = next((r for r in result.get("requirements", []) if r.get("status") == "recorded"), None)
            if record is not None:
                record["evidence"] = [injected]
                report["fault_injected"] = True
        return result

    def failure(state, exc, can_retry=True):
        # Validation messages are fixed internal strings. Never retain a provider exception body.
        report["last_failure"] = {"type": type(exc).__name__, "code": getattr(exc, "code", None)}
        if type(exc) is ValueError:
            report["last_failure"]["validation_reason"] = str(exc)
        return original_fail(state, exc, can_retry)

    conversation._provider = capture
    conversation._fail = failure
    app = None
    try:
        with tempfile.TemporaryDirectory(prefix="autokaggle-response-live-") as directory:
            app = create_app(Path(directory))
            with TestClient(app) as client:
                response = client.post("/api/projects", json={"title": "SPOCK response validation check"})
                response.raise_for_status()
                root = "/api/projects/" + response.json()["id"]
                client.patch(root + "/setup", json={"organizer_email": "response-check@example.org"}).raise_for_status()
                for index, message in enumerate(MESSAGES, 1):
                    print(f"Checking incremental SPOCK turn {index}", flush=True)
                    reply = client.post(root + "/conversation/messages", json={"message": message, "request_id": f"response-live-{index}"})
                    reply.raise_for_status()
                    view = reply.json()
                    report["turns"].append({"turn": index, "status": view["status"], "question": view.get("current_question"),
                                            "error": view.get("error")})
                    if view["status"] != "idle":
                        raise AssertionError("The live turn did not complete.")
                    stored = app.state.store.get(response.json()["id"], client.cookies["autokaggle_owner"])
                    assert injected not in json.dumps(stored["conversation"]["items"])
                    before = stored.get("_model_calls", 0)
                    repeated = client.post(root + "/conversation/messages", json={"message": message, "request_id": f"response-live-{index}"})
                    repeated.raise_for_status()
                    stored = app.state.store.get(response.json()["id"], client.cookies["autokaggle_owner"])
                    assert stored.get("_model_calls", 0) == before
                report["model_calls"] = stored.get("_model_calls", 0)
                report["validation_diagnostics"] = stored["conversation"].get("_response_diagnostics", [])
                report["saved_user_messages"] = sum(m["role"] == "user" for m in stored["conversation"]["messages"])
                assert report["saved_user_messages"] == len(MESSAGES)
                if args.inject_evidence_error:
                    assert report["fault_injected"] and report["model_calls"] >= len(MESSAGES) + 1
                report["passed"] = True
    finally:
        if app:
            app.state.pool.shutdown(wait=True)
        conversation._provider = original_provider
        conversation._fail = original_fail
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({key: report.get(key) for key in ("passed", "model_calls", "fault_injected", "last_failure")}), flush=True)


if __name__ == "__main__":
    main()
