"""Release requirements exercised through the real ASGI boundary and temporary DBs."""

import asyncio
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
from pathlib import Path
import secrets
import sqlite3
import subprocess
from unittest.mock import patch
from zipfile import ZipFile, ZIP_DEFLATED

import httpx
import pandas as pd
import pytest

from backend.access import AccessStore, COOKIE
from backend.import_contract import confirmation
from backend.main import app
from backend.runtime import run_bounded, solver_slot
from backend.schemas import OptimizationRequest
from backend.store import WorkspaceStore
from scripts.audit_readiness import sample
from scripts.maintain_data import backup, restore, retain
from src.analysis import analyze_shipments, calculate_kpis
from src.decisions import default_assumptions
from src.history import CaseInput, HistoryStore
from src.ingestion import load_shipments, DataInputError
from src.priority import PriorityConfig


@pytest.fixture
def secured(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGISTICS_WEB_DB_PATH", str(tmp_path / "workspace.sqlite3"))
    monkeypatch.setenv("LOGISTICS_DB_PATH", str(tmp_path / "history.sqlite3"))
    monkeypatch.setenv("LOGISTICS_ALLOWED_ORIGINS", "http://test")
    monkeypatch.setenv("LOGISTICS_COOKIE_SECURE", "0")
    access = AccessStore()
    access.provision("Pilot A")
    password = secrets.token_urlsafe(24)
    tokens = {}
    for role in ("admin", "operator", "viewer"):
        access.set_user(role, password, role)
        tokens[role] = access.login(role, password)

    def request(method, path, role="admin", origin="http://test", token=None, **kwargs):
        async def send():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test",
                    cookies={COOKIE: token or tokens[role]} if role else {}, headers={"Origin": origin} if origin else {}) as client:
                return await client.request(method, path, **kwargs)
        return asyncio.run(send())
    request.access, request.tokens, request.password = access, tokens, password
    return request


def upload(client, frame, day="2026-10-02"):
    content = frame.to_csv(index=False).encode()
    response = client("POST", "/api/datasets/preview", files={"file": ("input.csv", content)}, data={"as_of": day})
    assert response.status_code == 200, response.text
    preview = response.json()
    response = client("POST", "/api/datasets", files={"file": ("input.csv", content)}, data={"as_of": day, "confirmed": preview["confirmation"]})
    assert response.status_code == 201, response.text
    return response.json()["dataset_id"], preview


def decision(**extra):
    return dict(dataset_id="demo", as_of="2026-10-01", shipment_id="SYN-0027",
                assumptions=[asdict(item) for item in default_assumptions()], **extra)


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/workspace"), ("GET", "/api/datasets"), ("GET", "/api/exceptions"),
    ("GET", "/api/settings"), ("GET", "/api/cases"), ("GET", "/api/cases/export"),
    ("GET", "/api/exports/shipments"), ("GET", "/api/exports/report"),
    ("GET", "/api/optimization/runs/latest"), ("GET", "/api/optimization/runs/id/export/json"),
    ("GET", "/api/decisions/defaults"), ("GET", "/api/evaluation"), ("GET", "/api/demo/xlsx"),
    ("POST", "/api/datasets"), ("POST", "/api/datasets/preview"), ("POST", "/api/cases"),
    ("POST", "/api/optimization/runs"), ("PUT", "/api/settings/priority"),
    ("PATCH", "/api/cases/id"), ("DELETE", "/api/datasets/id"), ("GET", "/api/auth/session"),
])
def test_all_sensitive_routes_reject_anonymous_before_validation(secured, method, path):
    response = secured(method, path, role=None)
    assert response.status_code == 401
    assert "no-store" in response.headers["cache-control"]
    assert response.headers["x-request-id"]


@pytest.mark.parametrize("method,path", [("POST", "/api/datasets"), ("POST", "/api/cases"), ("PATCH", "/api/cases/id"),
    ("POST", "/api/optimization/runs"), ("PUT", "/api/settings/priority"), ("DELETE", "/api/datasets/id")])
def test_viewer_cannot_write_even_with_valid_cookie(secured, method, path):
    assert secured(method, path, role="viewer").status_code == 403


def test_roles_allow_same_organization_reads_but_settings_require_admin(secured):
    dataset, _ = upload(secured, pd.DataFrame([sample()]))
    for role in ("admin", "operator", "viewer"):
        response = secured("GET", "/api/workspace", role=role, params={"dataset_id": dataset})
        assert response.status_code == 200 and response.json()["kpis"]["total_shipments"] == 1
    assert secured("PUT", "/api/settings/priority", role="operator", json=PriorityConfig.load().to_dict()).status_code == 403
    assert secured("DELETE", f"/api/datasets/{dataset}", role="operator").status_code == 403


@pytest.mark.parametrize("origin", [None, "https://evil.example", "null"])
def test_write_origin_and_login_csrf_are_rejected(secured, origin):
    assert secured("PUT", "/api/settings/priority", origin=origin, json=PriorityConfig.load().to_dict()).status_code == 403
    assert secured("POST", "/api/auth/login", role=None, origin=origin, json={"username": "admin", "password": secured.password}).status_code == 403


def test_login_cookie_logout_rotation_expiration_and_disable(secured, monkeypatch):
    response = secured("POST", "/api/auth/login", role=None, json={"username": "admin", "password": secured.password})
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Path=/api" in cookie
    token = response.cookies.get(COOKIE)
    assert token != secured.tokens["admin"]
    with secured.access.connect() as db:
        assert not db.execute("SELECT 1 FROM access_sessions WHERE token_hash=?", (token,)).fetchone()
    assert secured("GET", "/api/auth/session", token=token).json()["organization"] == "Pilot A"
    assert secured("POST", "/api/auth/logout", token=token).status_code == 200
    assert secured("GET", "/api/workspace", token=token).status_code == 401
    with secured.access.connect() as db:
        db.execute("UPDATE access_sessions SET expires_at=0 WHERE username='operator'")
    assert secured("GET", "/api/cases", role="operator").status_code == 401
    secured.access.disable_user("viewer")
    assert secured("GET", "/api/cases", role="viewer").status_code == 401
    monkeypatch.setenv("LOGISTICS_COOKIE_SECURE", "1")
    response = secured("POST", "/api/auth/login", role=None, json={"username": "admin", "password": secured.password})
    assert "Secure" in response.headers["set-cookie"]


def test_invalid_login_rate_limited_and_no_passwords_in_events(secured):
    results = [secured("POST", "/api/auth/login", role=None, json={"username": "missing", "password": "incorrect password"}).status_code for _ in range(6)]
    assert results == [401] * 5 + [429]
    with secured.access.connect() as db:
        assert secured.password not in str(db.execute("SELECT * FROM access_events").fetchall())


def test_invalid_password_is_not_echoed_in_validation_errors(secured):
    password = "sensitive-input-" * 40
    response = secured("POST", "/api/auth/login", role=None, json={"username": "admin", "password": password})
    assert response.status_code == 422 and password not in response.text


def test_forged_session_and_client_tenant_do_not_grant_access(secured):
    assert secured("GET", "/api/datasets?tenant_id=PilotA", token="forged").status_code == 401
    assert secured("GET", "/api/workspace", role=None, headers={"X-Tenant-ID": "Pilot A", "X-Role": "admin"}).status_code == 401


def test_separate_organization_instance_cannot_use_other_session_or_ids(secured, tmp_path, monkeypatch):
    dataset, _ = upload(secured, pd.DataFrame([sample(customer_email="private@example.invalid")]))
    a_token = secured.tokens["admin"]
    monkeypatch.setenv("LOGISTICS_WEB_DB_PATH", str(tmp_path / "B/web.sqlite3"))
    monkeypatch.setenv("LOGISTICS_DB_PATH", str(tmp_path / "B/cases.sqlite3"))
    b = AccessStore(); b.provision("Pilot B"); b.set_user("admin", secured.password, "admin")
    assert secured("GET", "/api/datasets", token=a_token).status_code == 401
    b_token = b.login("admin", secured.password)
    assert secured("GET", "/api/auth/session", token=b_token).json()["organization"] == "Pilot B"
    assert secured("GET", "/api/workspace", token=b_token, params={"dataset_id": dataset}).status_code == 404
    assert secured("GET", "/api/cases", token=b_token).json() == []
    assert secured("GET", "/api/optimization/runs/latest", token=b_token).status_code == 404
    with pytest.raises(ValueError, match="another organization"):
        b.provision("Pilot A")
    monkeypatch.setenv("LOGISTICS_DB_PATH", str(tmp_path / "history.sqlite3"))
    assert secured("GET", "/api/workspace", token=b_token).status_code == 503


def test_currency_exclusion_applies_core_kpis_cost_threshold_and_report(secured):
    frame = pd.DataFrame([sample(shipment_id="USD", currency="USD"), sample(shipment_id="EUR", currency="EUR", shipping_cost=99999), sample(shipment_id="BLANK", currency="")])
    dataset, preview = upload(secured, frame)
    assert preview["kpis"]["total_shipping_cost"] == 100
    result = secured("GET", "/api/workspace", params={"dataset_id": dataset}).json()
    assert result["kpis"]["cost_eligible_shipments"] == 1 and result["kpis"]["total_shipping_cost"] == 100
    assert sum(row["code"] == "unsupported_currency" for row in result["issues"]) == 2
    assert not any(row["is_cost_anomaly"] for row in result["shipments"])
    report = secured("GET", "/api/exports/report", params={"dataset_id": dataset}).text
    assert "100.00" in report and "99999.00" not in report


def test_import_preview_and_explicit_confirmation_cover_duplicates_dates(secured):
    frame = pd.DataFrame([sample(planned_delivery="2026-10-01", actual_delivery="2026-10-01T15:00:00Z"), sample(status="In Transit", actual_delivery="")])
    content = frame.to_csv(index=False).encode()
    assert secured("POST", "/api/datasets", files={"file": ("input.csv", content)}, data={"as_of": "2026-10-02"}).status_code == 409
    _, preview = upload(secured, frame)
    assert preview["duplicate_rows"] == 2 and len(preview["conflict_preview"]) == 2
    assert preview["date_precision"]["planned_delivery"]["date_only"] == 1
    assert preview["kpis"]["excluded_rows"] == 1 and preview["kpis"]["average_delay_hours"] == 15
    assert "NOT end of day" in preview["rules"]["dates"]
    assert secured("POST", "/api/datasets", files={"file": ("input.csv", content + b"\n")}, data={"as_of": "2026-10-02", "confirmed": preview["confirmation"]}).status_code == 409


def test_comparison_context_pinning_and_unavailable_actions(secured):
    body = decision()
    compared = secured("POST", "/api/decisions/compare", json=body).json()
    save = dict(**body, selected_action="Request expedited handling", exception_type="Overdue in transit", comparison_token=compared["comparison_token"])
    cfg = PriorityConfig.load().to_dict(); cfg["weights"]["financial"] = 100
    assert secured("PUT", "/api/settings/priority", json=cfg).status_code == 200
    assert secured("POST", "/api/cases", json=save).status_code == 409
    assert secured("GET", "/api/cases").json() == []
    body["assumptions"][1]["assumed_available"] = False
    compared = secured("POST", "/api/decisions/compare", json=body).json()
    save.update(assumptions=body["assumptions"], comparison_token=compared["comparison_token"])
    assert secured("POST", "/api/cases", json=save).status_code == 400
    save["selected_action"] = "Wait and monitor"
    saved = secured("POST", "/api/cases", json=save)
    assert saved.status_code == 201
    snapshot = json.loads(saved.json()["priority_snapshot_json"])
    assert snapshot["priority_score"] == 88.1481 and snapshot["actor"] == "admin"
    assert secured("POST", "/api/cases", json=save).json()["case_id"] == saved.json()["case_id"]


def test_full_exception_queue_and_history_export_exceed_old_caps(secured):
    frame = pd.DataFrame([sample(shipment_id=f"Q-{i:04d}", status="In Transit", actual_delivery="") for i in range(501)])
    dataset, _ = upload(secured, frame)
    all_ids = []
    for offset in (0, 200, 400):
        response = secured("GET", "/api/exceptions", params={"dataset_id": dataset, "actionable_only": True, "limit": 200, "offset": offset})
        assert response.status_code == 200
        page = response.json(); assert page["total"] == 501
        all_ids.extend(row["shipment_id"] for row in page["items"])
    assert len(set(all_ids)) == 501 and "Q-0500" in all_ids
    assert secured("GET", "/api/exceptions", params={"dataset_id": dataset, "q": "Q-0500", "actionable_only": True}).json()["items"][0]["shipment_id"] == "Q-0500"
    history = HistoryStore(secured.access.history_path)
    for index in range(1003):
        history.create_case(CaseInput(str(index), "Overdue in transit", "Wait and monitor"))
    exported = pd.read_csv(BytesIO(secured("GET", "/api/cases/export").content))
    assert len(exported) == 1003 and exported.shipment_id.nunique() == 1003
    assert len(secured("GET", "/api/cases?offset=1000&limit=200").json()) == 3


def test_complete_body_limit_and_extra_parts_rejected_before_import(secured):
    response = secured("POST", "/api/datasets", content=b"x" * (20 * 1024 * 1024 + 1))
    assert response.status_code == 413
    response = secured("POST", "/api/datasets/preview", files=[("file", ("ok.csv", pd.DataFrame([sample()]).to_csv(index=False).encode())), ("ignored", ("extra.bin", b"x"))], data={"as_of": "2026-10-02"})
    assert response.status_code == 400 and "one file" in response.text


def test_chunked_body_cannot_bypass_total_limit(secured):
    async def chunks():
        for _ in range(21):
            yield b"x" * (1024 * 1024)
    assert secured("POST", "/api/datasets", content=chunks()).status_code == 413


def test_pilot_mode_requires_https_secure_cookie_configuration(secured, monkeypatch):
    monkeypatch.setenv("LOGISTICS_PILOT_MODE", "1")
    assert secured("GET", "/api/ready").status_code == 503
    assert secured("GET", "/api/health", role=None).status_code == 200
    monkeypatch.setenv("LOGISTICS_COOKIE_SECURE", "1")
    monkeypatch.setenv("LOGISTICS_ALLOWED_ORIGINS", "https://pilot.example.invalid")
    assert secured("GET", "/api/ready").status_code == 200


def test_workspace_quota_rejects_before_storage_write(secured, monkeypatch):
    store = WorkspaceStore(secured.access.path)
    with store.connect() as db:
        # Tiny SQLite strings stand in for the retention COUNT boundary.
        db.executemany("INSERT INTO web_runs VALUES (?,?,?)", [(f"R{i}", "{}", "2026-01-01") for i in range(200)])
    with pytest.raises(Exception) as rejected:
        store.save_run("{}")
    assert rejected.value.status_code == 507
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM web_runs").fetchone()[0] == 200


def test_case_quota_preserves_idempotent_retry(secured):
    store = HistoryStore(secured.access.history_path)
    case = CaseInput("ONE", "Data quality", "Wait and monitor")
    first = store.create_case(case, idempotency_key="same", max_records=1)
    assert store.create_case(case, idempotency_key="same", max_records=1) == first
    with pytest.raises(ValueError, match="Case retention quota"):
        store.create_case(CaseInput("TWO", "Data quality", "Wait and monitor"), max_records=1)
    assert len(store.export_cases()) == 1


def test_xlsx_expansion_and_column_budget():
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("xl/sharedStrings.xml", b"0" * (2 * 1024 * 1024))
    with pytest.raises(DataInputError, match="compression ratio"):
        load_shipments(output.getvalue(), "bomb.xlsx")
    with pytest.raises(DataInputError, match="128 columns"):
        load_shipments((",".join(f"c{i}" for i in range(129)) + "\n").encode(), "wide.csv")


def test_solver_concurrency_timeout_and_simulation_budget(secured):
    with solver_slot():
        response = secured("POST", "/api/optimization/runs", json={"scenario_count": 100})
        assert response.status_code == 429
    with patch("backend.runtime.subprocess.run", side_effect=subprocess.TimeoutExpired("worker", 45)):
        response = secured("POST", "/api/optimization/runs", json={"scenario_count": 100})
        assert response.status_code == 504
    assert secured("GET", "/api/optimization/runs/latest").status_code == 404
    assert secured("POST", "/api/optimization/runs", json={"count": 500, "scenario_count": 10000}).status_code == 422
    # The lease was released on every rejection/timeout.
    with solver_slot():
        pass


def test_solver_real_worker_is_killed_and_reaped_on_scaled_timeout(secured, monkeypatch):
    import backend.runtime as runtime
    actual_popen = subprocess.Popen
    children = []
    def observe(*args, **kwargs):
        child = actual_popen(*args, **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(runtime, "SOLVER_WALL_SECONDS", .05)
    with patch("backend.runtime.subprocess.Popen", side_effect=observe):
        response = secured("POST", "/api/optimization/runs", json={"scenario_count": 100})
    assert response.status_code == 504
    assert len(children) == 1 and children[0].poll() is not None
    assert secured("GET", "/api/optimization/runs/latest").status_code == 404
    with solver_slot():
        pass


def test_dataset_delete_and_backup_restore_retention(secured, tmp_path):
    dataset, _ = upload(secured, pd.DataFrame([sample()]))
    history = HistoryStore(secured.access.history_path)
    case = history.create_case(CaseInput("X", "Data quality", "Wait and monitor", priority_snapshot_json=json.dumps({"dataset": {"dataset_id": dataset}})))
    manifest = backup(tmp_path / "backup")
    assert manifest["files"]["workspace.sqlite3"]["counts"]["web_datasets"] == 2
    result = restore(tmp_path / "backup", tmp_path / "restored")
    assert result["sessions_revoked"] and result["integrity"]["workspace.sqlite3"]["access_sessions"] == 0
    assert result["integrity"]["history.sqlite3"]["cases"] == 1
    assert secured("DELETE", f"/api/datasets/{dataset}").status_code == 200
    assert secured("GET", "/api/workspace", params={"dataset_id": dataset}).status_code == 404
    with pytest.raises(LookupError): history.get_case(case)
    assert secured("DELETE", "/api/datasets/demo").status_code == 400
    dataset, _ = upload(secured, pd.DataFrame([sample()]))
    with WorkspaceStore(secured.access.path).connect() as db:
        db.execute("UPDATE web_datasets SET created_at=? WHERE dataset_id=?", ((datetime.now(timezone.utc)-timedelta(days=40)).isoformat(), dataset))
    assert retain()["datasets_deleted"] == 1
    (tmp_path / "backup/history.sqlite3").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="checksum"):
        restore(tmp_path / "backup", tmp_path / "refused")
    assert not (tmp_path / "refused").exists()
