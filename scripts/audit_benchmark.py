"""Reproducible audit workload timings, not a commercial capacity benchmark.

Run from the project root: python -m scripts.audit_benchmark --ui
AppTest injects each workload into the demo source; actual upload is tested separately.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import statistics
import tempfile
import time
from unittest.mock import patch

import pandas as pd

from src.analysis import analyze_shipments, calculate_kpis
from src.decisions import compare_actions, default_assumptions
from src.demo import DEMO_AS_OF
from src.exports import csv_bytes
from src.ingestion import load_shipments
from src.priority import delivery_deadline, prioritize_shipments
from src.reporting import RuleBasedReportGenerator


def make_workload(size: int) -> pd.DataFrame:
    records = []
    for index in range(size):
        kind = index % 4
        records.append({
            "shipment_id": f"AUDIT-{index:06d}", "origin": "Shanghai, China", "destination": "Rotterdam, Netherlands",
            "transport_mode": "Sea", "carrier": "Synthetic Audit Carrier", "shipped_at": "2026-09-01T00:00:00Z",
            "planned_delivery": "2026-10-05T12:00:00Z" if kind == 3 else "2026-09-30T12:00:00Z",
            "actual_delivery": ("2026-09-30T12:00:00Z" if kind == 0 else "2026-10-01T12:00:00Z") if kind < 2 else "",
            "shipping_cost": 100, "status": "Delivered" if kind < 2 else "In Transit",
            "delivery_deadline": "2026-10-02T12:00:00Z", "estimated_delay_hours": 48,
            "estimated_financial_impact": 1000, "financial_impact_basis": "Synthetic audit contract input",
            "shipment_value": 50000, "downstream_dependency_count": 2,
            "downstream_risk_basis": "Two synthetic dependent activities", "decision_context_source": "Synthetic audit only",
        })
    return pd.DataFrame(records)


def check_kpis(kpis, size):
    assert kpis["total_shipments"] == size
    assert kpis["delivered_shipments"] == size // 2
    assert kpis["on_time_delivery_rate"] == 0.5
    assert kpis["delayed_shipments"] == size // 4
    assert kpis["overdue_shipments"] == size // 4
    assert kpis["average_delay_hours"] == 24
    assert kpis["total_shipping_cost"] == size * 100
    assert kpis["cost_anomalies"] == 0


def injected_app():
    import app
    app.main()


def measure(size, repeats=3, include_ui=False):
    raw = make_workload(size)
    data = raw.to_csv(index=False).encode()
    timings = []
    for _ in range(repeats):
        started = time.perf_counter()
        loaded = load_shipments(data, "synthetic_audit.csv")
        read = time.perf_counter()
        result = analyze_shipments(loaded, DEMO_AS_OF)
        analyzed = time.perf_counter()
        priorities = prioritize_shipments(result.shipments, result.cutoff)
        scored = time.perf_counter()
        kpis = calculate_kpis(result.shipments)
        check_kpis(kpis, size)
        assert result.issues.empty
        report = RuleBasedReportGenerator().generate(result.shipments, result.issues, result.as_of, "Synthetic audit workload")
        assert f"| Total Shipments | {size} |" in report
        csv_bytes(priorities)
        csv_bytes(result.shipments)
        row = result.shipments.iloc[2]
        compare_actions(result.cutoff, delivery_deadline(row)[0], default_assumptions())
        finished = time.perf_counter()
        timings.append({"csv_read_s": read-started, "analysis_s": analyzed-read, "priority_s": scored-analyzed,
                        "report_exports_s": finished-scored, "pipeline_s": finished-started})
    output = {"rows": size, "repeats": repeats, "median_seconds": {key: round(statistics.median(row[key] for row in timings), 6) for key in timings[0]},
              "runs": timings, "kpis_verified": True, "errors": [], "csv_bytes": len(data)}
    if include_ui:
        from streamlit.testing.v1 import AppTest
        import app
        with tempfile.TemporaryDirectory(prefix="logistics-audit-ui-") as directory:
            with patch.dict(os.environ, {"LOGISTICS_DB_PATH": str(Path(directory) / "test.sqlite3")}), patch.object(app, "generate_demo_data", lambda: raw.copy()):
                started = time.perf_counter()
                ui = AppTest.from_function(injected_app).run(timeout=120)
                output["apptest_seconds"] = round(time.perf_counter() - started, 6)
                assert not ui.exception, [item.message for item in ui.exception]
                assert ui.metric[0].value == f"{size:,}"
                output["apptest_verified"] = True
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", nargs="+", type=int, default=[100, 500, 5000])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--ui", action="store_true")
    parser.add_argument("--output", default="artifacts/audit/benchmark.json")
    args = parser.parse_args()
    if args.repeats < 1 or any(size < 4 or size % 4 for size in args.sizes):
        parser.error("Use positive repeat counts and sizes divisible by 4.")
    output = {"environment": {"python": platform.python_version(), "platform": platform.platform(),
                               "pandas": pd.__version__, "timestamp_utc": datetime.now(timezone.utc).isoformat()},
              "method": "Clean synthetic four-case pattern, hand-calculated KPIs; 3 pipeline repeats by default. UI timing is one server-side AppTest run per size, not browser latency.",
              "results": [measure(size, args.repeats, args.ui) for size in args.sizes]}
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, indent=2, allow_nan=False))
    print(json.dumps(output, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
