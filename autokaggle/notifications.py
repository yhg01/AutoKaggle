"""Private organizer invitations with scoped, expiring, single-use login links."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import base64
import hashlib
import os
import secrets
import smtplib
import ssl
from urllib.parse import quote, urlparse

import httpx

from . import onboarding_setup, workflow


class MailUnavailable(Exception):
    """Safe delivery failure; provider responses and credentials stay private."""


def email_login_available():
    """Report configuration, not proof that a message reached an inbox."""
    base = urlparse(os.getenv("AUTOKAGGLE_PUBLIC_BASE_URL", ""))
    credentials = _gmail_configured() or bool(os.getenv("AUTOKAGGLE_SMTP_PASSWORD", "").strip())
    return bool(credentials
                and base.scheme == "https" and base.hostname
                and not (base.username or base.password or base.query or base.fragment))


def _gmail_configured():
    return all(os.getenv("AUTOKAGGLE_GMAIL_" + part, "").strip()
               for part in ("CLIENT_ID", "CLIENT_SECRET", "REFRESH_TOKEN"))


def _send_message(message):
    """Send once. An uncertain provider result must not cause an automatic resend."""
    try:
        if _gmail_configured():
            with httpx.Client(timeout=15, follow_redirects=False) as client:
                response = client.post("https://oauth2.googleapis.com/token", data={
                    "client_id": os.environ["AUTOKAGGLE_GMAIL_CLIENT_ID"],
                    "client_secret": os.environ["AUTOKAGGLE_GMAIL_CLIENT_SECRET"],
                    "refresh_token": os.environ["AUTOKAGGLE_GMAIL_REFRESH_TOKEN"],
                    "grant_type": "refresh_token"})
                if response.status_code != 200:
                    raise MailUnavailable("Email could not be sent. Try again later.")
                credentials = response.json()
                token = credentials.get("access_token")
                if not isinstance(token, str) or not token:
                    raise MailUnavailable("Email could not be sent. Try again later.")
                sender = os.getenv("AUTOKAGGLE_MAIL_FROM", "boldcoscientist@gmail.com")
                response = client.post("https://gmail.googleapis.com/gmail/v1/users/" + quote(sender, safe="") + "/messages/send",
                    headers={"Authorization": "Bearer " + token},
                    json={"raw": base64.urlsafe_b64encode(message.as_bytes()).decode()})
                if response.status_code != 200 or not response.json().get("id"):
                    raise MailUnavailable("Email could not be sent. Try again later.")
        else:
            sender = os.getenv("AUTOKAGGLE_MAIL_FROM", "boldcoscientist@gmail.com")
            with smtplib.SMTP_SSL(os.getenv("AUTOKAGGLE_SMTP_HOST", "smtp.gmail.com"),
                                 int(os.getenv("AUTOKAGGLE_SMTP_PORT", "465")),
                                 context=ssl.create_default_context(), timeout=15) as client:
                client.login(os.getenv("AUTOKAGGLE_SMTP_USERNAME", sender),
                             os.environ["AUTOKAGGLE_SMTP_PASSWORD"])
                if client.send_message(message):
                    raise MailUnavailable("Email could not be sent. Try again later.")
    except (OSError, smtplib.SMTPException, httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
        raise MailUnavailable("Email could not be sent. Try again later.") from None


def send_login_code(email: str, code: str):
    """Send a code only after the access service reserves its send allowance."""
    if not email_login_available():
        raise MailUnavailable("Email sign-in is not available yet. Contact the organizer.")
    if len(code) != 6 or not code.isascii() or not code.isdigit():
        raise MailUnavailable("The sign-in email could not be sent. Try again later.")
    sender = os.getenv("AUTOKAGGLE_MAIL_FROM", "boldcoscientist@gmail.com")
    base = os.getenv("AUTOKAGGLE_PUBLIC_BASE_URL", "").rstrip("/")
    try:
        message = EmailMessage()
        message["From"] = sender
        message["To"] = email
        message["Subject"] = "Your BOLD AutoKaggle sign-in code"
        message.set_content(
            "Your BOLD AutoKaggle sign-in code is:\n\n" + code + "\n\n"
            "Enter this code on " + base + "/login.\n"
            "The code expires in 10 minutes. It works once.\n"
            "Do not share this code. If you did not request it, ignore this email.\n")
        _send_message(message)
    except (MailUnavailable, OSError, smtplib.SMTPException, ValueError, KeyError):
        raise MailUnavailable("The sign-in email could not be sent. Try again later.") from None


def initialize(store):
    with store.connection() as con:
        con.execute("CREATE TABLE IF NOT EXISTS review_tokens (digest TEXT PRIMARY KEY, project TEXT NOT NULL, version TEXT NOT NULL, expires TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 0)")
        if "draft" not in {row[1] for row in con.execute("PRAGMA table_info(review_tokens)")}:
            con.execute("ALTER TABLE review_tokens ADD COLUMN draft TEXT NOT NULL DEFAULT ''")
        con.execute("CREATE TABLE IF NOT EXISTS review_grants (session TEXT NOT NULL, project TEXT NOT NULL, expires TEXT NOT NULL, PRIMARY KEY(session, project))")


def _utc():
    return datetime.now(timezone.utc)


def send_review(store, project, *, renew=False):
    current = workflow.view(project)
    if current["status"] != "ready_for_review":
        result = {"status": "not_ready", "detail": "Resolve the draft checks before sending the review invitation."}
    else:
        if not renew and current.get("notification", {}).get("status") == "sent":
            with store.connection() as con:
                # A redeemed invitation must not trigger a duplicate on the next build.
                # An active scoped session already gives the organizer review access.
                valid = con.execute("SELECT 1 FROM review_tokens WHERE project=? AND version=? AND draft=? AND expires>?", (project["id"], current["version"], workflow.fingerprint(project), _utc().isoformat())).fetchone()
                signed_in = con.execute("SELECT 1 FROM review_grants WHERE project=? AND expires>?", (project["id"], _utc().isoformat())).fetchone()
            if valid or signed_in:
                return current["notification"]
        base = os.getenv("AUTOKAGGLE_PUBLIC_BASE_URL", "").rstrip("/")
        parsed = urlparse(base)
        sender = os.getenv("AUTOKAGGLE_MAIL_FROM", "boldcoscientist@gmail.com")
        password = os.getenv("AUTOKAGGLE_SMTP_PASSWORD", "")
        if not password and not _gmail_configured():
            result = {"status": "not_configured", "detail": "Gmail sending access is not configured. See docs/EMAIL_SETUP.md."}
        elif parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            result = {"status": "not_configured", "detail": "Set an HTTPS review address that the organizer can access before sending email."}
        else:
            token = secrets.token_urlsafe(32)
            digest = hashlib.sha256(token.encode()).hexdigest()
            with store.connection() as con:
                con.execute("DELETE FROM review_tokens WHERE project=? AND used=0", (project["id"],))
                con.execute("INSERT INTO review_tokens (digest,project,version,expires,used,draft) VALUES (?,?,?,?,0,?)", (digest, project["id"], current["version"], (_utc() + timedelta(hours=24)).isoformat(), workflow.fingerprint(project)))
            result = {"status": "pending", "detail": "The review invitation is being sent."}
            project["workflow"]["notification"] = result
            store.save(project)
            message = EmailMessage()
            message["From"] = sender
            message["To"] = onboarding_setup.get(project)["organizer_email"]
            message["Subject"] = "Your BOLD AutoKaggle draft is ready for review"
            first = current.get("first_result") or {}
            project_root = base + f"/api/projects/{project['id']}/workflow"
            review_hub = base + f"/?project={project['id']}&view=review"
            message.set_content("Your private BOLD AutoKaggle draft is ready.\n\n"
                + f"Version: {current['version']}\n"
                + f"Submission pipeline test: {first.get('metric', 'not available')} {first.get('score', '')}\n"
                + "This result uses training-derived validation. It is not a final test score or a reproduced scientific reference result.\n\n"
                + "First, sign in with this private link. Use it within 24 hours. It works once and opens only this challenge.\n"
                + base + "/review#token=" + token + "\n\n"
                + "After sign-in, use these links in the same browser:\n\n"
                + "A. Challenge website\n" + project_root + "/preview\n\n"
                + "B. Research package (ZIP)\n" + project_root + "/package\n\n"
                + "C. Test the submission service\n" + project_root + "/preview#submission\n\n"
                + "Request changes with the agent\n" + review_hub + "\n\n"
                + "Tell the agent what you want to change: the problem definition, method and deployment, or baseline reproduction. "
                + "The agent keeps your earlier answers and asks for the details needed for each change.\n\n"
                + "Review the measured development result, checks, and open decisions before requesting a revised draft. "
                + "Your review access lasts seven days. The challenge has not been published.\n")
            try:
                _send_message(message)
                result = {"status": "sent", "detail": "Gmail accepted the organizer invitation. Check the inbox and spam folder.", "sent_at": _utc().isoformat()}
            except (MailUnavailable, OSError, smtplib.SMTPException, ValueError):
                # Do not log addresses, link tokens, credentials, or provider response text.
                with store.connection() as con:
                    con.execute("DELETE FROM review_tokens WHERE digest=?", (digest,))
                result = {"status": "failed", "detail": "Email delivery could not be confirmed. Check the Gmail settings, then retry."}
    if project.get("workflow"):
        project["workflow"]["notification"] = result
        store.save(project)
    return result


def redeem(store, token, existing_session=""):
    if not isinstance(token, str) or not 30 <= len(token) <= 100:
        raise ValueError("This review link is invalid or expired.")
    digest = hashlib.sha256(token.encode()).hexdigest()
    with store.connection() as con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute("SELECT project, version, draft FROM review_tokens WHERE digest=? AND used=0 AND expires>?", (digest, _utc().isoformat())).fetchone()
        if not row:
            raise ValueError("This review link is invalid or expired.")
        import json
        saved = con.execute("SELECT body FROM projects WHERE id=?", (row[0],)).fetchone()
        project = json.loads(saved[0]) if saved else None
        if not project or workflow.view(project).get("status") != "ready_for_review" or project["workflow"]["version"] != row[1] or workflow.fingerprint(project) != row[2]:
            raise ValueError("This draft changed. Request a new review link from the organizer.")
        session = existing_session if isinstance(existing_session, str) and 32 <= len(existing_session) <= 100 else secrets.token_urlsafe(32)
        con.execute("UPDATE review_tokens SET used=1 WHERE digest=?", (digest,))
        con.execute("INSERT OR REPLACE INTO review_grants VALUES (?,?,?)", (session, row[0], (_utc() + timedelta(days=7)).isoformat()))
        return session, row[0]
