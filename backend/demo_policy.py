"""Fail-closed, sealed synthetic instance; never trusts an upload's synthetic flag."""

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
import time

from fastapi import HTTPException

PURPOSE = "sealed-synthetic-demo-v1"
MAX_SEED_BYTES = 8 * 1024 * 1024


def demo_enabled():
    mode = os.environ.get("LOGISTICS_INSTANCE_MODE", "business")
    if mode not in {"business", "demo"}:
        raise HTTPException(503, "Unknown instance mode; use business or demo explicitly.")
    return mode == "demo"


def demo_paths():
    configured = os.environ.get("LOGISTICS_DEMO_ROOT", "")
    if not configured or not Path(configured).is_absolute():
        raise HTTPException(503, "Demo requires an explicit absolute, separately provisioned LOGISTICS_DEMO_ROOT.")
    root = Path(configured).resolve()
    paths = root / "workspace.sqlite3", root / "history.sqlite3"
    for variable, path in zip(("LOGISTICS_WEB_DB_PATH", "LOGISTICS_DB_PATH"), paths):
        override = os.environ.get(variable)
        if override and Path(override).resolve() != path:
            raise HTTPException(503, "Demo refuses business database overrides. Use its sealed synthetic database pair.")
    if any(p.is_symlink() for p in (Path(configured), *paths, root / "manifest.json")):
        raise HTTPException(503, "Demo seed paths must not be symbolic links.")
    return paths


def validate_demo():
    """Read-only validation before any account store or business request is opened."""
    workspace, history = demo_paths()
    try:
        root = workspace.parent
        manifest_file = root / "manifest.json"
        if manifest_file.stat().st_size > 4096:
            raise ValueError("Manifest too large")
        manifest = json.loads(manifest_file.read_text())
        if manifest["purpose"] != PURPOSE or set(manifest["files"]) != {workspace.name, history.name}:
            raise ValueError("Wrong purpose")
        if sum(p.stat().st_size for p in (workspace, history)) > MAX_SEED_BYTES:
            raise ValueError("Seed storage limit")
        for path in (workspace, history):
            if any(Path(str(path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
                raise ValueError("Seed was not sealed offline")
            if hashlib.sha256(path.read_bytes()).hexdigest() != manifest["files"][path.name]:
                raise ValueError("Seed changed")
        with sqlite3.connect(workspace.as_uri() + "?mode=ro&immutable=1", uri=True) as db:
            identity = db.execute("SELECT instance_id,organization FROM instance_identity WHERE id=1").fetchone()
            purpose = db.execute("SELECT purpose FROM demo_identity WHERE id=1").fetchone()
            if not identity or purpose != (PURPOSE,) or identity[0] != manifest["instance_id"]:
                raise ValueError("Identity mismatch")
            if db.execute("SELECT COUNT(*) FROM access_users").fetchone()[0] or db.execute("SELECT COUNT(*) FROM access_sessions").fetchone()[0]:
                raise ValueError("Accounts cannot be copied into a demo")
            if db.execute("SELECT dataset_id,synthetic FROM web_datasets").fetchall() != [("demo", 1)]:
                raise ValueError("Unexpected dataset")
            # A sealed manifest alone is insufficient to bless a customer dataset.
            from src.decision_demo import with_demo_context
            from src.demo import generate_demo_data
            canonical = with_demo_context(generate_demo_data()).to_json(orient="split", date_format="iso")
            if db.execute("SELECT raw_json FROM web_datasets WHERE dataset_id='demo'").fetchone()[0] != canonical:
                raise ValueError("Not the built-in synthetic source")
            if db.execute("SELECT COUNT(*) FROM planning_imports").fetchone()[0]:
                raise ValueError("Demo cannot contain uploaded planning imports")
            if db.execute("SELECT run_id FROM web_runs").fetchall() != [(manifest["run_id"],)]:
                raise ValueError("Unexpected planning runs")
        with sqlite3.connect(history.as_uri() + "?mode=ro&immutable=1", uri=True) as db:
            if db.execute("SELECT instance_id FROM instance_binding WHERE id=1").fetchone() != (identity[0],):
                raise ValueError("History identity mismatch")
        return {"username": "synthetic-visitor", "role": "viewer", "instance_id": identity[0],
                "organization": identity[1], "read_only_demo": True}
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        raise HTTPException(503, "Synthetic demo seed is missing, changed or incompatible. Rebuild a new demo directory offline; business databases are never accepted.") from exc


def allow_demo_read(path, query):
    allowed = {"/api/health", "/api/ready", "/api/auth/session", "/api/datasets", "/api/workspace", "/api/exceptions",
               "/api/settings", "/api/decisions/defaults", "/api/cases", "/api/cases/export", "/api/evaluation"}
    pattern = r"/api/(?:exports/(?:shipments|exceptions|priority|report|quality)|demo/(?:csv|xlsx)|optimization/runs/(?:latest|[a-f0-9]{32})(?:/export/(?:json|comparison|allocation|candidates))?)"
    if path not in allowed and not re.fullmatch(pattern, path):
        raise HTTPException(403, "Read-only synthetic demo: this operation is available only in a protected business instance.")
    if len(query) > 1024:
        raise HTTPException(413, "Demo query exceeds 1024 bytes.")


class DemoBudget:
    """One worker per demo; global 120/minute, at most two API operations in flight."""
    def __init__(self):
        self.lock = threading.Lock()
        self.started = time.monotonic()
        self.count = self.active = 0

    @contextmanager
    def slot(self):
        with self.lock:
            now = time.monotonic()
            if now - self.started >= 60:
                self.started, self.count = now, 0
            if self.count >= 120 or self.active >= 2:
                raise HTTPException(429, "Synthetic demo request budget reached. Retry shortly.", headers={"Retry-After": "60"})
            self.count += 1; self.active += 1
        try:
            yield
        finally:
            with self.lock:
                self.active -= 1
