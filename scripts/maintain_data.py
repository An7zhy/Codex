"""Offline two-database backup/restore and explicit retention, never live WAL copying.

Stop BOTH FastAPI/Next and Streamlit, then pass --offline-confirmed. Restore
always creates a NEW directory, verifies hashes/identity/integrity and revokes
sessions. Operator must choose the restored database paths; no silent overwrite.
"""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3

from backend.access import paths


def assert_offline():
    for port in (8000, 8501):
        with socket.socket() as sock:
            sock.settimeout(.2)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                raise ValueError(f"Port {port} is active. Stop both interfaces before offline maintenance.")


def check_database(path):
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Database integrity check failed.")
        names = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return {name: db.execute('SELECT COUNT(*) FROM "' + name.replace('"', '""') + '"').fetchone()[0] for name in names}


def identities(workspace, history):
    with sqlite3.connect(workspace.as_uri() + "?mode=ro", uri=True) as db, sqlite3.connect(history.as_uri() + "?mode=ro", uri=True) as hd:
        first = db.execute("SELECT instance_id FROM instance_identity WHERE id=1").fetchone()
        second = hd.execute("SELECT instance_id FROM instance_binding WHERE id=1").fetchone()
        if not first or first != second:
            raise ValueError("Backup database identities do not match.")
        return first[0]


def copy_database(source, destination):
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as db, sqlite3.connect(destination) as out:
        db.backup(out)
    os.chmod(destination, 0o600)


def backup(destination):
    sources = [path.resolve() for path in paths()]
    instance_id = identities(*sources)
    destination = Path(destination).resolve()
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(), "instance_id": instance_id,
                "scope": "Offline, both interfaces stopped; two SQLite native snapshots", "files": {}}
    for source, name in zip(sources, ("workspace.sqlite3", "history.sqlite3")):
        out = destination / name
        copy_database(source, out)
        manifest["files"][name] = {"sha256": hashlib.sha256(out.read_bytes()).hexdigest(), "counts": check_database(out)}
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    os.chmod(destination / "manifest.json", 0o600)
    return manifest


def restore(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    manifest = json.loads((source / "manifest.json").read_text())
    for name in ("workspace.sqlite3", "history.sqlite3"):
        item = source / name
        if hashlib.sha256(item.read_bytes()).hexdigest() != manifest["files"][name]["sha256"]:
            raise ValueError("Backup checksum mismatch. Restore refused.")
        if check_database(item) != manifest["files"][name]["counts"]:
            raise ValueError("Backup record counts differ from manifest.")
    if identities(source / "workspace.sqlite3", source / "history.sqlite3") != manifest["instance_id"]:
        raise ValueError("Backup instance differs from manifest.")
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    for name in ("workspace.sqlite3", "history.sqlite3"):
        copy_database(source / name, destination / name)
    with sqlite3.connect(destination / "workspace.sqlite3") as db:
        db.execute("DELETE FROM access_sessions")
        db.execute("DELETE FROM access_rates")
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='solver_lease'").fetchone():
            db.execute("DELETE FROM solver_lease")
    return {"restored": str(destination), "instance_id": manifest["instance_id"], "sessions_revoked": True,
            "integrity": {name: check_database(destination / name) for name in ("workspace.sqlite3", "history.sqlite3")}}


def retain(dataset_days=30, run_days=30, case_days=180):
    workspace, history = [path.resolve() for path in paths()]
    identities(workspace, history)
    now = datetime.now(timezone.utc)
    if min(dataset_days, run_days, case_days) < 1:
        raise ValueError("Retention periods must be positive whole days.")
    cutoffs = [(now - timedelta(days=days)).isoformat() for days in (dataset_days, run_days, case_days)]
    with sqlite3.connect(workspace) as db:
        db.execute("ATTACH DATABASE ? AS history", (str(history),))
        cases = db.execute("DELETE FROM history.cases WHERE created_at<? OR (json_valid(priority_snapshot_json) AND json_extract(priority_snapshot_json,'$.dataset.dataset_id') IN (SELECT dataset_id FROM web_datasets WHERE dataset_id!='demo' AND created_at<?))", (cutoffs[2], cutoffs[0])).rowcount
        datasets = db.execute("DELETE FROM web_datasets WHERE dataset_id!='demo' AND created_at<?", (cutoffs[0],)).rowcount
        runs = db.execute("DELETE FROM web_runs WHERE created_at<?", (cutoffs[1],)).rowcount
    # Reclaim deleted pages; logical deletion does not expire external backups.
    for path in (workspace, history):
        with sqlite3.connect(path) as db:
            db.execute("VACUUM")
    return {"datasets_deleted": datasets, "runs_deleted": runs, "cases_deleted": cases}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline-confirmed", action="store_true", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("backup"); b.add_argument("destination")
    r = sub.add_parser("restore"); r.add_argument("source"); r.add_argument("destination")
    p = sub.add_parser("retain")
    p.add_argument("--dataset-days", type=int, default=30); p.add_argument("--run-days", type=int, default=30); p.add_argument("--case-days", type=int, default=180)
    args = parser.parse_args()
    assert_offline()
    result = backup(args.destination) if args.command == "backup" else restore(args.source, args.destination) if args.command == "restore" else retain(args.dataset_days, args.run_days, args.case_days)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
