"""Production build browser regression and repair-specific checks on disposable DBs."""

import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
from unittest.mock import patch

import httpx

from backend.access import AccessStore, COOKIE
from scripts.start_web import ROOT, WebServers


def main():
    output = ROOT / "artifacts/hardening"
    docs = ROOT / "docs/hardening"
    output.mkdir(parents=True, exist_ok=True); docs.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="logistics-hardening-") as folder:
        password = secrets.token_urlsafe(24)
        environment = dict(LOGISTICS_WEB_DB_PATH=str(Path(folder) / "workspace.sqlite3"),
            LOGISTICS_DB_PATH=str(Path(folder) / "history.sqlite3"), LOGISTICS_ALLOWED_ORIGINS="http://127.0.0.1:3100",
            LOGISTICS_COOKIE_SECURE="0", LOGISTICS_PILOT_MODE="0", APP_BASE_URL="http://127.0.0.1:3100",
            PYTHONPATH=str(ROOT), BROWSER_TEST_USERNAME="browser-admin", BROWSER_TEST_PASSWORD=password,
            BROWSER_OUTPUT_DIR=str(output), BROWSER_SCREENSHOT_DIR=str(output / "premium-screenshots"),
            BROWSER_EVIDENCE_PATH=str(docs / "premium_regression.json"))
        with patch.dict(os.environ, environment):
            access = AccessStore(); access.provision("Isolated browser pilot")
            for name, role in (("browser-admin", "admin"), ("browser-viewer", "viewer"), ("browser-operator", "operator")):
                access.set_user(name, password, role)
            token = access.login("browser-admin", password)
        with (output / "servers.log").open("w") as log, WebServers(port=3100, environment=environment, log=log) as servers:
            result = subprocess.run([sys.executable, "tests/browser_premium.py"], cwd=ROOT,
                env=dict(os.environ, **environment), capture_output=True, text=True, timeout=600)
            (output / "premium.log").write_text(result.stdout + result.stderr)
            if result.returncode:
                raise RuntimeError("Premium regression failed; inspect artifacts/hardening/premium.log")
            print("PASS: full premium browser regression (authenticated).", flush=True)
            with httpx.Client(base_url="http://127.0.0.1:8000", cookies={COOKIE: token}) as client:
                before = {route: client.get("/api/" + route).json() for route in ("cases", "datasets", "settings", "optimization/runs/latest")}
                pid = servers.api.pid; servers.restart_api()
                after = {route: client.get("/api/" + route).json() for route in before}
                assert before == after and pid != servers.api.pid
                assert client.get("/api/auth/session").status_code == 200
                (docs / "restart.json").write_text(json.dumps({"passed": True, "actual_api_process_changed": True,
                    "cases": len(after["cases"]), "datasets": len(after["datasets"]), "session_persisted": True,
                    "settings_and_run_unchanged": True}, indent=2))
            result = subprocess.run([sys.executable, "tests/browser_hardening.py"], cwd=ROOT,
                env=dict(os.environ, **environment), capture_output=True, text=True, timeout=600)
            (output / "hardening.log").write_text(result.stdout + result.stderr)
            if result.returncode:
                raise RuntimeError("Repair-specific browser checks failed; inspect artifacts/hardening/hardening.log")
            print(result.stdout, flush=True)


if __name__ == "__main__":
    main()
