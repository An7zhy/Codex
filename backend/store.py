"""Small persistent workspace store, separate from the existing case database."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid
from fastapi import HTTPException

import pandas as pd

from src.decision_demo import with_demo_context
from src.demo import DEMO_AS_OF, generate_demo_data
from src.priority import PriorityConfig


class WorkspaceStore:
    def __init__(self, path):
        self.path = Path(path)
        from backend.demo_policy import demo_enabled, demo_paths, validate_demo
        self.read_only = demo_enabled()
        if self.read_only:
            validate_demo()
            if self.path.resolve() != demo_paths()[0]:
                raise HTTPException(503, "Demo cannot open another workspace.")
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS web_datasets (
                    dataset_id TEXT PRIMARY KEY, name TEXT NOT NULL, synthetic INTEGER NOT NULL,
                    as_of TEXT NOT NULL, raw_json TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS web_settings (setting_key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS web_runs (
                    run_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS planning_imports (
                    import_id TEXT PRIMARY KEY, status TEXT NOT NULL, created_at TEXT NOT NULL,
                    created_by TEXT NOT NULL, confirmed_at TEXT, confirmed_by TEXT,
                    confirmation TEXT NOT NULL, record_json TEXT NOT NULL);
            """)
            # Additive migration: preserve old values and give them a durable base version.
            db.execute("BEGIN IMMEDIATE")
            columns = {row[1] for row in db.execute("PRAGMA table_info(web_settings)")}
            if "version" not in columns:
                db.execute("ALTER TABLE web_settings ADD COLUMN version INTEGER NOT NULL DEFAULT 1")
            db.execute("""CREATE TABLE IF NOT EXISTS setting_changes (
                change_id INTEGER PRIMARY KEY, setting_key TEXT NOT NULL,
                old_version INTEGER NOT NULL, new_version INTEGER NOT NULL,
                actor TEXT NOT NULL, changed_at TEXT NOT NULL, diff_json TEXT NOT NULL,
                UNIQUE(setting_key,new_version))""")
            db.execute("INSERT OR IGNORE INTO web_settings(setting_key,value_json,version) VALUES ('priority',?,1)",
                       (json.dumps(PriorityConfig.load().to_dict(), allow_nan=False),))
        # INSERT OR IGNORE is safe under simultaneous first loads.
        if not self.has_dataset("demo"):
            self.save_dataset(with_demo_context(generate_demo_data()), "Synthetic Demo Data", True,
                              str(DEMO_AS_OF), dataset_id="demo")

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True, timeout=15) if self.read_only else sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def has_dataset(self, dataset_id):
        with self.connect() as db:
            return db.execute("SELECT 1 FROM web_datasets WHERE dataset_id=?", (dataset_id,)).fetchone() is not None

    def save_dataset(self, frame, name, synthetic, as_of, dataset_id=None):
        dataset_id = dataset_id or uuid.uuid4().hex
        payload = frame.to_json(orient="split", date_format="iso")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.check_quota(db, len(payload.encode()), "web_datasets", 1000)
            db.execute("INSERT OR IGNORE INTO web_datasets VALUES (?,?,?,?,?,?)",
                       (dataset_id, name, int(synthetic), as_of, payload,
                        datetime.now(timezone.utc).isoformat()))
        return dataset_id

    def dataset(self, dataset_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM web_datasets WHERE dataset_id=?", (dataset_id,)).fetchone()
        if row is None:
            raise LookupError("Dataset not found. Choose Synthetic Demo Data or upload a file.")
        metadata = dict(row)
        raw = json.loads(metadata.pop("raw_json"))
        metadata["synthetic"] = bool(metadata["synthetic"])
        return metadata, pd.DataFrame(raw["data"], columns=raw["columns"])

    def datasets(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT dataset_id,name,synthetic,as_of,created_at FROM web_datasets ORDER BY created_at DESC")]

    def setting(self, key, fallback):
        with self.connect() as db:
            row = db.execute("SELECT value_json FROM web_settings WHERE setting_key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else fallback

    def setting_snapshot(self, key):
        with self.connect() as db:
            row = db.execute("SELECT value_json,version FROM web_settings WHERE setting_key=?", (key,)).fetchone()
        if row is None:
            raise LookupError("Setting not found.")
        return {"priority": json.loads(row["value_json"]), "version": row["version"]}

    def save_setting(self, key, value, *, expected_version, actor):
        if type(expected_version) is not int or expected_version < 1 or not isinstance(actor, str) or not actor.strip():
            raise ValueError("An integer base version and authenticated actor are required.")
        payload = json.dumps(value, allow_nan=False)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT value_json,version FROM web_settings WHERE setting_key=?", (key,)).fetchone()
            if row is None:
                raise LookupError("Setting not found.")
            if row["version"] != expected_version:
                raise HTTPException(409, "Settings changed in another session. Your draft was not saved. Reload latest settings and review your changes.")
            if db.execute("SELECT COUNT(*) FROM setting_changes").fetchone()[0] >= 10000:
                raise HTTPException(507, "Settings audit quota reached. Ask an administrator to archive the configuration history before continuing.")
            changed = db.execute("UPDATE web_settings SET value_json=?,version=version+1 WHERE setting_key=? AND version=?", (payload,key,expected_version))
            if changed.rowcount != 1:
                raise HTTPException(409, "Settings changed. Reload latest settings before saving.")
            def flatten(item, prefix=""):
                result = {}
                for name, val in item.items():
                    field = f"{prefix}.{name}" if prefix else name
                    result.update(flatten(val, field) if isinstance(val, dict) else {field: val})
                return result
            before, after = flatten(json.loads(row["value_json"])), flatten(value)
            diff = {name: {"before": before.get(name), "after": after.get(name)} for name in sorted(before.keys() | after.keys()) if before.get(name) != after.get(name)}
            db.execute("INSERT INTO setting_changes(setting_key,old_version,new_version,actor,changed_at,diff_json) VALUES (?,?,?,?,?,?)",
                       (key,expected_version,expected_version+1,actor,datetime.now(timezone.utc).isoformat(),json.dumps(diff,allow_nan=False)))
        return {"priority": value, "version": expected_version + 1}

    def setting_history(self, limit, offset):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM setting_changes WHERE setting_key='priority' ORDER BY new_version DESC LIMIT ? OFFSET ?", (limit,offset)).fetchall()
        return [{**dict(row), "diff": json.loads(row["diff_json"])} for row in rows]

    def save_run(self, payload, planning_import_id=None):
        run_id = uuid.uuid4().hex
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if planning_import_id is not None:
                if not db.execute("SELECT 1 FROM planning_imports WHERE import_id=? AND status='confirmed'", (planning_import_id,)).fetchone():
                    raise HTTPException(409, "Planning source was deleted while solving; no result has been saved.")
            self.check_quota(db, len(payload.encode()), "web_runs", 200)
            db.execute("INSERT INTO web_runs VALUES (?,?,?)", (run_id, payload, datetime.now(timezone.utc).isoformat()))
        return run_id

    @staticmethod
    def check_quota(db, additional, table, limit):
        sizes = db.execute("SELECT COALESCE(SUM(length(CAST(raw_json AS BLOB))),0) FROM web_datasets").fetchone()[0]
        sizes += db.execute("SELECT COALESCE(SUM(length(CAST(payload_json AS BLOB))),0) FROM web_runs").fetchone()[0]
        sizes += db.execute("SELECT COALESCE(SUM(length(CAST(record_json AS BLOB))),0) FROM planning_imports").fetchone()[0]
        if sizes + additional > 256 * 1024 * 1024 or db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] >= limit:
            raise HTTPException(507, "Workspace retention quota reached (1000 datasets / 200 runs / 100 planning imports / 256 MiB JSON). Ask an administrator to delete or expire records.")

    def run(self, run_id=None, input_mode=None):
        with self.connect() as db:
            row = db.execute("SELECT * FROM web_runs WHERE run_id=?", (run_id,)).fetchone() if run_id else db.execute(
                "SELECT * FROM web_runs WHERE (? IS NULL OR COALESCE(json_extract(payload_json,'$.input_mode'),'synthetic')=?) ORDER BY created_at DESC,run_id DESC LIMIT 1", (input_mode, input_mode)).fetchone()
        if not row:
            raise LookupError("No optimization run yet. Run an allocation to generate analytics.")
        return {"run_id": row["run_id"], "created_at": row["created_at"], **json.loads(row["payload_json"])}

    def save_import(self, record, actor):
        import hashlib
        import_id = uuid.uuid4().hex
        payload = json.dumps(record, sort_keys=True, allow_nan=False)
        fingerprint = hashlib.sha256(payload.encode()).hexdigest()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.check_quota(db, len(payload.encode()), "planning_imports", 100)
            db.execute("INSERT INTO planning_imports VALUES (?,?,?,?,NULL,NULL,?,?)", (
                import_id, "previewed" if record["validation"]["valid"] else "invalid", datetime.now(timezone.utc).isoformat(), actor, fingerprint, payload))
        return self.planning_import(import_id)

    def planning_import(self, import_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM planning_imports WHERE import_id=?", (import_id,)).fetchone()
        if not row:
            raise LookupError("Planning import not found in this organization instance.")
        item = dict(row)
        item["record"] = json.loads(item.pop("record_json"))
        return item

    def planning_imports(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT import_id,status,created_at,created_by,confirmed_at,confirmed_by FROM planning_imports ORDER BY created_at DESC,import_id DESC")]

    def confirm_import(self, import_id, fingerprint, actor):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status,confirmation FROM planning_imports WHERE import_id=?", (import_id,)).fetchone()
            if not row:
                raise LookupError("Planning import not found in this organization instance.")
            if row["status"] == "invalid" or row["confirmation"] != fingerprint:
                raise HTTPException(409, "Only a valid, unchanged preview can be confirmed. Correct and preview the inputs again.")
            db.execute("UPDATE planning_imports SET status='confirmed',confirmed_at=?,confirmed_by=? WHERE import_id=? AND status='previewed'",
                       (datetime.now(timezone.utc).isoformat(), actor, import_id))
        return self.planning_import(import_id)
