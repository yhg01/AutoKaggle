"""Release review, notification, and BOLD OS eligibility.

Synthetic checks, reported research results, checked research evidence, and human
approval are separate facts. No download or model response can approve a release.
"""
from __future__ import annotations

from email.message import EmailMessage
import hashlib
import json
import os
import re
from urllib.parse import quote

from . import notifications
from .store import now


def invitation(store, item, build, *, retry=False):
    saved = build.get("review_invitation") or {}
    if saved.get("status") == "sent" or (saved and saved.get("status") != "queued" and not retry):
        return saved
    email = item.get("setup", {}).get("organizer_email")
    if not email or not notifications.email_login_available():
        build["review_invitation"] = {"status": "unavailable", "reason": "Review email is not configured. The session and release are saved."}
        store.save(item)
        return build["review_invitation"]
    base = os.environ["AUTOKAGGLE_PUBLIC_BASE_URL"].rstrip("/")
    link = base + "/lite?project=" + quote(item["id"], safe="") + "&review=evaluator"
    build["review_invitation"] = {"status": "sending", "attempted_at": now(), "attempts": saved.get("attempts", 0) + 1}
    store.save(item)  # A process crash leaves an uncertain send, never an automatic duplicate.
    message = EmailMessage()
    message["From"] = os.getenv("AUTOKAGGLE_MAIL_FROM", "boldcoscientist@gmail.com")
    message["To"] = email
    message["Subject"] = "Review your AutoKaggle Lite evaluator"
    published = build.get("published") or {}
    message.set_content(f"Your evaluator is ready for software review: {item['title']}\n"
        f"Version: {build['evaluator_version']}\n\nOpen your saved session:\n{link}\n\n"
        "Sign in with your organizer email. Review the code, tests, downloads, and validation record. "
        "Use the code review conversation to request changes. The coding agent starts from this release and tests the revised version. "
        "Scientific changes must be accepted in the contract before a new build.\n\n"
        "Synthetic tests have passed. Validation on the declared research data and human approval remain separate steps.\n"
        + (f"\nRepository: {published['url']}\nZIP: {published['zip_url']}\n" if published else
           "\nDownload the release and config from the Evaluator view in your session.\n"))
    try:
        notifications._send_message(message)
    except notifications.MailUnavailable:
        build["review_invitation"].update(status="uncertain", reason="The mail service did not confirm delivery. Check the inbox before retrying.")
    else:
        build["review_invitation"].update(status="sent", sent_at=now())
    store.save(item)
    return build["review_invitation"]


def registry_payload(item, build):
    """Fail closed. Retries identify the exact release, evidence, and approval."""
    validation, approval, evidence = build.get("validation") or {}, build.get("human_approval") or {}, build.get("evidence") or {}
    commit, contract = evidence.get("commit"), build.get("contract_sha256")
    from . import lite
    if build.get("contract_version") != lite.version(item["lite"]["contract"], item["lite"].get("sources", [])):
        raise ValueError("The scientific contract changed. Validate and approve the current version.")
    if not commit or not contract or build.get("status") != "ready":
        raise ValueError("A tested evaluator release is required.")
    if any(validation.get(k) != "passed" for k in ("build", "contract_coverage", "code_review", "synthetic")):
        raise ValueError("Complete the software and contract checks first.")
    research = validation.get("research_evidence") or {}
    if (validation.get("research_data") != "validated" or research.get("passed") is not True
            or research.get("mode") != "research" or research.get("commit") != commit
            or research.get("contract_sha256") != contract or not research.get("reference_sha256")
            or not research.get("report_sha256") or not research.get("artifact_sha256")
            or not re.fullmatch(r"controlled-runtime:[a-f0-9]{16}", str(research.get("checked_by", "")))):
        raise ValueError("Validation on the declared research data is still required.")
    if (approval.get("commit") != commit or approval.get("contract_sha256") != contract
            or approval.get("research_report_sha256") != research["report_sha256"] or not approval.get("approved_by")):
        raise ValueError("Human approval of this release and its research validation is required.")
    published = build.get("published") or {}
    if published.get("commit") != commit or not published.get("url"):
        raise ValueError("Publish this exact evaluator commit before BOLD OS registration.")
    c = item["lite"]["contract"]
    return {"schema": "bold.autokaggle.registration.v1", "source_id": "autokaggle:" + item["id"],
            "idempotency_key": hashlib.sha256(json.dumps([item["id"], commit, research["report_sha256"], approval.get("approved_at")], separators=(",", ":")).encode()).hexdigest(),
            "destinations": ["problem_bank", "benchmarks"], "title": c.get("title", item["title"]),
            "objective": c.get("objective"), "task_kind": c.get("task_kind"),
            "evaluator": {"repository": published["url"], "commit": commit, "version": build["evaluator_version"],
                          "zip_url": published["zip_url"], "contract_sha256": contract},
            "validation": validation, "human_approval": approval,
            "source": {"url": c.get("source_url"), "revision": c.get("source_revision")}}


def queue_registration(item, build):
    try:
        payload = registry_payload(item, build)
    except ValueError as exc:
        build["registry"] = {"status": "not_eligible", "reason": str(exc)}
        return
    # Keep this outbox durable. Do not invent an endpoint or bypass BOLD OS access.
    old = build.get("registry") or {}
    if old.get("idempotency_key") == payload["idempotency_key"] and old.get("status") == "registered":
        return
    build["registry"] = {**(old if old.get("idempotency_key") == payload["idempotency_key"] else {}),
                         "status": "pending_connection", "idempotency_key": payload["idempotency_key"],
                         "payload": payload, "queued_at": now(),
                         "reason": "The BOLD OS Problem Bank and Benchmarks write connection must be configured."}


def deliver_registration(store, item, build, *, client=None):
    """Send an eligible outbox record through an explicitly configured BOLD API.

    This adapter does not create a BOLD API or extend a read-only MCP token.
    A response must confirm both records for the exact evaluator commit.
    """
    from urllib.parse import urlsplit
    import httpx
    queue_registration(item, build)
    queued = build["registry"]
    if queued["status"] in {"not_eligible", "registered"}:
        store.save(item)
        return
    url = os.getenv("AUTOKAGGLE_BOLD_REGISTRY_URL", "")
    token = os.getenv("AUTOKAGGLE_BOLD_REGISTRY_TOKEN", "")
    if not url or not token:
        store.save(item)
        return
    try:
        parsed = urlsplit(url)
        valid_url = (parsed.scheme == "https" and parsed.hostname == "europe-west2-bold-d7ff2.cloudfunctions.net"
                     and not (parsed.username or parsed.password or parsed.query or parsed.fragment)
                     and parsed.port in (None, 443) and parsed.path == "/boldApi/v1/register_benchmark")
    except ValueError:
        valid_url = False
    if not valid_url:
        queued.update(status="failed", reason="The configured registry endpoint is not an approved BOLD OS HTTPS endpoint.")
        store.save(item)
        return
    queued.update(status="sending", attempts=queued.get("attempts", 0) + 1, attempted_at=now())
    store.save(item)
    own_client = client is None
    client = client or httpx.Client(timeout=30, follow_redirects=False)
    try:
        response = client.post(url, json={"registration": queued["payload"]}, headers={"Authorization": token if token.startswith("Bearer ") else "Bearer " + token, "Idempotency-Key": queued["idempotency_key"]})
        if response.status_code not in (200, 201):
            raise ValueError("BOLD OS did not accept registration (HTTP " + str(response.status_code) + "). The outbox entry is saved.")
        receipt = response.json()
        if (not isinstance(receipt, dict) or receipt.get("idempotency_key") != queued["idempotency_key"]
                or receipt.get("commit") != build["evidence"]["commit"]
                or any(not isinstance(receipt.get(k), str) or not receipt[k].strip() for k in ("problem_id", "benchmark_id"))):
            raise ValueError("BOLD OS did not confirm both records for the tested commit. Retry with the same outbox entry.")
        queued.update(status="registered", registered_at=now(), reason=None,
                      receipt={k: receipt[k] for k in ("problem_id", "benchmark_id", "commit", "idempotency_key")})
    except (ValueError, httpx.HTTPError) as exc:
        queued.update(status="failed", reason=str(exc) if isinstance(exc, ValueError) else
                      "The BOLD OS connection was interrupted. The outbox entry is saved for retry.")
    finally:
        if own_client:
            client.close()
        store.save(item)
