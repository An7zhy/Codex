"""Run original premium regression and Sprint 2 browser operations on isolated DBs."""

import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
from unittest.mock import patch

from backend.access import AccessStore
from scripts.start_web import ROOT, WebServers


def main():
    output, docs = ROOT / "artifacts/sprint2", ROOT / "docs/sprint2"
    output.mkdir(parents=True, exist_ok=True); docs.mkdir(parents=True, exist_ok=True)
    for script, label in (("browser_premium.py", "premium_regression"), ("browser_sprint2.py", "uploaded_flow")):
        with tempfile.TemporaryDirectory(prefix="logistics-sprint2-") as folder:
            password = secrets.token_urlsafe(24)
            environment = dict(LOGISTICS_WEB_DB_PATH=str(Path(folder) / "workspace.sqlite3"), LOGISTICS_DB_PATH=str(Path(folder) / "history.sqlite3"),
                LOGISTICS_ALLOWED_ORIGINS="http://127.0.0.1:3100", LOGISTICS_COOKIE_SECURE="0", LOGISTICS_PILOT_MODE="0",
                APP_BASE_URL="http://127.0.0.1:3100", PYTHONPATH=str(ROOT), BROWSER_TEST_USERNAME="sprint2-admin", BROWSER_TEST_PASSWORD=password,
                BROWSER_OUTPUT_DIR=str(output), BROWSER_SCREENSHOT_DIR=str(output / "screenshots"), BROWSER_EVIDENCE_PATH=str(docs / f"{label}.json"))
            with patch.dict(os.environ, environment):
                access = AccessStore(); access.provision("Sprint 2 isolated browser organization")
                for name, role in (("sprint2-admin", "admin"), ("sprint2-operator", "operator"), ("sprint2-viewer", "viewer")):
                    access.set_user(name, password, role)
            with (output / f"{label}-servers.log").open("w") as log, WebServers(port=3100, environment=environment, log=log) as servers:
                result = subprocess.run([sys.executable, str(ROOT / "tests" / script)], cwd=ROOT, env=dict(os.environ, **environment),
                    capture_output=True, text=True, timeout=600)
                (output / f"{label}.log").write_text(result.stdout + result.stderr)
                if result.returncode:
                    raise RuntimeError(f"{script} failed; inspect artifacts/sprint2/{label}.log")
                print(f"PASS: {script}", flush=True)
                if label == "uploaded_flow":
                    # The browser saves upload/run IDs, not credentials. Verify a real restart.
                    evidence = json.loads((docs / "uploaded_flow.json").read_text())
                    prior_pid = servers.api.pid; servers.restart_api()
                    assert prior_pid != servers.api.pid
                    follow = subprocess.run([sys.executable, str(ROOT / "tests/browser_sprint2.py"), "--restart-check"], cwd=ROOT,
                        env=dict(os.environ, **environment), capture_output=True, text=True, timeout=120)
                    (output / "restart.log").write_text(follow.stdout + follow.stderr)
                    assert follow.returncode == 0, "Restart recheck failed; inspect artifacts/sprint2/restart.log"
                    evidence = json.loads((docs / "uploaded_flow.json").read_text())
                    evidence["actual_api_process_restart"] = True
                    (docs / "uploaded_flow.json").write_text(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
