"""Reference documents for the interview. They give the agent context and never enter a package.

Only the extracted text is kept. It lives under the session directory, so deleting
the session deletes it, and the package build reads only the dataset.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid

from fastapi import File, HTTPException, Request, UploadFile

from .store import now

MAX_DOCUMENT_BYTES = 50 * 1024 * 1024
MAX_DOCUMENTS = 20
READER = Path(__file__).with_name("document_reader.py")
# Set by the application: maps a project ID to its private directory.
DIRECTORY = None


def extract(body, name="", content_type=""):
    """Read untrusted bytes in the bounded reader. Raise ValueError with a researcher-facing reason."""
    try:
        result = subprocess.run([sys.executable, "-I", str(READER), name[:180], content_type[:120]], input=body,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=45, check=True)
        parsed = json.loads(result.stdout)
    except (subprocess.SubprocessError, ValueError):
        raise ValueError("This file could not be read within the time and memory limits. Attach a smaller text or PDF version.") from None
    if parsed.get("error"):
        raise ValueError(parsed["error"])
    if not parsed.get("text", "").strip():
        raise ValueError("This file has no readable text. Attach a text, PDF, or Office version.")
    return parsed


def _records(project):
    return project.setdefault("_documents", [])


def _path(project, identifier):
    return Path(DIRECTORY(project["id"])) / "documents" / (identifier + ".txt")


def view(project):
    """Return document details for the interface, without their text. pending means not sent yet."""
    waiting = project.get("_new_documents", [])
    return [{**{key: record[key] for key in ("id", "name", "kind", "bytes", "chars", "truncated", "added_at")}, "pending": record["id"] in waiting}
            for record in project.get("_documents", [])]


def find(project, reference):
    """Find a document by its identifier or its exact file name."""
    records = project.get("_documents", [])
    return next((r for r in records if r["id"] == reference), None) or next((r for r in records if r["name"] == reference), None)


def text(project, record):
    return _path(project, record["id"]).read_text(encoding="utf-8")


def add(project, filename, body):
    if len(body) > MAX_DOCUMENT_BYTES:
        raise ValueError("Attach a document up to 50 MB.")
    name = Path((filename or "document").replace("\\", "/")).name[:180] or "document"
    digest = hashlib.sha256(body).hexdigest()
    records = _records(project)
    existing = next((record for record in records if record["sha256"] == digest), None)
    if existing:
        # Attaching a known file again sends it with the next message, without a second copy.
        waiting = project.setdefault("_new_documents", [])
        if existing["id"] not in waiting:
            waiting.append(existing["id"])
        return existing
    if len(records) >= MAX_DOCUMENTS:
        raise ValueError(f"A session can hold {MAX_DOCUMENTS} documents. Remove one before attaching another.")
    parsed = extract(body, name)
    record = {"id": uuid.uuid4().hex, "name": name, "kind": parsed["kind"], "bytes": len(body), "sha256": digest,
              "chars": len(parsed["text"]), "truncated": bool(parsed.get("truncated")), "added_at": now()}
    path = _path(project, record["id"])
    path.parent.mkdir(mode=0o700, exist_ok=True)
    path.write_text(parsed["text"], encoding="utf-8")
    records.append(record)
    project.setdefault("_new_documents", []).append(record["id"])
    return record


def remove(project, identifier):
    record = next((r for r in project.get("_documents", []) if r["id"] == identifier), None)
    if record is None:
        raise ValueError("This document is no longer attached.")
    _path(project, identifier).unlink(missing_ok=True)
    project["_documents"].remove(record)
    if identifier in project.get("_new_documents", []):
        project["_new_documents"].remove(identifier)
    # Lookup excerpts and model traces can quote the removed text.
    project.pop("_model_traces", None)
    state = project.get("conversation") or {}
    state["_tool_log"] = [entry for entry in state.get("_tool_log", []) if entry.get("source") not in {identifier, record["name"]}]
    return record


def take_new(project):
    """Return documents attached since the last message, to show on the next one."""
    identifiers = project.pop("_new_documents", [])
    return [{"id": r["id"], "name": r["name"]} for r in project.get("_documents", []) if r["id"] in identifiers]


def register(app, store, editing):
    @app.post("/api/projects/{project_id}/documents")
    def attach_document(project_id: str, request: Request, file: UploadFile = File(...)):
        with editing(project_id, request) as item:
            try:
                body = file.file.read(MAX_DOCUMENT_BYTES + 1)
                record = add(item, file.filename, body)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            finally:
                file.file.close()
            store.save(item)
            return {"document": {key: record[key] for key in ("id", "name", "kind", "chars", "truncated")}, "documents": view(item)}

    @app.delete("/api/projects/{project_id}/documents/{document_id}")
    def remove_document(project_id: str, document_id: str, request: Request):
        with editing(project_id, request) as item:
            if not any(record["id"] == document_id for record in item.get("_documents", [])):
                raise HTTPException(404, "This document is no longer attached.")
            store.record_erasure(project_id, "content")
            remove(item, document_id)
            store.save(item)
        store.checkpoint()
        return {"deleted": True, "documents": view(item)}
