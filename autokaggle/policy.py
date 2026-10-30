"""Deterministic release gates; model advice cannot bypass these checks."""
from __future__ import annotations


def check(identifier, severity, title, detail, action=""):
    return {"id": identifier, "severity": severity, "title": title, "detail": detail, "action": action}


def known(value):
    return value.strip().lower() not in {"", "unknown", "not sure", "unsure", "tbd", "to be determined", "n/a", "?", "not yet", "i don't know"}


def brief_checks(project):
    a = project["answers"]
    checks = []
    fields = [("objective", "Scientific objective", "State what a successful result would establish."),
              ("prediction_unit", "Prediction unit", "State what one prediction represents, such as a patient or an experiment."),
              ("success_criterion", "Success criterion", "State what improvement would be scientifically useful.")]
    for key, label, action in fields:
        present = known(a.get(key, ""))
        checks.append(check(key, "pass" if present else "blocker", label,
                            "Recorded for human review." if present else "This decision is missing.", "" if present else action))
    private = a.get("labels_public") == "no"
    checks.append(check("public_labels", "pass" if private else "blocker", "Test answer exposure",
                        "The organizer states that these labels have not been public. This statement needs verification." if private else
                        "Test labels are public or their exposure is unknown. A new split cannot remove prior exposure.",
                        "" if private else "Use fresh private evaluation labels, then update the source declaration."))
    source_known = a.get("data_origin") in {"private", "public", "synthetic"}
    checks.append(check("provenance", "pass" if source_known else "blocker", "Data origin",
                        "Origin recorded. Retain the source and collection history in the brief." if source_known else "The data source is unknown.",
                        "" if source_known else "Identify how the data were collected or generated."))
    rights = a.get("rights") == "yes"
    checks.append(check("rights", "pass" if rights else "blocker", "Permission to use the data",
                        "The organizer confirms permission. This is a declaration, not a legal review." if rights else "Permission has not been confirmed.",
                        "" if rights else "Confirm permission before preparing a shareable package."))
    for key, label in [("compute_budget", "Compute estimate"), ("token_budget", "Model token estimate")]:
        present = known(a.get(key, ""))
        checks.append(check(key, "pass" if present else "warning", label,
                            f"Organizer estimate: {a[key]}" if present else "Estimate missing. Record US dollars for one credible attempt, or state unknown.",
                            "" if present else "Include experiments and final evaluation. A range or USD 0 is acceptable."))
    if a.get("data_origin") == "synthetic":
        checks.append(check("synthetic", "warning", "Synthetic data",
                            "This is a synthetic trial. Its results do not establish real scientific validity.", "Confirm the generator and intended use."))
    return checks


def summarize(checks):
    return {"blockers": sum(c["severity"] == "blocker" for c in checks),
            "warnings": sum(c["severity"] == "warning" for c in checks),
            "passed": sum(c["severity"] == "pass" for c in checks)}


def checklist(project):
    a, design = project["answers"], project["design"]
    analysis = project.get("analysis")
    has_problem = all(known(a.get(k, "")) for k in ("objective", "prediction_unit", "success_criterion"))
    return [
        {"id": "problem", "label": "Problem fit", "status": "complete" if has_problem else "missing", "detail": "Objective, prediction unit, and useful result."},
        {"id": "data", "label": "Data quality", "status": "complete" if project.get("dataset") else "missing", "detail": "A readable dataset and source declaration."},
        {"id": "design", "label": "Evaluation design", "status": "complete" if design.get("target") and analysis and not analysis["summary"]["blockers"] else "attention" if design.get("target") else "missing", "detail": "Target, metric, independent split, and private labels."},
        {"id": "trial", "label": "Trial run", "status": "complete" if analysis and analysis.get("baseline", {}).get("status") == "complete" else "attention" if analysis else "missing", "detail": "A development baseline; final test data stay sealed."},
        {"id": "review", "label": "Review and package", "status": "complete" if project.get("prepared") else "attention" if analysis else "missing", "detail": "Review the evidence, then prepare separate packages."},
    ]


def rules_advice(project, kind="conversation"):
    checks = (project.get("analysis") or {}).get("checks") or brief_checks(project)
    open_items = [c for c in checks if c["severity"] == "blocker"]
    warnings = [c for c in checks if c["severity"] == "warning"]
    if kind == "review":
        parts = ["Review the evidence before sharing this challenge."]
        parts += [f"• {c['title']}: {c['action'] or c['detail']}" for c in open_items[:5]]
        if not open_items:
            parts += ["The implemented checks have no blockers. Confirm that the objective, metric, and split match the scientific use case."]
        parts += [f"• {c['title']}: {c['detail']}" for c in warnings[:3]]
        parts += ["The private package needs an isolated evaluation runner before use with untrusted research code."]
        return "\n\n".join(parts)
    if not project.get("dataset"):
        open_items.insert(0, check("dataset", "blocker", "Dataset", "", "Attach a CSV, or choose a synthetic example to test the workflow."))
    if not open_items:
        return "The required fields are recorded. Run the data audit, review its findings, and confirm the evaluation design. The checklist shows the remaining work."
    return "The next useful decisions are:\n\n" + "\n\n".join(f"{i+1}. {c['action'] or c['detail']}" for i, c in enumerate(open_items[:3]))
