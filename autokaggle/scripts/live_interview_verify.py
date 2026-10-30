"""Verify the actual interview API with live OpenRouter calls and synthetic facts.

Run from the repository root. Keys stay in process memory; the temporary project
store is removed on exit. This check does not send email or run submitted code.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile

from dotenv import dotenv_values
from fastapi.testclient import TestClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--model", default="openai/gpt-6.1-sol")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    key = dotenv_values(args.env_file).get("OPENROUTER_API_KEY")
    if not key:
        raise SystemExit("OPENROUTER_API_KEY is missing from the supplied environment file.")
    os.environ.update(OPENAI_API_KEY=key, OPENAI_BASE_URL="https://openrouter.ai/api/v1",
                      AUTOKAGGLE_MODE="model", AUTOKAGGLE_MODEL=args.model)
    from autokaggle.app import create_app

    report = {"provider": "OpenRouter", "model": args.model,
              "reasoning": {"conversation": "medium", "draft": "high"}, "checks": []}
    with tempfile.TemporaryDirectory(prefix="autokaggle-interview-live-") as directory:
        app = create_app(Path(directory))
        with TestClient(app) as client:
            response = client.post("/api/projects", json={"title": "Synthetic demand interview"})
            response.raise_for_status()
            project_id = response.json()["id"]
            route = f"/api/projects/{project_id}/conversation"

            def action(name, request_id, message=None):
                print(f"Checking {request_id}...", flush=True)
                body = {"request_id": request_id}
                if message is not None:
                    body["message"] = message
                result = client.post(f"{route}/{name}", json=body)
                result.raise_for_status()
                view = result.json()
                assert view["status"] != "error", view.get("error")
                assert view["mode"] == "model"
                return view

            brief = (
                "We want to forecast next-day product demand to reduce waste at shops. "
                "One output is the number of units sold for one shop and product tomorrow. "
                "We have 20,000 private daily shop-product records from 2021 to 2025, "
                "with observed sales as labels and permission to use the records in this challenge. "
                "Keep time order and evaluate later dates; repeated records from the same shop exist. "
                "No labels have been published. Measure MAE in units; a 10% improvement would be useful. "
                "Any predictive method is allowed. I choose a code competition. "
                "The artifact is a Python prediction program. It runs once daily at 18:00 UTC, "
                "using only sales and prices known then, with no network, no GPU and no persistent state. "
                "The declared standard-library runner limits are suitable for this initial trial."
            )
            first = action("messages", "live-brief", brief)
            items = {item["id"]: item for item in first["checklist"]}
            for field in ("question", "task", "data", "methodology", "deployment"):
                assert items[field]["status"] in {"answered", "partial"}, field
                assert items[field]["value"], field
            question = first.get("current_question") or {}
            assert question.get("field") not in {"trial", "entry", "support", "review"}
            report["first_followup"] = question
            report["checks"].append("Multiple facts extracted; one targeted researcher question")

            baseline = (
                "Our strongest known reference is our internal seasonal-average algorithm, version 1.2. "
                "The internal report gives MAE 4.2 units on 2024 data. Its Python source is available "
                "and uses the standard library. It runs on one CPU in 10 seconds with 100 MiB RAM. "
                "It has not been reproduced through AutoKaggle, and we do not know whether it is SOTA."
            )
            second = action("messages", "live-reference", baseline)
            items = {item["id"]: item for item in second["checklist"]}
            assert items["difficulty"]["value"]
            assert "4.2" in items["difficulty"]["value"]
            report["checks"].append("Reported reference result retained without a reproduction claim")

            setup = action("messages", "live-setup", (
                "For one credible attempt, compute costs $120 and model tokens cost $15. "
                "I confirm five submissions per day. My organizer email is researcher@example.org."
            ))
            assert setup["setup"]["organizer_email"] == "researcher@example.org"
            assert setup["setup"]["daily_submission_limit"] == 5
            assert setup["setup"]["submissions_confirmed"]
            corrected = action("messages", "live-correction", "Change the compute cost from $120 to $180. Keep the model token cost at $15.")
            items = {item["id"]: item for item in corrected["checklist"]}
            assert "$180" in items["plan"]["value"]
            assert "$15" in items["plan"]["value"]
            assert "$120" not in items["plan"]["value"]
            report["checks"].append("Setup collected in chat; budget correction preserves other facts")

            count = len(corrected["messages"])
            replay = action("messages", "live-correction", "Change the compute cost from $120 to $180. Keep the model token cost at $15.")
            assert len(replay["messages"]) == count
            saved = client.get(route).json()
            assert saved["messages"] == replay["messages"]
            report["checks"].append("Retry does not duplicate the message; reload preserves the interview")

            if saved.get("current_question"):
                field = saved["current_question"]["field"]
                skipped = action("skip", "live-defer")
                items = {item["id"]: item for item in skipped["checklist"]}
                assert items[field]["status"] == "deferred"
                assert (skipped.get("current_question") or {}).get("field") != field
                report["checks"].append("Deferred topic is retained and is not asked again")

            draft = action("draft", "live-draft")
            readme = client.get(route + "/readme.md")
            readme.raise_for_status()
            assert draft["readme"] and "18:00" in readme.text
            assert "4.2" in readme.text and "$180" in readme.text
            assert "researcher@example.org" not in readme.text
            assert "method" in readme.text.lower() and "deploy" in readme.text.lower()
            report["checks"].append("README contains methodology, deployment and reference facts; private email excluded")
            with app.state.store.connection() as connection:
                row = connection.execute("SELECT body FROM projects WHERE id=?", (project_id,)).fetchone()
            stored = json.loads(row[0])
            report["model_calls"] = stored["_model_calls"]
            report["final_phase"] = draft["phase"]
            report["followups"] = draft["followups"]
    if args.report:
        args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
