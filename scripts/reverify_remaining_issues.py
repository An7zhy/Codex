"""Read-only product audit: bounded synthetic probes and existing browser assertions.

Only temporary organization databases are written. Existing test assertions and
historical evidence files are left untouched. No production feature is changed.
"""

import argparse
import asyncio
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
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
import pandas as pd

from backend.access import AccessStore, COOKIE
from backend.main import app
from backend.store import WorkspaceStore
from scripts.audit_readiness import sample
from scripts.maintain_data import backup, restore
from scripts.start_web import ROOT, WebServers
from src.decisions import default_assumptions
from src.transport.templates import template_tables, workbook_bytes

DOCS = ROOT / "docs/remaining-issues"
ARTIFACTS = ROOT / "artifacts/remaining-issues"


def probes(offline_cli=False):
    evidence = {"completed": False, "checked_at_utc": datetime.now(timezone.utc).isoformat(),
                "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "data_scope": "Authored synthetic fixtures; no actual customer databases or freight records", "observations": {}}
    observations = evidence["observations"]
    with tempfile.TemporaryDirectory(prefix="logistics-remaining-") as folder:
        root = Path(folder)
        environment = dict(LOGISTICS_WEB_DB_PATH=str(root / "a/workspace.sqlite3"), LOGISTICS_DB_PATH=str(root / "a/history.sqlite3"),
                           LOGISTICS_ALLOWED_ORIGINS="http://audit", LOGISTICS_COOKIE_SECURE="0", LOGISTICS_PILOT_MODE="0")
        password = secrets.token_urlsafe(24)
        with patch.dict(os.environ, environment):
            access = AccessStore(); access.provision("Synthetic audit A")
            tokens = {}
            for role in ("admin", "operator", "viewer"):
                access.set_user(role, password, role); tokens[role] = access.login(role, password)
            access.set_user("second-admin", password, "admin")
            tokens["second-admin"] = access.login("second-admin", password)

            def request(method, path, role="admin", **kwargs):
                async def send():
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                            base_url="http://audit", cookies={COOKIE: tokens[role]} if role else {}, headers={"Origin": "http://audit"}) as client:
                        return await client.request(method, path, **kwargs)
                return asyncio.run(send())

            def upload(frame):
                content = frame.to_csv(index=False).encode()
                arguments = dict(files={"file": ("synthetic-audit.csv", content)}, data={"as_of": "2026-10-02"})
                preview = request("POST", "/api/datasets/preview", **arguments)
                assert preview.status_code == 200, preview.text
                accepted = request("POST", "/api/datasets", files=arguments["files"],
                                   data={**arguments["data"], "confirmed": preview.json()["confirmation"]})
                assert accepted.status_code == 201, accepted.text
                return accepted.json()["dataset_id"], preview.json()

            routes = [("GET", "/api/workspace"), ("GET", "/api/datasets"), ("GET", "/api/exceptions"),
                      ("GET", "/api/settings"), ("GET", "/api/cases"), ("GET", "/api/cases/export"),
                      ("GET", "/api/exports/report"), ("GET", "/api/optimization/runs/latest"),
                      ("GET", "/api/planning/templates/xlsx"), ("GET", "/api/planning/imports"),
                      ("POST", "/api/datasets"), ("POST", "/api/cases"), ("POST", "/api/planning/imports/preview"),
                      ("POST", "/api/planning/runs"), ("PUT", "/api/settings/priority"), ("DELETE", "/api/planning/imports/id")]
            statuses = {method + " " + path: request(method, path, role=None).status_code for method, path in routes}
            assert set(statuses.values()) == {401}
            observations["PR-01_anonymous"] = statuses
            writes = [("POST", "/api/datasets"), ("POST", "/api/planning/runs"), ("POST", "/api/cases"),
                      ("PATCH", "/api/cases/id"), ("PUT", "/api/settings/priority"), ("DELETE", "/api/datasets/id")]
            denied = {method + " " + path: request(method, path, role="viewer").status_code for method, path in writes}
            assert set(denied.values()) == {403}
            observations["PR-01_viewer"] = denied

            frame = pd.DataFrame([sample(shipment_id="USD", currency="USD"),
                                  sample(shipment_id="EUR", currency="EUR", shipping_cost=99999),
                                  sample(shipment_id="BLANK", currency="")])
            dataset, preview = upload(frame)
            workspace = request("GET", "/api/workspace", params={"dataset_id": dataset}).json()
            assert workspace["kpis"]["total_shipping_cost"] == 100
            assert workspace["kpis"]["cost_eligible_shipments"] == 1
            assert sum(row["code"] == "unsupported_currency" for row in workspace["issues"]) == 2
            observations["PR-04"] = {"cost_usd": 100, "eligible_costs": 1, "currency_issues": 2}

            dates, preview = upload(pd.DataFrame([sample(shipment_id="CONFLICT", planned_delivery="2026-10-01", actual_delivery="2026-10-01T15:00:00Z"),
                                                 sample(shipment_id="CONFLICT", status="In Transit", actual_delivery="")]))
            assert preview["kpis"]["average_delay_hours"] == 15 and preview["duplicate_rows"] == 2
            observations["PR-05"] = {"date_only_is_midnight_delay_hours": 15, "duplicate_source_rows": 2,
                                     "excluded_rows": preview["kpis"]["excluded_rows"], "rules": preview["rules"]}

            tables = template_tables(2)
            item = request("POST", "/api/planning/imports/preview", files={"workbook": ("synthetic-planning.xlsx", workbook_bytes(tables))})
            assert item.status_code == 201 and item.json()["status"] == "previewed"
            item = item.json(); import_id = item["import_id"]
            assert request("POST", "/api/planning/runs", json={"import_id": import_id}).status_code == 409
            assert request("POST", f"/api/planning/imports/{import_id}/confirm", json={"confirmation": item["confirmation"], "acknowledged": True}).status_code == 200
            started = time.perf_counter()
            solved = request("POST", "/api/planning/runs", json={"import_id": import_id})
            assert solved.status_code == 201, solved.text
            run = solved.json()
            costs = [row["total_shipping_cost_usd"] for row in run["summary"]]
            assert costs == [120, 180, 120] and run["scenario_count"] == 0 and run["simulation_details"] == {}
            assert all(row["assumed_late_probability"] is None for row in run["results"]["Optimized Allocation"]["assignments"])
            observations["PR-06"] = {"independent_costs_usd": costs, "all_statuses": [row["status"] for row in run["summary"]],
                "scenario_count": 0, "fake_probabilities_absent": True, "source_declarations": run["source_info"], "request_seconds": time.perf_counter()-started}

            body = dict(dataset_id="demo", as_of="2026-10-01", shipment_id="SYN-0027", assumptions=[asdict(x) for x in default_assumptions()])
            compared = request("POST", "/api/decisions/compare", json=body).json()
            save = dict(**body, selected_action="Wait and monitor", exception_type="Overdue in transit", comparison_token=compared["comparison_token"])
            settings = request("GET", "/api/settings").json()["priority"]
            changed = deepcopy(settings); changed["weights"]["financial"] = 100
            assert request("PUT", "/api/settings/priority", json=changed).status_code == 200
            assert request("POST", "/api/cases", json=save).status_code == 409
            observations["PR-09_stale_comparison"] = {"status": 409, "no_case_saved": request("GET", "/api/cases").json() == []}

            # Observe a remaining concurrency gap rather than accepting it as correct.
            a, b = deepcopy(changed), deepcopy(changed)
            a["weights"]["urgency"] = 81
            b["weights"]["financial"] = 82
            first = request("PUT", "/api/settings/priority", json=a)
            second = request("PUT", "/api/settings/priority", role="second-admin", json=b)
            final = request("GET", "/api/settings").json()["priority"]
            observations["remaining_settings_lost_update"] = {"first_status": first.status_code, "stale_second_status": second.status_code,
                "distinct_administrators": ["admin", "second-admin"],
                "first_urgency": 81, "final_urgency": final["weights"]["urgency"], "original_urgency": changed["weights"]["urgency"],
                "lost_update_reproduced": final["weights"]["urgency"] != 81}
            assert first.status_code == second.status_code == 200 and final["weights"]["urgency"] != 81

            save["comparison_token"] = request("POST", "/api/decisions/compare", json=body).json()["comparison_token"]
            saved_case = request("POST", "/api/cases", json=save)
            assert saved_case.status_code == 201
            case_id = saved_case.json()["case_id"]

            with access.connect() as db:
                rows = [dict(row) for row in db.execute("SELECT actor,operation,target,status FROM access_events WHERE operation='PUT'")]
            observations["PR-10_metadata"] = {"request_id_header": bool(second.headers.get("x-request-id")),
                "events": rows, "old_new_config_in_event": False,
                "ready_status": request("GET", "/api/ready", role=None).status_code}

            # Cross-organization IDs and session tokens cannot transfer to another DB pair.
            with patch.dict(os.environ, {"LOGISTICS_WEB_DB_PATH": str(root / "b/workspace.sqlite3"), "LOGISTICS_DB_PATH": str(root / "b/history.sqlite3")}):
                other = AccessStore(); other.provision("Synthetic audit B"); other.set_user("admin", password, "admin")
                assert request("GET", "/api/datasets").status_code == 401
                old_token = tokens["admin"]; tokens["admin"] = other.login("admin", password)
                cross = {"dataset": request("GET", "/api/workspace", params={"dataset_id": dataset}).status_code,
                         "import": request("GET", f"/api/planning/imports/{import_id}").status_code,
                         "run": request("GET", f'/api/optimization/runs/{run["run_id"]}').status_code}
                assert set(cross.values()) == {404}
                with patch.dict(os.environ, {"LOGISTICS_DB_PATH": environment["LOGISTICS_DB_PATH"]}):
                    mismatch = request("GET", "/api/ready", role=None).status_code
                    assert mismatch == 503
                tokens["admin"] = old_token
                observations["PR-02"] = {"foreign_cookie_status": 401, "foreign_ids": cross, "mixed_db_pair_status": mismatch}

            # Same instance includes the confirmed import and linked allocation in native snapshots.
            cli_commands = []
            if offline_cli:
                for operation, paths in (("backup", [str(root / "backup")]), ("restore", [str(root / "backup"), str(root / "restored")])):
                    result = subprocess.run([sys.executable, "-m", "scripts.maintain_data", "--offline-confirmed", operation, *paths],
                        cwd=ROOT, capture_output=True, text=True, timeout=30)
                    assert result.returncode == 0, result.stderr
                    cli_commands.append({"operation": operation, "exit_code": result.returncode})
                    if operation == "backup": manifest = json.loads(result.stdout)
                    else: restored = json.loads(result.stdout)
            else:
                manifest = backup(root / "backup")
                restored = restore(root / "backup", root / "restored")
            assert restored["sessions_revoked"]
            with patch.dict(os.environ, {"LOGISTICS_WEB_DB_PATH": str(root / "restored/workspace.sqlite3"), "LOGISTICS_DB_PATH": str(root / "restored/history.sqlite3")}):
                assert request("GET", "/api/planning/imports").status_code == 401
                tokens["admin"] = AccessStore().login("admin", password)
                assert request("GET", f"/api/planning/imports/{import_id}").json()["status"] == "confirmed"
                rerun = request("GET", f'/api/optimization/runs/{run["run_id"]}').json()
                assert [row["total_shipping_cost_usd"] for row in rerun["summary"]] == costs
                assert request("GET", "/api/cases").json()[0]["case_id"] == case_id
                observations["PR-07"] = {"native_backup_table_counts": {name: value["counts"] for name,value in manifest["files"].items()},
                    "integrity_checked": True, "sessions_revoked": True, "confirmed_import_and_run_restored": True,
                    "case_preserved": True, "cli_commands": cli_commands,
                    "scope": "Stopped synthetic DB pair; not live multi-writer backup, scheduler or production RPO/RTO"}

            with patch.dict(os.environ, {"LOGISTICS_WEB_DB_PATH": str(root)}):
                observations["PR-10_invalid_database"] = {"health": request("GET", "/api/health", role=None).status_code,
                    "ready": request("GET", "/api/ready", role=None).status_code}
                assert observations["PR-10_invalid_database"] == {"health": 200, "ready": 503}
        evidence["completed"] = True
    (DOCS / ("offline_cli_probes.json" if offline_cli else "api_probes.json")).write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print("PASS: isolated API probes, including documented residual settings lost update", flush=True)


def browsers(flow=None):
    for label, script in (("premium", "browser_premium.py"), ("hardening", "browser_hardening.py"), ("uploaded", "browser_sprint2.py")):
        if flow and label != flow:
            continue
        with tempfile.TemporaryDirectory(prefix="logistics-remaining-browser-") as folder:
            password = secrets.token_urlsafe(24)
            output = ARTIFACTS / label; output.mkdir(parents=True, exist_ok=True)
            environment = dict(LOGISTICS_WEB_DB_PATH=str(Path(folder) / "workspace.sqlite3"), LOGISTICS_DB_PATH=str(Path(folder) / "history.sqlite3"),
                LOGISTICS_ALLOWED_ORIGINS="http://127.0.0.1:3100", LOGISTICS_COOKIE_SECURE="0", LOGISTICS_PILOT_MODE="0",
                APP_BASE_URL="http://127.0.0.1:3100", PYTHONPATH=str(ROOT), BROWSER_TEST_USERNAME="sprint2-admin", BROWSER_TEST_PASSWORD=password,
                BROWSER_OUTPUT_DIR=str(output), BROWSER_SCREENSHOT_DIR=str(output), BROWSER_EVIDENCE_PATH=str(DOCS / f"{label}_browser.json"))
            with patch.dict(os.environ, environment):
                access = AccessStore(); access.provision("Synthetic remaining-issues browser audit")
                for name, role in (("sprint2-admin", "admin"), ("sprint2-operator", "operator"), ("sprint2-viewer", "viewer"), ("browser-viewer", "viewer")):
                    access.set_user(name, password, role)
            with (output / "servers.log").open("w") as log, WebServers(port=3100, environment=environment, log=log) as servers:
                # The historical hardening script has a fixed DOCS path. Override
                # that module constant only, preserving every browser assertion.
                if label in {"hardening", "uploaded"}:
                    code = ("import importlib.util; from pathlib import Path; "
                            f"spec=importlib.util.spec_from_file_location('audit_browser', 'tests/{script}'); "
                            "m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); ")
                    code += ("m.DOCS=Path('artifacts/remaining-issues/hardening'); " if label == "hardening" else
                             "m.OUTPUT=Path('artifacts/remaining-issues/uploaded'); m.EVIDENCE=Path('docs/remaining-issues/uploaded_browser.json'); ")
                    code += "m.main()"
                    command = [sys.executable, "-c", code]
                else:
                    command = [sys.executable, str(ROOT / "tests" / script)]
                result = subprocess.run(command, cwd=ROOT, env=dict(os.environ, **environment), capture_output=True, text=True, timeout=600)
                (output / "browser.log").write_text(result.stdout + result.stderr)
                if label == "hardening" and (output / "browser.json").exists():
                    (DOCS / "hardening_browser.json").write_bytes((output / "browser.json").read_bytes())
                if result.returncode:
                    raise RuntimeError(f"{script} failed: inspect {output}/browser.log")
                if label == "uploaded":
                    pid = servers.api.pid; servers.restart_api(); assert servers.api.pid != pid
                    result = subprocess.run([*command, "--restart-check"], cwd=ROOT,
                        env=dict(os.environ, **environment), capture_output=True, text=True, timeout=120)
                    (output / "restart.log").write_text(result.stdout+result.stderr)
                    assert result.returncode == 0
                    file = DOCS / "uploaded_browser.json"; value = json.loads(file.read_text()); value["actual_api_process_restart"] = True
                    file.write_text(json.dumps(value, indent=2))
                print(f"PASS: {script}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", action="store_true", help="Run three existing flows against a previously built production frontend")
    parser.add_argument("--browser-flow", choices=("premium", "hardening", "uploaded"), help="Repeat a single unchanged browser flow")
    parser.add_argument("--offline-cli", action="store_true", help="After stopping audit browser servers, repeat probes using actual backup/restore CLI")
    args = parser.parse_args()
    DOCS.mkdir(parents=True, exist_ok=True); ARTIFACTS.mkdir(parents=True, exist_ok=True)
    browsers(args.browser_flow) if args.browser or args.browser_flow else probes(args.offline_cli)


if __name__ == "__main__":
    main()
