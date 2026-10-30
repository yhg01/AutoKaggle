"""Private local storage; ownership checks are part of every organizer lookup."""
from __future__ import annotations

import json
import os
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
        os.chmod(self.db, 0o600)
        # A process restart cannot silently leave a run active forever.
        from .conversation import recover_interrupted
        with self.connection() as con:
            for row in con.execute("SELECT id, body FROM projects").fetchall():
                item = json.loads(row[1])
                changed = recover_interrupted(item)
                if item.get("harness", {}).get("status") == "running":
                    item["harness"] = {"status": "failed", "stage": "interrupted", "error": "The server restarted. Your saved work is available. Run the agent again."}
                    changed = True
                if changed:
                    con.execute("UPDATE projects SET body=? WHERE id=?", (json.dumps(item), row[0]))

    def connection(self):
        con = sqlite3.connect(self.db, timeout=15)
        con.execute("PRAGMA journal_mode=WAL")
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
            row = con.execute("SELECT body FROM projects WHERE id=? AND (owner=? OR EXISTS (SELECT 1 FROM review_grants WHERE session=? AND project=projects.id AND expires>?))", (project_id, owner, owner, now())).fetchone()
        return json.loads(row[0]) if row else None

    def by_token(self, token):
        if not token or len(token) > 100:
            return None
        with self.connection() as con:
            row = con.execute("SELECT body FROM projects WHERE participant=?", (token,)).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, owner):
        with self.connection() as con:
            rows = con.execute("SELECT body FROM projects WHERE owner=? OR EXISTS (SELECT 1 FROM review_grants WHERE session=? AND project=projects.id AND expires>?) ORDER BY updated_at DESC", (owner, owner, now())).fetchall()
        return [{k: item[k] for k in ("id", "title", "updated_at", "status")} for item in map(lambda r: json.loads(r[0]), rows)]

    def save(self, item):
        item["updated_at"] = now()
        with self.connection() as con:
            con.execute("UPDATE projects SET updated_at=?, participant=?, body=? WHERE id=?",
                        (item["updated_at"], item.get("_participant"), json.dumps(item, allow_nan=False), item["id"]))


def public_project(item):
    return {k: v for k, v in item.items() if not k.startswith("_")}
