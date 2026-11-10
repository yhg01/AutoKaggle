"""Private local storage; ownership checks are part of every organizer lookup."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
import secrets
import sqlite3
import threading
import uuid
from datetime import datetime, timezone


def now():
    return datetime.now(timezone.utc).isoformat()


ANSWERS = {"objective": "", "prediction_unit": "", "success_criterion": "",
           "data_origin": "unknown", "labels_public": "unknown", "rights": "unknown",
           "compute_budget": "", "token_budget": ""}
DESIGN = {"target": "", "task": "classification", "metric": "accuracy", "split": "random",
          "group_column": "", "time_column": "", "exclude_columns": [], "test_fraction": 0.2}


class Store:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        self.db = self.root / "projects.sqlite3"
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}
        with self.connection() as con:
            con.execute("CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, owner TEXT NOT NULL, updated_at TEXT NOT NULL, participant TEXT UNIQUE, body TEXT NOT NULL)")
            con.execute("CREATE TABLE IF NOT EXISTS review_grants (session TEXT NOT NULL, project TEXT NOT NULL, expires TEXT NOT NULL, PRIMARY KEY(session, project))")
            con.execute("CREATE TABLE IF NOT EXISTS collaborators (id TEXT PRIMARY KEY, project TEXT NOT NULL, member TEXT NOT NULL, joined TEXT NOT NULL, consent TEXT NOT NULL, UNIQUE(project,member))")
            con.execute("CREATE TABLE IF NOT EXISTS handoff_codes (digest TEXT PRIMARY KEY, project TEXT NOT NULL, expires TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 0)")
            con.execute("CREATE TABLE IF NOT EXISTS handoff_attempts (actor TEXT NOT NULL, at TEXT NOT NULL)")
            con.execute("CREATE TABLE IF NOT EXISTS submission_usage (project TEXT NOT NULL, day TEXT NOT NULL, team TEXT NOT NULL, count INTEGER NOT NULL, PRIMARY KEY(project,day,team))")
        self.apply_erasure_journal()
        os.chmod(self.db, 0o600)
        # A process restart cannot silently leave a run active forever.
        from .conversation import recover_interrupted
        with self.connection() as con:
            for row in con.execute("SELECT id, body FROM projects").fetchall():
                item = json.loads(row[1])
                active_import = item.get("_source_import", {}).get("status") in {"queued", "working"}
                state = item.get("conversation") or {}
                if active_import and not state.get("_pending"):
                    state.update(_inflight=False, status="idle", error=None, can_retry=False)
                changed = recover_interrupted(item)
                if item.get("lite", {}).get("status") == "working":
                    item["lite"].update(status="error", stage="Interrupted; saved work is available",
                        job_id=None, error="The service restarted. Retry the saved request to continue.")
                    changed = True
                if active_import:
                    item["_source_import"].update(status="failed", stage="Import interrupted",
                        error="The service restarted. Retry the import; saved answers are unchanged.")
                    changed = True
                for trace in item.get("_model_traces", []):
                    if trace.get("status") == "running":
                        trace.update(status="interrupted", finished_at=now())
                        changed = True
                if item.get("harness", {}).get("status") == "running":
                    item["harness"] = {"status": "failed", "stage": "interrupted", "error": "The server restarted. Your saved work is available. Run the agent again."}
                    changed = True
                if changed:
                    con.execute("UPDATE projects SET body=? WHERE id=?", (json.dumps(item), row[0]))

    def connection(self):
        con = sqlite3.connect(self.db, timeout=15)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA secure_delete=ON")
        return con

    def lock(self, project_id):
        with self._guard:
            return self._locks.setdefault(project_id, threading.Lock())

    def create(self, owner, title="", brief=""):
        identifier = str(uuid.uuid4())
        item = {"id": identifier, "title": title or "Untitled challenge", "brief": brief,
                "created_at": now(), "updated_at": now(), "status": "draft",
                "answers": dict(ANSWERS), "design": {**DESIGN, "exclude_columns": []},
                "dataset": None, "analysis": None, "advice": [], "events": [],
                "prepared": False, "notices": [], "revision": 1,
                "harness": {"status": "idle", "stage": "scope"},
                "_seed": secrets.randbits(31), "_participant": None, "_model_calls": 0}
        self.directory(identifier).mkdir(mode=0o700)
        with self.connection() as con:
            con.execute("INSERT INTO projects VALUES (?,?,?,?,?)", (identifier, owner, now(), None, json.dumps(item)))
        return item

    def directory(self, project_id):
        if str(uuid.UUID(project_id)) != project_id:
            raise ValueError("Invalid project identifier")
        return self.root / project_id

    def get(self, project_id, owner):
        with self.connection() as con:
            row = con.execute("SELECT body FROM projects WHERE id=? AND (owner=? OR EXISTS (SELECT 1 FROM review_grants WHERE session=? AND project=projects.id AND expires>?) OR EXISTS (SELECT 1 FROM collaborators WHERE member=? AND project=projects.id))", (project_id, owner, owner, now(), owner)).fetchone()
        return json.loads(row[0]) if row else None

    def by_token(self, token):
        if not token or len(token) > 100:
            return None
        with self.connection() as con:
            row = con.execute("SELECT body FROM projects WHERE participant=?", (token,)).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, owner):
        with self.connection() as con:
            rows = con.execute("SELECT body, owner=? FROM projects WHERE owner=? OR EXISTS (SELECT 1 FROM review_grants WHERE session=? AND project=projects.id AND expires>?) OR EXISTS (SELECT 1 FROM collaborators WHERE member=? AND project=projects.id) ORDER BY updated_at DESC", (owner, owner, owner, now(), owner)).fetchall()
        return [{**{k: item[k] for k in ("id", "title", "updated_at", "status")}, "role": "owner" if own else "collaborator", "can_delete": bool(own)} for item, own in ((json.loads(r[0]), r[1]) for r in rows)]

    def owns(self, project_id, owner):
        with self.connection() as con:
            return bool(con.execute("SELECT 1 FROM projects WHERE id=? AND owner=?", (project_id, owner)).fetchone())

    def author_label(self, project_id, owner):
        if self.owns(project_id, owner):
            return "Organizer"
        with self.connection() as con:
            row = con.execute("SELECT id FROM collaborators WHERE project=? AND member=?", (project_id, owner)).fetchone()
        if row:
            return "Collaborator " + row[0][:6].upper()
        return "Reviewer"

    def record_erasure(self, project_id, scope="project"):
        """Persist non-content deletion instructions outside restorable snapshots."""
        with self._guard:
            path = self.root / "erasure-journal.json"
            entries = json.loads(path.read_text()) if path.exists() else []
            entries.append({"id": project_id, "at": now(), "scope": scope})
            temporary = path.with_suffix(".tmp")
            with temporary.open("w") as handle:
                os.fchmod(handle.fileno(), 0o600)
                json.dump(entries, handle)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(path)
            directory_fd = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)

    def purge_dependents(self, project_id, *, submissions=True):
        with self.connection() as con:
            tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in ("review_grants", "review_tokens", "submission_tokens", "handoff_codes"):
                if table in tables:
                    con.execute(f"DELETE FROM {table} WHERE project=?", (project_id,))
            if submissions and "draft_submissions" in tables:
                con.execute("INSERT INTO submission_usage(project,day,team,count) SELECT project,day,team,count(*) FROM draft_submissions WHERE project=? GROUP BY project,day,team ON CONFLICT(project,day,team) DO UPDATE SET count=count+excluded.count", (project_id,))
                con.execute("DELETE FROM draft_submissions WHERE project=?", (project_id,))

    def delete(self, project_id):
        self.record_erasure(project_id)
        self.purge_dependents(project_id)
        with self.connection() as con:
            con.execute("DELETE FROM collaborators WHERE project=?", (project_id,))
            con.execute("DELETE FROM submission_usage WHERE project=?", (project_id,))
            con.execute("DELETE FROM projects WHERE id=?", (project_id,))
        if self.directory(project_id).exists():
            shutil.rmtree(self.directory(project_id))
        self.checkpoint()

    def checkpoint(self):
        # Secure-delete clears freed pages; checkpoint removes old WAL snapshots.
        with self.connection() as con:
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def apply_erasure_journal(self):
        """An old database restore cannot make erased projects available again."""
        path = self.root / "erasure-journal.json"
        if not path.exists():
            return
        entries = json.loads(path.read_text())
        if not isinstance(entries, list):
            raise ValueError("Invalid erasure journal. Restore must stop.")
        for entry in entries:
            identifier = str(uuid.UUID(entry["id"]))
            with self.connection() as con:
                row = con.execute("SELECT updated_at FROM projects WHERE id=?", (identifier,)).fetchone()
            if row and entry["scope"] == "content" and row[0] >= entry["at"]:
                continue
            self.purge_dependents(identifier)
            with self.connection() as con:
                con.execute("DELETE FROM collaborators WHERE project=?", (identifier,))
                con.execute("DELETE FROM projects WHERE id=?", (identifier,))
            if self.directory(identifier).exists():
                shutil.rmtree(self.directory(identifier))

    def save(self, item):
        item["updated_at"] = now()
        with self.connection() as con:
            con.execute("UPDATE projects SET updated_at=?, participant=?, body=? WHERE id=?",
                        (item["updated_at"], item.get("_participant"), json.dumps(item, allow_nan=False), item["id"]))


def public_project(item):
    return {k: v for k, v in item.items() if not k.startswith("_")}
