"""Rehearse actual offline backup/restore CLI and fresh login on a synthetic instance."""

import asyncio
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

import httpx

from backend.access import AccessStore, COOKIE
from backend.main import app
from backend.optimizer_worker import calculate
from backend.schemas import OptimizationRequest
from backend.store import WorkspaceStore
from scripts.maintain_data import check_database
from src.history import CaseInput, HistoryStore
from src.priority import PriorityConfig
from scripts.start_web import ROOT


def main():
    with tempfile.TemporaryDirectory(prefix="logistics-recovery-") as folder:
        root = Path(folder)
        env = dict(LOGISTICS_WEB_DB_PATH=str(root / "original/workspace.sqlite3"),
                   LOGISTICS_DB_PATH=str(root / "original/history.sqlite3"), LOGISTICS_ALLOWED_ORIGINS="http://recovery",
                   LOGISTICS_COOKIE_SECURE="0", LOGISTICS_PILOT_MODE="0")
        password = secrets.token_urlsafe(24)
        with patch.dict(os.environ, env):
            access = AccessStore(); access.provision("Synthetic recovery rehearsal")
            access.set_user("recovery-admin", password, "admin")
            old_token = access.login("recovery-admin", password)
            workspace = WorkspaceStore(access.path)
            cfg = PriorityConfig.load().to_dict(); cfg["weights"]["financial"] = 100
            workspace.save_setting("priority", cfg)
            history = HistoryStore(access.history_path)
            case_id = history.create_case(CaseInput("SYN-0027", "Overdue in transit", "Wait and monitor", estimated_cost=0, estimated_delay=72))
            run_id = workspace.save_run(json.dumps(calculate(OptimizationRequest(scenario_count=100)), allow_nan=False))
        commands = []
        started = time.perf_counter()
        for args in (("backup", str(root / "backup")), ("restore", str(root / "backup"), str(root / "restored"))):
            result = subprocess.run([sys.executable, "-m", "scripts.maintain_data", "--offline-confirmed", *args],
                cwd=ROOT, env=dict(os.environ, **env), capture_output=True, text=True, timeout=30)
            assert result.returncode == 0, result.stderr
            commands.append({"operation": args[0], "exit_code": result.returncode, "result": json.loads(result.stdout)})
        elapsed = time.perf_counter() - started
        restored = dict(env, LOGISTICS_WEB_DB_PATH=str(root / "restored/workspace.sqlite3"), LOGISTICS_DB_PATH=str(root / "restored/history.sqlite3"))
        async def verify():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://recovery", headers={"Origin": "http://recovery"}) as client:
                client.cookies.set(COOKIE, old_token, path="/api")
                assert (await client.get("/api/cases")).status_code == 401
                client.cookies.clear()
                login = await client.post("/api/auth/login", json={"username": "recovery-admin", "password": password})
                assert login.status_code == 200
                data = (await client.get("/api/workspace")).json()
                assert data["kpis"]["total_shipments"] == 158 and data["kpis"]["total_shipping_cost"] == 539830.75
                cases = (await client.get("/api/cases")).json()
                assert len(cases) == 1 and cases[0]["case_id"] == case_id
                assert (await client.get("/api/settings")).json()["priority"]["weights"]["financial"] == 100
                assert (await client.get("/api/optimization/runs/latest")).json()["run_id"] == run_id
                return data["kpis"]
        with patch.dict(os.environ, restored):
            kpis = asyncio.run(verify())
        # Persist facts, never temporary paths, tokens, passwords or DB contents.
        evidence = {"passed": True, "data": "Synthetic recovery rehearsal only", "commands": [
            {"command": "python -m scripts.maintain_data --offline-confirmed " + row["operation"] + " <temporary paths>",
             "exit_code": row["exit_code"]} for row in commands],
            "native_snapshot_counts": commands[0]["result"]["files"],
            "backup_and_restore_cli_seconds": elapsed,
            "restored_kpis": kpis, "old_sessions_rejected": True, "fresh_login_verified": True,
            "case_settings_run_preserved": True, "scope": "Stopped synthetic instance; not live cross-database recovery or a production RPO/RTO guarantee"}
        (ROOT / "docs/hardening/backup_restore.json").write_text(json.dumps(evidence, indent=2))
        print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
