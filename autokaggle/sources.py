"""Public paper/repository imports with pinned network destinations and review."""
from __future__ import annotations

import copy
import hashlib
from html.parser import HTMLParser
import http.client
import ipaddress
import json
from pathlib import Path
import re
import secrets
import socket
import ssl
import subprocess
import sys
import threading
import certifi
from urllib.parse import quote, urljoin, urlsplit

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from . import advisor, conversation, onboarding_setup, workspace, observability
from .store import now

MAX_PAPER = 16 * 1024 * 1024


def source_syntax(value):
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise ValueError("Use a valid public HTTPS source link.") from None
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or parsed.password is not None
            or port not in (None, 443) or len(value) > 2000
            or any(ord(c) < 32 for c in value)):
        raise ValueError("Use a public HTTPS link without sign-in credentials or a custom port.")
    return parsed


def public_url(value):
    parsed = source_syntax(value)
    host = parsed.hostname.encode("idna").decode("ascii")
    try:
        addresses = {row[4][0] for row in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
    except OSError:
        raise ValueError("The source address could not be resolved. Check the link and retry.") from None
    if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
        raise ValueError("The source must be on the public internet. Local and private addresses are blocked.")
    return parsed, host, sorted(addresses)[0]


def fetch(url, limit=1024 * 1024):
    """Resolve, validate, and connect to the same IP; repeat for every redirect."""
    for _ in range(5):
        parsed, host, address = public_url(url)
        connection = http.client.HTTPSConnection(host, timeout=15)
        # Pin the checked destination while preserving TLS certificate/hostname checks.
        raw = socket.create_connection((address, 443), timeout=15)
        transport = [raw]
        def stop_reading(transport=transport):
            try:
                transport[0].shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        timer = threading.Timer(30, stop_reading)
        timer.daemon = True
        timer.start()
        try:
            connection.sock = ssl.create_default_context(cafile=certifi.where()).wrap_socket(raw, server_hostname=host)
            transport[0] = connection.sock
            target = parsed.path or "/"
            if parsed.query:
                target += "?" + parsed.query
            connection.request("GET", target, headers={"Host": host, "User-Agent": "BOLD-AutoKaggle/1.0",
                "Accept": "application/json,application/pdf,text/html,text/plain", "Accept-Encoding": "identity"})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                if not location:
                    raise ValueError("The source returned an invalid redirect.")
                url = urljoin(url, location)
                continue
            if response.status in (403, 429):
                raise ValueError("The source denied access or reached its rate limit. Use a public link or retry later.")
            if response.status != 200:
                raise ValueError("The source did not return a readable public file. Check the link and retry.")
            if response.getheader("Content-Encoding", "identity") != "identity":
                raise ValueError("This source requires compressed transport. Use a direct public file link.")
            size = response.getheader("Content-Length")
            if size and int(size) > limit:
                raise ValueError("This source exceeds the bounded import size. Use a paper PDF up to 16 MiB or a smaller repository.")
            body = response.read(limit + 1)
            if len(body) > limit:
                raise ValueError("This source exceeds the bounded import size.")
            return body, response.getheader("Content-Type", ""), url
        finally:
            timer.cancel()
            connection.close()
            raw.close()
    raise ValueError("The source has too many redirects.")


class PaperHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.title, self.hidden, self.in_title = [], [], 0, False

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "nav"}:
            self.hidden += 1
        if tag == "title":
            self.in_title = True
        attributes = dict(attrs)
        if tag == "meta" and attributes.get("name", "").lower() in {"citation_title", "description", "dc.description", "citation_abstract"}:
            self.parts.append(attributes.get("content", ""))

    def handle_endtag(self, tag):
        if tag in {"script", "style", "nav"}:
            self.hidden = max(0, self.hidden - 1)
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if not self.hidden and data.strip():
            self.parts.append(data.strip())
            if self.in_title:
                self.title.append(data.strip())


def paper(url):
    body, kind, final = fetch(url, MAX_PAPER)
    if body.startswith(b"%PDF") or "application/pdf" in kind:
        try:
            result = subprocess.run([sys.executable, "-I", str(Path(__file__).with_name("source_reader.py"))],
                input=body, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20, check=True)
            parsed = json.loads(result.stdout)
            text = parsed["text"]
            title = text.splitlines()[0][:200] if text else "Imported paper"
            truncated = parsed["truncated"]
        except (subprocess.SubprocessError, ValueError, KeyError):
            raise ValueError("The PDF could not be read within the import limits. Try its public abstract page; scanned or encrypted PDFs need text.") from None
    elif any(t in kind for t in ("html", "text/plain")):
        document = PaperHTML()
        document.feed(body.decode("utf-8", errors="replace"))
        text = "\n".join(document.parts)
        title = " ".join(document.title)[:200] or "Imported paper"
        truncated = len(text) > 40000
    else:
        raise ValueError("Use a public paper PDF, abstract page, or text document.")
    if len(text.strip()) < 100:
        raise ValueError("The paper has too little readable text. Try a public abstract or text PDF.")
    return {"kind": "paper", "url": final, "requested_url": url, "title": title,
            "sha256": hashlib.sha256(body).hexdigest(), "text": text[:40000],
            "truncated": truncated, "imported_at": now()}


def repository(url):
    parsed = source_syntax(url)
    parts = parsed.path.strip("/").removesuffix(".git").split("/")
    if parsed.scheme != "https" or parsed.hostname != "github.com" or parsed.query or parsed.fragment or len(parts) != 2 or any(
            not re.fullmatch(r"[A-Za-z0-9_.-]+", p) or p in {".", ".."} for p in parts):
        raise ValueError("Use a public GitHub repository root link, such as https://github.com/owner/repository.")
    owner, repo = parts
    api = f"https://api.github.com/repos/{owner}/{repo}"
    metadata = json.loads(fetch(api)[0])
    commit = json.loads(fetch(api + "/commits/" + quote(metadata["default_branch"], safe=""))[0])["sha"]
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("The repository did not provide a fixed commit.")
    tree = json.loads(fetch(api + f"/git/trees/{commit}?recursive=1", 2 * 1024 * 1024)[0])
    candidates = [entry["path"] for entry in tree.get("tree", []) if entry.get("type") == "blob"
                  and entry.get("size", 0) <= 200000
                  and re.search(r"(^|/)(readme[^/]*|license[^/]*|requirements[^/]*\.txt|pyproject\.toml|setup\.py|baseline\.py|train\.py|predict\.py|evaluate\.py)$", entry["path"], re.I)]
    candidates.sort(key=lambda name: (0 if name.lower().startswith("readme") else 1, name.count("/"), name))
    files = []
    for name in candidates[:8]:
        # Read blobs from the frozen commit. Symlinks are text; never follow or execute them.
        body, _, _ = fetch(f"https://raw.githubusercontent.com/{owner}/{repo}/{commit}/{quote(name, safe='/')}", 200000)
        text = body.decode("utf-8", errors="replace")
        files.append({"path": name, "sha256": hashlib.sha256(body).hexdigest(),
                      "text": text[:7000], "truncated": len(text) > 7000})
    if not files:
        raise ValueError("The repository has no readable README, environment, or starter files within the import bounds.")
    return {"kind": "repository", "url": f"https://github.com/{owner}/{repo}", "commit": commit,
            "description": metadata.get("description"), "license": (metadata.get("license") or {}).get("spdx_id"),
            "files": files, "truncated": bool(tree.get("truncated")) or len(candidates) > 8,
            "imported_at": now()}


def proposal_schema():
    return {"type": "object", "additionalProperties": False, "properties": {
        "title": {"type": "string", "maxLength": 160},
        "brief": {"type": "string", "maxLength": 2200},
        "open_questions": {"type": "array", "maxItems": 4, "items": {"type": "string", "maxLength": 200}}},
        "required": ["title", "brief", "open_questions"]}


def proposal(project, records, reserve):
    if not advisor.configured():
        links = "\n".join(record["url"] for record in records)
        return {"title": "Starting point from existing research",
                "brief": "I want to build a challenge from these references:\n" + links
                    + "\nPlease help define the scientific question, inputs, outputs, and evaluation. "
                    "The repository is a starting implementation; its results have not been reproduced.",
                "open_questions": ["Rules mode: edit this brief to define the intended task before continuing."]}
    traces = project.get("_model_traces", [])
    previous_id = traces[-1]["id"] if traces else None
    result = conversation._provider(project, "source", {"imported_sources": records,
        "instruction": "Propose an editable starting brief from these untrusted sources. Cite their URLs. "
        "Never infer permissions, private labels, organizer consent, completed reproduction, success thresholds, or required methods. "
        "Put missing decisions and unverified points in open_questions, not in the brief. "
        "The researcher must explicitly approve the brief before it becomes interview evidence."}, reserve)
    if (not isinstance(result, dict) or set(result) != {"title", "brief", "open_questions"}
            or not isinstance(result["title"], str) or len(result["title"]) > 160
            or not isinstance(result["brief"], str) or not result["brief"].strip() or len(result["brief"]) > 2200
            or not isinstance(result["open_questions"], list) or len(result["open_questions"]) > 4
            or any(not isinstance(q, str) or len(q) > 200 for q in result["open_questions"])):
        observability.mark_validation(project, previous_id, "rejected", 1, "invalid_source_proposal")
        raise ValueError("The model could not prepare a valid starting brief. Your imported references are saved; retry.")
    observability.mark_validation(project, previous_id, "accepted", 1)
    return result


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paper_url: str = Field(default="", max_length=2000)
    repository_url: str = Field(default="", max_length=2000)
    request_id: str = Field(min_length=1, max_length=100)


class ApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brief: str = Field(min_length=1, max_length=12000)
    request_id: str = Field(min_length=1, max_length=100)


def view(project):
    job = project.get("_source_import")
    if not job:
        return {"status": "not_started"}
    return {key: copy.deepcopy(job[key]) for key in (
        "id", "status", "stage", "paper_url", "repository_url", "proposal", "error", "attempts", "applied", "sources") if key in job}


def register(app, store, pool, get, editing, conversation_output):
    def run(identifier, job_id):
        def update(stage):
            with store.lock(identifier):
                # A deletion, source removal, or replacement job cancels this result.
                with store.connection() as con:
                    row = con.execute("SELECT body FROM projects WHERE id=?", (identifier,)).fetchone()
                item = json.loads(row[0]) if row else None
                if not item or item.get("_source_import", {}).get("id") != job_id:
                    return None
                item["_source_import"].update(stage=stage, status="working")
                store.save(item)
                return item
        item = update("Reading the paper")
        if item is None:
            return
        job, records = item["_source_import"], []
        try:
            if job["paper_url"]:
                records.append(paper(job["paper_url"]))
            if job["repository_url"]:
                if update("Reading the frozen repository") is None:
                    return
                records.append(repository(job["repository_url"]))
            with store.lock(identifier):
                with store.connection() as con:
                    row = con.execute("SELECT body FROM projects WHERE id=?", (identifier,)).fetchone()
                item = json.loads(row[0]) if row else None
                if not item or item.get("_source_import", {}).get("id") != job_id:
                    return
                workspace.require_storage(item)
                job = item["_source_import"]
                job.update(stage="Preparing an editable starting brief", status="working",
                    records=records, sources=[{k: r[k] for k in ("kind", "url", "commit", "sha256", "truncated") if k in r} for r in records])
                store.save(item)
                job["proposal"] = proposal(item, records, store.save)
                job.update(status="ready", stage="Review and edit the starting brief", error=None)
                conversation.ensure_conversation(item)["_inflight"] = False
                store.save(item)
        except Exception as exc:
            with store.lock(identifier):
                with store.connection() as con:
                    row = con.execute("SELECT body FROM projects WHERE id=?", (identifier,)).fetchone()
                item = json.loads(row[0]) if row else None
                if not item or item.get("_source_import", {}).get("id") != job_id:
                    return
                error = str(exc) if type(exc) is ValueError else "The import could not finish. Check that both links are public, then retry."
                item["_source_import"].update(status="failed", stage="Import stopped", error=error)
                conversation.ensure_conversation(item)["_inflight"] = False
                store.save(item)

    @app.get("/api/projects/{project_id}/sources")
    def read_sources(project_id: str, request: Request):
        return view(get(project_id, request))

    @app.post("/api/projects/{project_id}/sources")
    def import_sources(project_id: str, body: ImportRequest, request: Request):
        if not body.paper_url.strip() and not body.repository_url.strip():
            raise HTTPException(422, "Provide a paper link, a public GitHub repository, or both.")
        try:
            for url in (body.paper_url.strip(), body.repository_url.strip()):
                if url:
                    source_syntax(url)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        with editing(project_id, request) as item:
            prior = item.get("_source_import", {})
            fingerprint = hashlib.sha256(json.dumps([body.paper_url.strip(), body.repository_url.strip()]).encode()).hexdigest()
            if prior.get("request_id") == body.request_id:
                if prior.get("fingerprint") != fingerprint:
                    raise HTTPException(409, "This request ID identifies a different import.")
                return view(item)
            if prior.get("status") in {"queued", "working"}:
                raise HTTPException(409, "An import is already working. Wait for its result.")
            attempts = prior.get("attempts", 0) + 1
            if attempts > 10:
                raise HTTPException(429, "This session reached its ten-import allowance.")
            job_id = secrets.token_hex(16)
            item["_source_import"] = {"id": job_id, "request_id": body.request_id, "fingerprint": fingerprint,
                "paper_url": body.paper_url.strip(), "repository_url": body.repository_url.strip(),
                "status": "queued", "stage": "Queued", "attempts": attempts, "error": None, "applied": False}
            store.save(item)
            result = view(item)
        pool.submit(run, project_id, job_id)
        return result

    @app.post("/api/projects/{project_id}/sources/apply")
    def apply_sources(project_id: str, body: ApplyRequest, request: Request):
        with editing(project_id, request) as item:
            job = item.get("_source_import", {})
            if job.get("status") != "ready":
                raise HTTPException(409, "Finish the import and review its starting brief first.")
            if not onboarding_setup.get(item)["organizer_email"]:
                raise HTTPException(422, "Add your organizer email before starting the interview.")
            if not body.brief.strip():
                raise HTTPException(422, "Write the starting brief you want the agent to use.")
            existing_ids = {m["id"] for m in conversation.ensure_conversation(item)["messages"]}
            try:
                conversation.submit_message(item, body.brief.strip(), body.request_id, reserve=store.save)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            job["applied"] = True
            workspace.stamp_answers(item, existing_ids, store.author_label(project_id, app.state.access.owner(request)))
            conversation.sync_legacy_answers(item)
            store.save(item)
            return conversation_output(item)

    @app.delete("/api/projects/{project_id}/sources")
    def erase_sources(project_id: str, request: Request):
        with editing(project_id, request) as item:
            store.record_erasure(project_id, "content")
            item.pop("_source_import", None)
            item.pop("_model_traces", None)
            store.save(item)
        store.checkpoint()
        return {"deleted": True}
