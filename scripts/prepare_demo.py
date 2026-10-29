"""Create a NEW sealed synthetic directory, never import/copy customer data/accounts."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from unittest.mock import patch

from backend.access import AccessStore
from backend.demo_policy import PURPOSE, MAX_SEED_BYTES, validate_demo
from backend.optimizer_worker import calculate
from backend.schemas import OptimizationRequest
from backend.store import WorkspaceStore
from src.history import CaseInput, HistoryStore


def prepare(directory):
    root = Path(directory).absolute()
    if root.is_symlink():
        raise ValueError("Use a new directory, not a symbolic link.")
    # Existing paths, even empty ones, are refused; no --force or production reset.
    root.mkdir(parents=True, mode=0o700, exist_ok=False)
    workspace, history = root / "workspace.sqlite3", root / "history.sqlite3"
    environment = dict(LOGISTICS_INSTANCE_MODE="business", LOGISTICS_WEB_DB_PATH=str(workspace), LOGISTICS_DB_PATH=str(history))
    with patch.dict(os.environ, environment):
        access = AccessStore(); identity = access.provision("Synthetic Demo — no business data")
        storage = WorkspaceStore(workspace)
        # These inputs are constructed here, never accepted from an upload or CLI quote.
        result = calculate(OptimizationRequest(count=12, scenario_count=1000, time_limit_seconds=1))
        result["input_mode"] = "synthetic"
        run_id = storage.save_run(json.dumps(result, allow_nan=False))
        HistoryStore(history).create_case(CaseInput("SYN-0027", "Overdue in transit", "Wait and monitor", estimated_cost=0,
            resolution_notes="Synthetic demonstration history only; no real shipment or customer information."))
        with storage.connect() as db:
            db.execute("CREATE TABLE demo_identity(id INTEGER PRIMARY KEY CHECK(id=1),purpose TEXT NOT NULL)")
            db.execute("INSERT INTO demo_identity VALUES (1,?)", (PURPOSE,))
    for path in (workspace, history):
        with sqlite3.connect(path) as db:
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            db.execute("PRAGMA journal_mode=DELETE")
        os.chmod(path, 0o444)
    if sum(p.stat().st_size for p in (workspace, history)) > MAX_SEED_BYTES:
        raise ValueError("Built-in seed exceeded its 8 MiB budget; refusing publication.")
    manifest = dict(purpose=PURPOSE, instance_id=identity["instance_id"], run_id=run_id,
                    provenance="Generated locally from built-in synthetic fixtures only; no accounts, uploads or carrier API",
                    files={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (workspace, history)})
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    os.chmod(root / "manifest.json", 0o444)
    os.chmod(root, 0o555)
    with patch.dict(os.environ, dict(LOGISTICS_INSTANCE_MODE="demo", LOGISTICS_DEMO_ROOT=str(root),
                                    LOGISTICS_WEB_DB_PATH=str(workspace), LOGISTICS_DB_PATH=str(history))):
        validate_demo()
    return {"directory": str(root), "sealed": True, "accounts": 0, "run_id": run_id}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", help="New versioned directory; existing paths are never overwritten")
    args = parser.parse_args()
    print(json.dumps(prepare(args.directory), indent=2))


if __name__ == "__main__":
    main()
