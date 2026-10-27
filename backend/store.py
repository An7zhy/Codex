"""Small persistent workspace store, separate from the existing case database."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid

import pandas as pd

from src.decision_demo import with_demo_context
from src.demo import DEMO_AS_OF, generate_demo_data


class WorkspaceStore:
    def __init__(self, path):
        self.path = Path(path)
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
            """)
        # INSERT OR IGNORE is safe under simultaneous first loads.
        if not self.has_dataset("demo"):
            self.save_dataset(with_demo_context(generate_demo_data()), "Synthetic Demo Data", True,
                              str(DEMO_AS_OF), dataset_id="demo")

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=15)
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
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO web_datasets VALUES (?,?,?,?,?,?)",
                       (dataset_id, name, int(synthetic), as_of, frame.to_json(orient="split", date_format="iso"),
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
                "SELECT dataset_id,name,synthetic,as_of,created_at FROM web_datasets ORDER BY created_at DESC LIMIT 100")]

    def setting(self, key, fallback):
        with self.connect() as db:
            row = db.execute("SELECT value_json FROM web_settings WHERE setting_key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else fallback

    def save_setting(self, key, value):
        payload = json.dumps(value, allow_nan=False)
        with self.connect() as db:
            db.execute("INSERT INTO web_settings VALUES (?,?) ON CONFLICT(setting_key) DO UPDATE SET value_json=excluded.value_json", (key, payload))

    def save_run(self, payload):
        run_id = uuid.uuid4().hex
        with self.connect() as db:
            db.execute("INSERT INTO web_runs VALUES (?,?,?)", (run_id, payload, datetime.now(timezone.utc).isoformat()))
        return run_id

    def run(self, run_id=None):
        with self.connect() as db:
            row = db.execute("SELECT * FROM web_runs WHERE run_id=?", (run_id,)).fetchone() if run_id else db.execute(
                "SELECT * FROM web_runs ORDER BY created_at DESC LIMIT 1").fetchone()
        if not row:
            raise LookupError("No optimization run yet. Run an allocation to generate analytics.")
        return {"run_id": row["run_id"], "created_at": row["created_at"], **json.loads(row["payload_json"])}
