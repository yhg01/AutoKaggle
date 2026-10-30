"""Check scope acceptance with live OpenRouter replies and an isolated local store."""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import tempfile

from dotenv import dotenv_values
from fastapi.testclient import TestClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=Path("autokaggle/test-results/scope-live.json"))
    args = parser.parse_args()
    key = dotenv_values(".env").get("OPENROUTER_API_KEY")
    if not key:
        raise SystemExit("The private OpenRouter key is unavailable.")
    os.environ.update(OPENAI_API_KEY=key, OPENAI_BASE_URL="https://openrouter.ai/api/v1",
                      AUTOKAGGLE_MODEL="openai/gpt-6.1-sol", AUTOKAGGLE_MODE="model",
                      AUTOKAGGLE_PRIVATE_MODE="0", AUTOKAGGLE_SMTP_PASSWORD="",
                      AUTOKAGGLE_GMAIL_REFRESH_TOKEN="")
    from autokaggle.app import create_app
    from autokaggle import conversation

    report = {"provider": "OpenRouter", "model": "openai/gpt-6.1-sol",
              "reasoning": "medium", "checks": {}, "questions": []}
    provider = conversation._provider
    def capture_provider(*provider_args, **provider_kwargs):
        result = provider(*provider_args, **provider_kwargs)
        report["last_model_result"] = copy.deepcopy(result)
        return result
    conversation._provider = capture_provider
    with tempfile.TemporaryDirectory(prefix="autokaggle-scope-live-") as directory:
        app = create_app(Path(directory))
        with TestClient(app) as client:
            response = client.post("/api/projects", json={"title": "Scope acceptance verification"})
            response.raise_for_status()
            root = "/api/projects/" + response.json()["id"]
            client.patch(root + "/setup", json={"organizer_email": "scope-check@example.org"}).raise_for_status()

            def post(path, payload):
                result = client.post(root + "/conversation/" + path, json=payload)
                result.raise_for_status()
                view = result.json()
                if view["status"] != "idle":
                    report.update(passed=False, error=view.get("error"))
                    args.report.parent.mkdir(parents=True, exist_ok=True)
                    args.report.write_text(json.dumps(report, indent=2) + "\n")
                    raise AssertionError(view.get("error"))
                return view

            def message(text, request_id):
                print("Checking " + request_id, flush=True)
                view = post("messages", {"message": text, "request_id": request_id})
                question = view.get("current_question")
                if question:
                    assert question.get("requirement_id") and question.get("why")
                    report["questions"].append(question)
                return view

            first = message(
                "I want to predict planetary-system stability from short integrations to reduce simulation cost. "
                "Each result is the probability of a collision or ejection within one billion orbits. "
                "This is a synthetic pilot inspired by SPOCK 2.0; the simulation source still needs to be selected.",
                "scope-live-brief")
            report["checks"]["focused_question_with_consequence"] = bool(first.get("current_question"))
            scope = {"field": "methodology", "summary": "Choose a method within the fixed platform limits. External data and services are not allowed.",
                     "resolutions": [
                         {"requirement_id": "methods", "mode": "delegated", "detail": "Choose a method within the fixed runner, compute, and data access limits."},
                         {"requirement_id": "resources", "mode": "confirmed", "detail": "External data and services are not allowed."}],
                     "request_id": "scope-live-accept"}
            accepted = post("scope", scope)
            item = next(x for x in accepted["checklist"] if x["id"] == "methodology")
            assert item["understanding"]["completed"] == item["understanding"]["total"]
            report["checks"]["scope_resolves_card"] = True
            before_scope = copy.deepcopy(item["scope"])
            replayed = post("scope", scope)
            assert next(x for x in replayed["checklist"] if x["id"] == "methodology")["scope"] == before_scope
            report["checks"]["acceptance_retry_is_idempotent"] = True

            followup = message("The pilot will use independently generated synthetic planetary systems. Keep the agreed method and resource policy.", "scope-live-add-detail")
            item = next(x for x in followup["checklist"] if x["id"] == "methodology")
            assert item["understanding"]["completed"] == item["understanding"]["total"]
            assert not item["scope"].get("stale")
            report["checks"]["new_detail_preserves_accepted_scope"] = True

            changed = message("Correction to the agreed resource policy: external datasets are now allowed, but external services remain prohibited.", "scope-live-correction")
            item = next(x for x in changed["checklist"] if x["id"] == "methodology")
            assert item["scope"].get("stale") or any(x.get("requirement_id") == "resources" and x.get("stale") for x in item["scope"]["resolutions"])
            methods = next(x for x in item["requirements"] if x["id"] == "methods")
            assert methods["status"] == "delegated"
            report["checks"]["correction_reopens_only_affected_scope"] = True
            report["model_calls"] = app.state.store.get(response.json()["id"], client.cookies["autokaggle_owner"]).get("_model_calls", 0)
        app.state.pool.shutdown(wait=True)
    report["passed"] = all(report["checks"].values())
    report.pop("last_model_result", None)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
