"""Bounded production-readiness probes. Never opens the user's databases.

These characterize current behavior, including defects; a completed probe is not
a passed production gate. Run: python -m scripts.audit_readiness
"""

import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import platform
import re
import sqlite3
import subprocess
import tempfile
import time
from unittest.mock import patch

import httpx
import pandas as pd

from backend.main import app
from src.analysis import analyze_shipments, calculate_kpis
from src.decisions import default_assumptions
from src.history import CaseInput, HistoryStore
from src.priority import PriorityConfig, prioritize_shipments
from src.transport.engine import candidate_table, late_probability
from src.transport.models import Candidate, Constraints, Order, PlanningData, Service

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/audit/readiness_probes.json"


def sample(**changes):
    """Hand-authored synthetic contract probe, not a deidentified customer record."""
    return {**dict(shipment_id="AUDIT-1", origin="Shanghai, China", destination="Rotterdam, Netherlands",
                   carrier="Fictional audit carrier", transport_mode="Sea", status="Delivered",
                   planned_delivery="2026-10-01T08:00:00Z", actual_delivery="2026-10-01T08:00:00Z",
                   shipping_cost=100), **changes}


async def exercise(folder):
    evidence = {"audit_of_commit": "69ca7e0", "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "python": platform.python_version(), "platform": platform.platform(),
                "data_warning": "All authored contract probes are synthetic. The separately attributed public airport sample is not freight SLA validation.",
                "observations": {}, "completed": False}
    seen = evidence["observations"]
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://audit", cookies={"audit_session": "A"}) as a, \
               httpx.AsyncClient(transport=transport, base_url="http://audit", cookies={"audit_session": "B"}) as b:
        # These cookies distinguish browser sessions only; neither client is authenticated.
        async def upload(frame, name="probe.csv", client=a):
            payload = frame.to_csv(index=False).encode()
            response = await client.post("/api/datasets", files={"file": (name, payload)}, data={"as_of": "2026-10-02"})
            assert response.status_code == 201, response.text
            return response.json(), len(payload)

        async def read(dataset, client=a, **params):
            response = await client.get("/api/workspace", params={"dataset_id": dataset["dataset_id"], **params})
            assert response.status_code == 200, response.text
            return response.json()

        private, _ = await upload(pd.DataFrame([sample(customer_email="ops@example.invalid")]), "organization-A.csv")
        listed = await b.get("/api/datasets")
        exposed = await read(private, b)
        exported = await b.get("/api/exports/shipments", params={"dataset_id": private["dataset_id"]})
        seen["anonymous_cross_session_read"] = {"list_status": listed.status_code,
            "other_session_sees_dataset": any(row["dataset_id"] == private["dataset_id"] for row in listed.json()),
            "workspace_status": 200, "extra_column_in_response": "customer_email" in exposed["shipments"][0],
            "extra_column_in_export": "ops@example.invalid" in exported.text,
            "note": "Two independent unauthenticated cookie sessions, not two authenticated tenant accounts."}

        config = PriorityConfig.load().to_dict()
        config["weights"]["financial"] = 100
        changed = await b.put("/api/settings/priority", json=config)
        observed = (await a.get("/api/settings")).json()
        seen["anonymous_global_settings_write"] = {"write_status": changed.status_code,
                                                   "other_session_financial_weight": observed["priority"]["weights"]["financial"]}
        await a.put("/api/settings/priority", json=PriorityConfig.load().to_dict())

        case_body = {"dataset_id": "demo", "as_of": "2026-10-01", "shipment_id": "SYN-0027",
                     "assumptions": [asdict(value) for value in default_assumptions()],
                     "selected_action": "Wait and monitor", "exception_type": "Overdue in transit", "resolution_notes": "Synthetic readiness probe"}
        saved = (await a.post("/api/cases", json=case_body)).json()
        patched = await b.patch("/api/cases/" + saved["case_id"], json={"resolution_status": "Resolved", "actual_cost": 123,
                               "actual_delay": 12, "resolution_notes": "Other anonymous session", "expected_version": saved["version"]})
        seen["anonymous_case_update"] = {"status": patched.status_code, "status_after": patched.json().get("resolution_status")}

        comparison_body = {key: value for key, value in case_body.items() if key not in {"selected_action", "exception_type", "resolution_notes"}}
        comparison_before = await a.post("/api/decisions/compare", json=comparison_body)
        before_priority = next(row["priority_score"] for row in (await a.get("/api/workspace")).json()["exceptions"] if row["shipment_id"] == "SYN-0027")
        revised = PriorityConfig.load().to_dict()
        revised["weights"]["financial"] = 100
        await b.put("/api/settings/priority", json=revised)
        saved_after_rule_change = (await a.post("/api/cases", json={**case_body, "resolution_notes": "Saved after another session changed rules"})).json()
        after_priority = json.loads(saved_after_rule_change["priority_snapshot_json"])["priority_score"]
        seen["comparison_configuration_revision"] = {"compare_status": comparison_before.status_code,
            "score_when_compared": before_priority, "saved_snapshot_score": after_priority,
            "snapshot_config_version_in_compare_response": "config_version" in comparison_before.json(),
            "meaning": "Saving recomputes priority with current global settings, not a version pinned by the displayed comparison."}
        await a.put("/api/settings/priority", json=PriorityConfig.load().to_dict())

        variants = {}
        for name, frame in {
            "reordered_trimmed_uppercase": pd.DataFrame([sample()]).iloc[:, ::-1].rename(columns=lambda key: " " + key.upper() + " "),
            "alternative_column_names": pd.DataFrame([sample()]).rename(columns={"shipment_id": "Order ID", "planned_delivery": "ETA"}),
            "missing_actual_column": pd.DataFrame([sample()]).drop(columns="actual_delivery"),
        }.items():
            response = await a.post("/api/datasets", files={"file": (name + ".csv", frame.to_csv(index=False).encode())})
            variants[name] = {"status": response.status_code, "detail": response.json().get("detail")}
        for name, payload in {"semicolon_csv": pd.DataFrame([sample()]).to_csv(index=False, sep=";").encode(),
                              "gbk_csv": pd.DataFrame([sample(origin="上海")]).to_csv(index=False).encode("gbk"),
                              "malformed_csv": b'shipment_id,origin\n"unterminated,cell',
                              "not_excel": b"not an xlsx archive"}.items():
            response = await a.post("/api/datasets", files={"file": (name + (".xlsx" if name == "not_excel" else ".csv"), payload)})
            variants[name] = {"status": response.status_code, "detail": response.json().get("detail")}
        public = ROOT / "tests/fixtures/public_transport/airport_traffic.csv"
        response = await a.post("/api/datasets", files={"file": ("public-airport-traffic.csv", public.read_bytes())})
        seen["public_transport_input"] = {"status": response.status_code, "detail": response.json().get("detail"),
            "provenance": json.loads(public.with_name("provenance.json").read_text()),
            "not_verified": "Upstream identifies original source as Unknown; airport aggregate records do not contain shipment delivery/SLA fields."}
        seen["template_compatibility"] = variants

        dates = {}
        for name, planned, actual in [
            ("offset_equivalent", "2026-10-01T10:00:00+02:00", "2026-10-01T08:00:00Z"),
            ("ambiguous_day_month", "01/10/2026", "2026-10-01T08:00:00Z"),
            ("date_only_deadline", "2026-10-01", "2026-10-01T15:00:00Z"),
            ("invalid_actual", "2026-10-01", "not-a-date"),
        ]:
            dataset, _ = await upload(pd.DataFrame([sample(planned_delivery=planned, actual_delivery=actual)]))
            result = await read(dataset)
            dates[name] = {"kpis": result["kpis"], "issues": [row["code"] for row in result["issues"]]}
        seen["date_and_timezone"] = dates

        mixed, _ = await upload(pd.DataFrame([sample(shipment_id="USD", currency="USD", weight_unit="kg"),
                                              sample(shipment_id="EUR", currency="EUR", weight_unit="lb")]))
        result = await read(mixed)
        seen["mixed_currency_and_units"] = {"total_reported_as_usd": result["kpis"]["total_shipping_cost"],
            "issue_count": result["issue_count"], "currencies_retained": [row["currency"] for row in result["shipments"]],
            "units_retained": [row["weight_unit"] for row in result["shipments"]],
            "meaning": "Explicit EUR/lb metadata does not prevent summing the nominal costs as USD; no FX/unit conversion was performed."}

        bad_costs, _ = await upload(pd.DataFrame([sample(shipment_id=f"COST-{i}", shipping_cost=value)
                                                 for i, value in enumerate([-1, "USD 10", "inf", "1.234,56", "1,234"])]))
        result = await read(bad_costs)
        seen["invalid_and_locale_prices"] = {"valid_costs": result["kpis"]["cost_eligible_shipments"],
            "total": result["kpis"]["total_shipping_cost"], "issues": result["issue_count"],
            "interpretation": "1,234 is interpreted as 1234, not locale decimal 1.234; other invalid price strings excluded."}

        first = sample(shipment_id="SAME", status="In Transit", actual_delivery="")
        later = sample(shipment_id="SAME")
        seen["conflicting_duplicate_order"] = {}
        for name, rows in [("transit_first", [first, later]), ("delivered_first", [later, first])]:
            dataset, _ = await upload(pd.DataFrame(rows))
            result = await read(dataset)
            seen["conflicting_duplicate_order"][name] = {key: result["kpis"][key] for key in
                                                        ("total_shipments", "delivered_shipments", "overdue_shipments")}

        all_active = [sample(shipment_id=f"ACTIVE-{i:04d}", status="In Transit", actual_delivery="",
                             delivery_deadline="2026-10-03T00:00:00Z", estimated_delay_hours=72,
                             estimated_financial_impact=10000, financial_impact_basis="Synthetic assumption",
                             shipment_value=100000, downstream_dependency_count=5,
                             downstream_risk_basis="Synthetic dependency") for i in range(501)]
        all_active[-1].update(estimated_delay_hours=0, estimated_financial_impact=0, shipment_value=0, downstream_dependency_count=0)
        dataset, _ = await upload(pd.DataFrame(all_active))
        result = await read(dataset)
        target = all_active[-1]["shipment_id"]
        direct = await a.post("/api/decisions/compare", json={"dataset_id": dataset["dataset_id"], "as_of": "2026-10-02",
                              "shipment_id": target, "assumptions": [asdict(value) for value in default_assumptions()]})
        seen["queue_cap_actionability"] = {"exception_count": result["exception_count"], "returned": len(result["exceptions"]),
            "target": target, "target_available_to_ui": any(row["shipment_id"] == target for row in result["exceptions"]),
            "direct_compare_status": direct.status_code}

        body_oversize = b"x" * (20 * 1024 * 1024 + 1)
        response = await a.post("/api/datasets", files={"file": ("oversize.csv", body_oversize)})
        seen["oversized_selected_file"] = {"bytes": len(body_oversize), "status": response.status_code, "detail": response.json().get("detail")}
        response = await a.post("/api/datasets", files=[("file", ("small.csv", pd.DataFrame([sample()]).to_csv(index=False).encode())),
                                ("ignored", ("unused.bin", body_oversize))])
        seen["oversized_ignored_multipart_part"] = {"unused_bytes": len(body_oversize), "status": response.status_code,
            "meaning": "The selected file limit is not a total HTTP-body or multipart spool limit."}
        del body_oversize

        line = pd.DataFrame([sample()]).to_csv(index=False).splitlines()
        over_rows = (line[0] + "\n" + (line[1] + "\n") * 100001).encode()
        response = await a.post("/api/datasets", files={"file": ("too-many-rows.csv", over_rows)})
        seen["row_limit"] = {"rows": 100001, "bytes": len(over_rows), "status": response.status_code, "detail": response.json().get("detail")}

        workloads = []
        for size in (100, 5000):
            started = time.perf_counter()
            dataset, payload_size = await upload(pd.DataFrame([sample(shipment_id=f"LOAD-{i}") for i in range(size)]))
            uploaded_at = time.perf_counter()
            result = await read(dataset)
            assert result["kpis"]["total_shipments"] == size
            assert result["kpis"]["on_time_delivery_rate"] == 1
            workloads.append({"rows": size, "csv_bytes": payload_size, "upload_seconds": uploaded_at - started,
                              "workspace_seconds": time.perf_counter() - uploaded_at, "retained": result["kpis"]["total_shipments"]})
        seen["bounded_api_workloads"] = workloads

        nonfinite = {}
        for name, payload in {"NaN": '{"cost_weight":NaN}', "overflow_exponent": '{"cost_weight":1e309}',
                              "negative": '{"cost_weight":-1}', "boolean": '{"count":true}'}.items():
            response = await a.post("/api/optimization/runs", content=payload, headers={"Content-Type": "application/json"})
            nonfinite[name] = {"status": response.status_code, "body_excerpt": response.text[:180]}
        seen["numeric_api_errors"] = nonfinite

        options = await a.options("/api/settings/priority", headers={"Origin": "https://example.invalid",
                                   "Access-Control-Request-Method": "PUT", "Access-Control-Request-Headers": "content-type"})
        cross_origin = await a.post("/api/datasets", headers={"Origin": "https://example.invalid"},
                                    files={"file": ("origin-probe.csv", pd.DataFrame([sample()]).to_csv(index=False).encode())})
        seen["cors_and_origin"] = {"preflight_status": options.status_code,
            "allow_origin": options.headers.get("access-control-allow-origin"), "simple_upload_status": cross_origin.status_code,
            "note": "No permissive CORS middleware. CORS is not authentication; a simple upload can be received without a preflight."}

        injected = await a.get("/api/workspace", params={"dataset_id": "' OR 1=1 --"})
        cases = await a.get("/api/cases", params={"shipment_id": "' OR 1=1 --"})
        csv = await a.post("/api/datasets", files={"file": ("formulas.csv", pd.DataFrame([sample(origin="=1+1")]).to_csv(index=False).encode())})
        exported = await a.get("/api/exports/shipments", params={"dataset_id": csv.json()["dataset_id"]})
        seen["sql_and_csv_controls"] = {"injected_dataset_status": injected.status_code,
            "injected_case_query_results": len(cases.json()), "formula_escaped": "'=1+1" in exported.text}

        run = await a.post("/api/optimization/runs", json={"count": 12, "scenario_count": 100})
        run_body = run.json()
        peer_run = await b.get("/api/optimization/runs/latest")
        custom = await a.post("/api/optimization/runs", json={"orders": [], "services": []})
        seen["optimization_scope"] = {"status": run.status_code, "provenance": run_body["provenance"],
            "strategies": {row["strategy"]: row["status"] for row in run_body["summary"]},
            "other_session_latest_is_same": peer_run.json()["run_id"] == run_body["run_id"],
            "custom_order_service_payload_status": custom.status_code}

        deletion = await a.delete("/api/datasets/" + private["dataset_id"])
        seen["retention"] = {"delete_dataset_status": deletion.status_code, "stored_upload_rows": len((await a.get("/api/datasets")).json())}

        store = HistoryStore(folder / "history.sqlite3")
        for i in range(1001):
            store.create_case(CaseInput(f"HISTORY-{i}", "Synthetic audit exception", "Wait and monitor",
                                         resolution_notes="Synthetic pagination fixture"))
        history_export = await a.get("/api/cases/export")
        with sqlite3.connect(folder / "history.sqlite3") as connection:
            stored_count = connection.execute("SELECT count(*) FROM cases").fetchone()[0]
        seen["history_export_cap"] = {"stored_cases": stored_count,
            "exported_cases": len(pd.read_csv(BytesIO(history_export.content))),
            "note": "The export endpoint limits to the newest 1000 and has no cursor or full-export option."}
        with patch.dict(os.environ, {"LOGISTICS_WEB_DB_PATH": str(folder)}):
            healthy = await a.get("/api/health")
            unavailable = await a.get("/api/workspace")
            ready = await a.get("/api/ready")
        seen["health_not_database_readiness"] = {"health_status": healthy.status_code, "workspace_status": unavailable.status_code,
                                               "readiness_route_status": ready.status_code,
                                               "meaning": "Process liveness works but there is no separate database-aware readiness endpoint."}

    schemas = {}
    backups = {}
    for name in ("workspace", "history"):
        path = folder / (name + ".sqlite3")
        with sqlite3.connect(path) as original:
            schemas[name] = {table: [row[1] for row in original.execute(f'PRAGMA table_info("{table}")')]
                             for (table,) in original.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            restored_path = folder / (name + "-restored.sqlite3")
            with sqlite3.connect(restored_path) as restored:
                original.backup(restored)
                assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                counts = {table: original.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0] for table in schemas[name]}
                assert counts == {table: restored.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0] for table in schemas[name]}
                backups[name] = {"integrity_check": "ok", "table_counts": counts}
    seen["database_schemas"] = schemas
    seen["manual_native_sqlite_backup_restore"] = {"result": backups,
        "scope": "Audit-only quiescent backup/restore using sqlite3.Connection.backup; no scheduled application backup or disaster recovery service implemented."}

    plan = PlanningData((Order("P", "CN", "EU", 1, 1, 48),),
                        (Service("S", "CN", "EU", "Air", 48, 12, 10, 10, 10),), (Candidate("P", "S", 100),))
    eligibility = candidate_table(plan, Constraints(1000)).iloc[0]
    seen["deadline_business_semantics"] = {"hard_eligible": bool(eligibility.eligible),
        "assumed_late_probability": late_probability(48, 12, 48),
        "meaning": "Meeting an expected-time hard deadline is not a 95% on-time guarantee."}
    prices = pd.DataFrame([sample(shipment_id=f"SMALL-{i}", shipping_cost=100, weight_kg=10) for i in range(8)]
                          + [sample(shipment_id="LARGE", shipping_cost=1000, weight_kg=100)])
    analyzed = analyze_shipments(prices, "2026-10-02")
    seen["cost_comparability"] = {"equal_cost_per_kg": True, "flagged_ids": analyzed.shipments.loc[analyzed.shipments.is_cost_anomaly, "shipment_id"].tolist(),
                                 "meaning": "Absolute cost screening does not normalize by shipment weight."}

    # Never print candidate secret values. Report only categories and locations.
    patterns = {"private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
                "aws_access_key": re.compile(r"AKIA[0-9A-Z]{16}"),
                "github_token": re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
                "openai_style_key": re.compile(r"sk-[A-Za-z0-9]{32,}")}
    findings = []
    files = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    for name in filter(None, files):
        path = ROOT / name
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError:
            continue
        for category, regex in patterns.items():
            for match in regex.finditer(text):
                findings.append({"file": name, "line": text.count("\n", 0, match.start()) + 1, "category": category})
    seen["tracked_secret_pattern_scan"] = {"findings": findings,
        "scope": "Current tracked text files up to 2 MB; no environment values or git-history contents dumped. Not a comprehensive secret audit."}
    evidence["completed"] = True
    return evidence


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="logistics-readiness-") as directory:
        folder = Path(directory)
        with patch.dict(os.environ, {"LOGISTICS_WEB_DB_PATH": str(folder / "workspace.sqlite3"),
                                     "LOGISTICS_DB_PATH": str(folder / "history.sqlite3")}):
            evidence = asyncio.run(exercise(folder))
    OUTPUT.write_text(json.dumps(evidence, indent=2, allow_nan=False), encoding="utf-8")
    print("Recorded", len(evidence["observations"]), "observations:", OUTPUT, flush=True)
    print("Completed probes demonstrate current behavior; they do not mark identified production gates as passed.")


if __name__ == "__main__":
    main()
