"""HTTP round trips assert business numbers, persistence and rejected input.

Optional web dependencies are isolated from the original Streamlit installation.
Full web validation/CI installs requirements-web.txt, so this module is not skipped.
"""

import asyncio
from dataclasses import asdict
from io import BytesIO
import json

import pandas as pd
import pytest

httpx = pytest.importorskip("httpx")
pytest.importorskip("fastapi")

from backend.main import app
from backend.store import WorkspaceStore
from src.decisions import default_assumptions
from src.demo import generate_demo_data, demo_xlsx_bytes
from src.priority import PriorityConfig


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGISTICS_WEB_DB_PATH", str(tmp_path / "web.sqlite3"))
    monkeypatch.setenv("LOGISTICS_DB_PATH", str(tmp_path / "cases.sqlite3"))

    class Client:
        def request(self, method, url, **kwargs):
            async def send():
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as session:
                    return await session.request(method, url, **kwargs)
            return asyncio.run(send())

        def get(self, url, **kwargs): return self.request("GET", url, **kwargs)
        def post(self, url, **kwargs): return self.request("POST", url, **kwargs)
        def put(self, url, **kwargs): return self.request("PUT", url, **kwargs)
        def patch(self, url, **kwargs): return self.request("PATCH", url, **kwargs)
    return Client()


def decision_body(**changes):
    return {"dataset_id": "demo", "as_of": "2026-10-01", "shipment_id": "SYN-0027",
            "assumptions": [asdict(value) for value in default_assumptions()], **changes}


def test_api_default_kpis_are_existing_python_calculations(client):
    assert client.get("/api/health").json()["status"] == "ok"
    response = client.get("/api/workspace")
    assert response.status_code == 200
    body = response.json()
    assert body["dataset"]["synthetic"] is True
    k = body["kpis"]
    assert k["total_shipments"] == 158
    assert k["delivered_shipments"] == 91
    assert k["eligible_deliveries"] == 90
    assert k["on_time_delivery_rate"] == 43 / 90
    assert k["overdue_shipments"] == 30
    assert k["total_shipping_cost"] == 539830.75
    assert k["cost_anomalies"] == 4
    assert len(body["shipments"]) == 50
    assert any(row["actionable"] and row["shipment_id"] == "SYN-0027" for row in body["exceptions"])


def test_filter_pagination_exports_share_same_scope(client):
    body = client.get("/api/workspace?status=In%20Transit&limit=10&offset=10").json()
    assert body["kpis"]["delivered_shipments"] == 0
    assert body["kpis"]["on_time_delivery_rate"] is None
    assert len(body["shipments"]) == 10 and body["offset"] == 10
    exported = pd.read_csv(BytesIO(client.get("/api/exports/shipments?status=In%20Transit").content))
    assert exported.status.eq("In Transit").all()
    assert len(exported) == body["total_rows"]
    report = client.get("/api/exports/report?status=In%20Transit")
    assert "Executive Summary" in report.text and "Synthetic Demo Data" in report.text
    assert "attachment" in report.headers["content-disposition"]
    assert client.get("/api/workspace?q=NO-SUCH-SHIPMENT").json()["kpis"]["total_shipments"] == 0


@pytest.mark.parametrize("kind", ["csv", "xlsx"])
def test_upload_and_new_store_instance_persistence(client, tmp_path, kind):
    frame = generate_demo_data().head(10)
    content = frame.to_csv(index=False).encode() if kind == "csv" else demo_xlsx_bytes(frame)
    response = client.post("/api/datasets", files={"file": (f"orders.{kind}", content)}, data={"as_of": "2026-10-01"})
    assert response.status_code == 201, response.text
    dataset = response.json()
    assert dataset["synthetic"] is False  # uploads are never automatically branded synthetic
    body = client.get("/api/workspace", params={"dataset_id": dataset["dataset_id"]}).json()
    assert body["total_rows"] == 10
    new_store = WorkspaceStore(tmp_path / "web.sqlite3")
    metadata, stored = new_store.dataset(dataset["dataset_id"])
    assert metadata["name"] == f"orders.{kind}" and len(stored) == 10
    assert any(item["dataset_id"] == dataset["dataset_id"] for item in client.get("/api/datasets").json())


@pytest.mark.parametrize("content,filename", [(b"", "empty.csv"), (b"foo,bar\n1,2", "missing.csv"),
                                             (b"bad", "bad.xlsx"), (b"bad", "wrong.txt")])
def test_invalid_uploads_are_actionable_and_do_not_replace_demo(client, content, filename):
    response = client.post("/api/datasets", files={"file": (filename, content)})
    assert response.status_code == 400
    assert isinstance(response.json()["detail"], str)
    assert client.get("/api/workspace").json()["kpis"]["total_shipments"] == 158


def test_header_only_and_field_errors_do_not_crash(client):
    frame = generate_demo_data().head(4).copy()
    for frame_to_upload, expected_rows in [(frame.iloc[:0], 0), (frame, 4)]:
        if expected_rows:
            frame_to_upload.loc[0, "planned_delivery"] = "bad-date"
            frame_to_upload.loc[1, "shipping_cost"] = -1
            frame_to_upload.loc[2, "shipment_id"] = frame_to_upload.loc[1, "shipment_id"]
        dataset = client.post("/api/datasets", files={"file": ("edge.csv", frame_to_upload.to_csv(index=False).encode())}).json()
        response = client.get("/api/workspace", params={"dataset_id": dataset["dataset_id"], "as_of": "2026-10-01"})
        assert response.status_code == 200
        body = response.json()
        assert body["total_rows"] == expected_rows
        if expected_rows:
            assert body["kpis"]["total_shipments"] == 3
            assert body["issue_count"] >= 3
        else:
            assert body["kpis"]["on_time_delivery_rate"] is None


def test_settings_change_score_not_v1_kpis_and_persist(client, tmp_path):
    before = client.get("/api/workspace").json()
    score = lambda body: next(row["priority_score"] for row in body["exceptions"] if row["shipment_id"] == "SYN-0027")
    assert score(before) == 78.6667
    config = PriorityConfig.load().to_dict()
    config["weights"]["financial"] = 100
    assert client.put("/api/settings/priority", json=config).status_code == 200
    after = client.get("/api/workspace").json()
    assert score(after) == 88.1481
    assert before["kpis"] == after["kpis"]
    assert WorkspaceStore(tmp_path / "web.sqlite3").setting("priority", {})["weights"]["financial"] == 100
    assert client.get("/api/evaluation").status_code == 200


def test_decision_time_and_cost_are_independent(client):
    body = decision_body()
    baseline = client.post("/api/decisions/compare", json=body)
    assert baseline.status_code == 200
    assert baseline.json()["comparison"][0]["estimated_delay_hours"] == pytest.approx(72)
    body["assumptions"][0].update(additional_cost=450, remaining_hours=48)
    changed = client.post("/api/decisions/compare", json=body).json()
    assert changed["comparison"][0]["estimated_additional_cost_usd"] == 450
    assert changed["comparison"][0]["estimated_delay_hours"] == pytest.approx(24)
    body["assumptions"][0]["additional_cost"] = 900
    price_only = client.post("/api/decisions/compare", json=body).json()
    assert price_only["comparison"][0]["estimated_delay_hours"] == pytest.approx(24)


def test_case_save_retry_update_stale_version_and_similarity(client):
    payload = decision_body(selected_action="Wait and monitor", exception_type="Overdue in transit", resolution_notes="API acceptance")
    response = client.post("/api/cases", json=payload)
    assert response.status_code == 201, response.text
    saved = response.json()
    assert saved["estimated_cost"] == 0 and saved["actual_cost"] is None
    assert client.post("/api/cases", json=payload).json()["case_id"] == saved["case_id"]
    assert len(client.get("/api/cases").json()) == 1
    update = dict(resolution_status="Resolved", actual_cost=150, actual_delay=12,
                  resolution_notes="Outcome recorded", expected_version=1)
    assert client.patch(f'/api/cases/{saved["case_id"]}', json=update).status_code == 200
    assert client.patch(f'/api/cases/{saved["case_id"]}', json=update).status_code == 409
    assert client.get("/api/cases?resolution_status=Resolved").json()[0]["actual_cost"] == 150
    assert client.post("/api/cases", json=payload).json()["resolution_status"] == "Resolved"
    assert len(client.get("/api/cases/export").content) > 0
    # A second order on the same lane/mode/type should find the saved case.
    workspace = client.get("/api/workspace").json()
    source = next(row for row in workspace["exceptions"] if row["shipment_id"] == "SYN-0027")
    similar = next(row for row in workspace["exceptions"] if row["actionable"] and row["shipment_id"] != source["shipment_id"]
                   and (row["origin"], row["destination"], row["transport_mode"], row["exception_types"].split("; ")[0])
                   == (source["origin"], source["destination"], source["transport_mode"], "Overdue in transit"))
    comparison = client.post("/api/decisions/compare", json=decision_body(shipment_id=similar["shipment_id"])).json()
    assert any(row["case_id"] == saved["case_id"] for row in comparison["similar_cases"])


@pytest.mark.parametrize("change", [{"shipment_id": "MISSING"}, {"shipment_id": "SYN-0001"},
                                     {"assumptions": []}])
def test_invalid_decision_requests_are_not_successful(client, change):
    assert client.post("/api/decisions/compare", json=decision_body(**change)).status_code in (400, 404, 422)


@pytest.mark.parametrize("body", [{"budget_percent": -1}, {"cost_weight": 0, "time_weight": 0, "risk_weight": 0},
                                  {"count": True}, {"time_limit_seconds": 100}, {"unknown": 1}])
def test_invalid_optimizer_input_rejected(client, body):
    assert client.post("/api/optimization/runs", json=body).status_code in (400, 422)
    assert client.get("/api/optimization/runs/latest").status_code == 404


def test_optimizer_real_results_export_and_persistence(client, tmp_path):
    response = client.post("/api/optimization/runs", json={"scenario_count": 100})
    assert response.status_code == 201, response.text
    run = response.json()
    assert all(row["status"] == "OPTIMAL" for row in run["summary"])
    assert run["results"]["Optimized Allocation"]["assignments"]
    assert len(run["candidate_checks"]) == 36
    assert run["simulation_details"]["Optimized Allocation"][0]["expected_hours"] > 0
    assert len(WorkspaceStore(tmp_path / "web.sqlite3").run()["summary"]) == 3
    assert client.get("/api/optimization/runs/latest").json()["run_id"] == run["run_id"]
    payload = client.get(f'/api/optimization/runs/{run["run_id"]}/export/json').json()
    assert payload["scenario_fingerprint"] == run["scenario_fingerprint"]
    for kind in ("comparison", "allocation", "candidates"):
        assert client.get(f'/api/optimization/runs/{run["run_id"]}/export/{kind}').status_code == 200


def test_optimizer_shortage_and_empty_are_honest(client):
    strict = client.post("/api/optimization/runs", json={"budget_percent": 0, "scenario_count": 100}).json()
    assert all(row["status"] == "INFEASIBLE" and row["total_shipping_cost_usd"] is None for row in strict["summary"])
    soft = client.post("/api/optimization/runs", json={"budget_percent": 0, "allow_unassigned": True, "scenario_count": 100}).json()
    assert all(row["unassigned_orders"] == 12 and row["simulated_on_time_rate_all_orders"] == 0 for row in soft["summary"])
    empty = client.post("/api/optimization/runs", json={"count": 0, "scenario_count": 100}).json()
    assert all(row["status"] == "OPTIMAL" and row["simulated_on_time_rate_all_orders"] is None for row in empty["summary"])


@pytest.mark.parametrize("query", ["as_of=bad-date", "offset=-1", "limit=100000"])
def test_invalid_query_parameters(client, query):
    assert client.get("/api/workspace?" + query).status_code == 422
