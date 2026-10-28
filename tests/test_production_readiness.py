"""Audited behavior and explicit unmet production gates, not new business features.

Former strict XFAIL gates retain their original assertions and now must pass.
Fixtures authenticate only positive paths; anonymous and unrelated sessions remain unauthenticated.
"""

import asyncio
from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest

httpx = pytest.importorskip("httpx")
pytest.importorskip("fastapi")

from backend.main import app
from backend.access import AccessStore, COOKIE
from backend.import_contract import confirmation
import secrets
from scripts.audit_readiness import sample
from src.analysis import analyze_shipments, calculate_kpis
from src.ingestion import DataInputError, load_shipments
from src.priority import PriorityConfig
from src.transport.engine import candidate_table
from src.transport.models import Candidate, Constraints, Order, PlanningData, Service


@pytest.fixture
def clients(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGISTICS_WEB_DB_PATH", str(tmp_path / "workspace.sqlite3"))
    monkeypatch.setenv("LOGISTICS_DB_PATH", str(tmp_path / "history.sqlite3"))

    monkeypatch.setenv("LOGISTICS_ALLOWED_ORIGINS", "http://audit")
    access = AccessStore()
    access.provision("Audit regression organization")
    password = secrets.token_urlsafe(24)
    access.set_user("audit", password, "admin")
    token = access.login("audit", password)

    def request(method, path, *, session="A", **kwargs):
        async def send():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                         base_url="http://audit", cookies={COOKIE: token} if session == "A" else {}, headers={"Origin": "http://audit"}) as client:
                return await client.request(method, path, **kwargs)
        return asyncio.run(send())
    return request


def upload(clients, frame):
    response = clients("POST", "/api/datasets", files={"file": ("probe.csv", frame.to_csv(index=False).encode())}, data={"as_of": "2026-10-02", "confirmed": confirmation(frame.to_csv(index=False).encode(), "2026-10-02")})
    assert response.status_code == 201
    return response.json()["dataset_id"]


def test_release_gate_sensitive_dataset_list_requires_authentication(clients):
    assert clients("GET", "/api/datasets", session="anonymous").status_code == 401


def test_release_gate_configuration_write_requires_authentication(clients):
    assert clients("PUT", "/api/settings/priority", session="anonymous", json=PriorityConfig.load().to_dict()).status_code == 401


def test_release_gate_unrelated_session_cannot_read_dataset(clients):
    dataset_id = upload(clients, pd.DataFrame([sample(customer_email="ops@example.invalid")]))
    assert clients("GET", "/api/workspace", session="B", params={"dataset_id": dataset_id}).status_code in (401, 403, 404)


def test_release_gate_conflicting_currency_must_be_rejected_or_flagged(clients):
    dataset_id = upload(clients, pd.DataFrame([sample(shipment_id="A", currency="USD"), sample(shipment_id="B", currency="EUR")]))
    result = clients("GET", "/api/workspace", params={"dataset_id": dataset_id})
    if result.status_code == 200:
        assert any("currency" in str(row).lower() for row in result.json()["issues"])
    else:
        assert result.status_code in (400, 422)


def test_release_gate_readiness_detects_unavailable_database(clients, monkeypatch, tmp_path):
    monkeypatch.setenv("LOGISTICS_WEB_DB_PATH", str(tmp_path))
    assert clients("GET", "/api/workspace").status_code == 503
    assert clients("GET", "/api/ready").status_code == 503


def test_reordered_trimmed_uppercase_columns_supported():
    frame = pd.DataFrame([sample()]).iloc[:, ::-1].rename(columns=lambda name: " " + name.upper() + " ")
    loaded = load_shipments(frame.to_csv(index=False).encode(), "reordered.csv")
    assert calculate_kpis(analyze_shipments(loaded, "2026-10-02").shipments)["on_time_delivery_rate"] == 1


def test_public_transport_sample_has_attribution_but_not_shipment_schema():
    path = Path(__file__).parent / "fixtures/public_transport/airport_traffic.csv"
    public = pd.read_csv(path)
    assert len(public) == 221 and "airport" in public
    assert path.with_name("LICENSE").exists()
    with pytest.raises(DataInputError, match="Missing required columns"):
        load_shipments(path.read_bytes(), "public-airport-traffic.csv")


def test_iso_offsets_are_equivalent_and_date_only_is_midnight():
    same = sample(planned_delivery="2026-10-01T10:00:00+02:00", actual_delivery="2026-10-01T08:00:00Z")
    assert calculate_kpis(analyze_shipments(pd.DataFrame([same]), "2026-10-02").shipments)["on_time_delivery_rate"] == 1
    date_only = sample(planned_delivery="2026-10-01", actual_delivery="2026-10-01T15:00:00Z")
    # Current arithmetic is correct; an end-of-day customer promise needs a different input policy.
    assert analyze_shipments(pd.DataFrame([date_only]), "2026-10-02").shipments.iloc[0].delay_hours == 15


@pytest.mark.parametrize("payload", ['{"cost_weight":NaN}', '{"cost_weight":1e309}', '{"cost_weight":-1}', '{"count":true}'])
def test_bad_numeric_requests_return_client_errors(clients, payload):
    response = clients("POST", "/api/optimization/runs", content=payload, headers={"Content-Type": "application/json"})
    assert response.status_code in (400, 422)
    assert clients("GET", "/api/optimization/runs/latest").status_code == 404


def test_sql_parameters_do_not_interpret_injection(clients):
    assert clients("GET", "/api/workspace", params={"dataset_id": "' OR 1=1 --"}).status_code == 404
    assert clients("GET", "/api/cases", params={"shipment_id": "' OR 1=1 --"}).json() == []


def test_expected_time_feasibility_is_not_high_reliability():
    plan = PlanningData((Order("P", "A", "B", 1, 1, 48),),
                        (Service("S", "A", "B", "Air", 48, 12, 10, 10, 10),), (Candidate("P", "S", 100),))
    candidate = candidate_table(plan, Constraints(1000)).iloc[0]
    assert candidate.eligible
    assert candidate.assumed_late_probability == pytest.approx(.4510098623)
