"""Production web/browser audit with temporary SQLite and an actual API restart."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.request

from scripts.start_web import ROOT, WebServers


def get(path):
    with urllib.request.urlopen("http://127.0.0.1:8000/api" + path, timeout=20) as response:
        return json.load(response)


def main():
    output = ROOT / "artifacts/premium-browser"
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="logistics-premium-audit-") as folder:
        environment = dict(LOGISTICS_WEB_DB_PATH=str(Path(folder) / "workspace.sqlite3"),
                           LOGISTICS_DB_PATH=str(Path(folder) / "history.sqlite3"),
                           APP_BASE_URL="http://127.0.0.1:3100")
        with (output / "servers.log").open("w") as log:
            with WebServers(port=3100, environment=environment, log=log) as servers:
                result = subprocess.run([sys.executable, "tests/browser_premium.py"], cwd=ROOT,
                                        env=dict(os.environ, **environment), capture_output=True, text=True, timeout=600)
                (output / "browser.log").write_text(result.stdout + result.stderr, encoding="utf-8")
                print(result.stdout, flush=True)
                if result.returncode:
                    print(result.stderr, file=sys.stderr)
                    raise RuntimeError("Premium browser audit failed; see artifacts/premium-browser/browser.log.")
                before = get("/cases")
                saved_run = get("/optimization/runs/latest")
                datasets = get("/datasets")
                settings = get("/settings")
                assert len(before) == 1 and before[0]["actual_cost"] == 470 and before[0]["resolution_status"] == "Resolved"
                pid = servers.api.pid
                servers.restart_api()
                assert pid != servers.api.pid
                assert get("/cases") == before
                assert get("/optimization/runs/latest")["run_id"] == saved_run["run_id"]
                assert get("/datasets") == datasets
                assert get("/settings") == settings
                evidence = json.loads((ROOT / "docs/premium_browser_evidence.json").read_text())
                evidence["cold_restart"] = {"passed": True, "api_pid_before": pid, "api_pid_after": servers.api.pid,
                                             "cases_preserved": len(before), "datasets_preserved": len(datasets),
                                             "optimization_run_preserved": saved_run["run_id"]}
                (ROOT / "docs/premium_browser_evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
                print("PASS: actual API process restart preserves cases, uploaded datasets, settings and optimization run.", flush=True)


if __name__ == "__main__":
    main()
