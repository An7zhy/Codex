"""Uploaded plans use the original solver, strict units and the existing access boundary."""

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
import secrets
import time
from unittest.mock import patch

import httpx
import pandas as pd
import pytest

from backend.access import AccessStore, COOKIE
from backend.main import app
from backend.runtime import solver_slot
from backend.store import WorkspaceStore
from scripts.maintain_data import backup, restore, retain
from src.transport.input_contract import HEADERS, read_tables, validate_tables
from src.transport.templates import template_tables, workbook_bytes
from src.transport.uploaded import run_uploaded


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGISTICS_WEB_DB_PATH", str(tmp_path / "workspace.sqlite3"))
    monkeypatch.setenv("LOGISTICS_DB_PATH", str(tmp_path / "history.sqlite3"))
    monkeypatch.setenv("LOGISTICS_ALLOWED_ORIGINS", "http://test")
    monkeypatch.setenv("LOGISTICS_COOKIE_SECURE", "0")
    access = AccessStore(); access.provision("Upload pilot A")
    password = secrets.token_urlsafe(24)
    tokens = {}
    for role in ("admin", "operator", "viewer"):
        access.set_user(role, password, role); tokens[role] = access.login(role, password)
    def request(method, path, role="operator", token=None, origin="http://test", **kwargs):
        async def send():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test",
                cookies={COOKIE: token or tokens[role]} if role else {}, headers={"Origin": origin}) as client:
                return await client.request(method, path, **kwargs)
        return asyncio.run(send())
    request.access, request.tokens, request.password = access, tokens, password
    return request


def preview(api, tables=None, *, kind="xlsx", role="operator"):
    tables = template_tables() if tables is None else tables
    files = {"workbook": ("planning.xlsx", workbook_bytes(tables))} if kind == "xlsx" else {
        name: (name + ".csv", frame.to_csv(index=False).encode()) for name, frame in tables.items()}
    response = api("POST", "/api/planning/imports/preview", role=role, files=files)
    assert response.status_code == 201, response.text
    return response.json()


def confirm(api, item):
    response = api("POST", f'/api/planning/imports/{item["import_id"]}/confirm', json={"confirmation": item["confirmation"], "acknowledged": True})
    assert response.status_code == 200, response.text
    return response.json()


def test_mapping_and_hand_calculated_small_instance():
    result = validate_tables(template_tables())
    assert result["valid"] and not result["errors"]
    data = result["payload"]["data"]
    assert [row["deadline_hours"] for row in data["orders"]] == [48, 24]
    assert data["orders"][0]["weight_kg"] == 6 and data["orders"][0]["volume_m3"] == 1
    assert len(data["services"]) == 2  # not four per-order copies of shared capacity
    with patch("src.transport.experiments.generate_scenarios", side_effect=AssertionError("No invented distribution permitted")):
        solved = run_uploaded(result["payload"])
    by_strategy = {row["strategy"]: row for row in solved["summary"]}
    # Independent enumeration: ECO/FAST=40+80=120; FAST/ECO=100+50=150;
    # FAST/FAST=180. ECO/ECO violates shared capacity. Fastest is 12+12h.
    assert by_strategy["Lowest Cost"]["total_shipping_cost_usd"] == 120
    assert by_strategy["Fastest Delivery"]["total_shipping_cost_usd"] == 180
    assert by_strategy["Optimized Allocation"]["total_shipping_cost_usd"] == 120
    allocation = solved["results"]["Optimized Allocation"]["assignments"]
    assert {row["shipment_id"]: row["service_id"] for row in allocation} == {"UPLOAD-0001": "SHARED-ECO", "UPLOAD-0002": "SHARED-FAST"}
    assert sum(row["expected_hours"] for row in solved["results"]["Fastest Delivery"]["assignments"]) == 24
    assert solved["scenario_count"] == 0 and solved["simulation_details"] == {}
    assert all(row["assumed_late_probability"] is None for row in allocation + solved["candidate_checks"])
    assert all(row["simulated_on_time_rate_all_orders"] is None for row in solved["summary"])


@pytest.mark.parametrize("table,column,value", [
    ("transport_options", "currency", "EUR"), ("transport_options", "currency", ""),
    ("constraints", "currency", "CNY"), ("constraints", "penalty_currency", "EUR"),
    ("shipments", "weight_unit", "lb"), ("capacity", "weight_unit", "tonnes"),
    ("shipments", "volume_unit", "L"), ("capacity", "volume_unit", "cbm"),
    ("transport_options", "time_unit", "days"), ("transport_options", "quoted_cost", "-1"),
    ("transport_options", "quoted_cost", "NaN"), ("transport_options", "quoted_cost", "inf"),
    ("transport_options", "quoted_cost", "1,234"), ("transport_options", "quoted_cost", "1e309"),
    ("shipments", "weight", "0"), ("shipments", "volume", "0"),
    ("capacity", "shipment_capacity", "1.5"), ("capacity", "shipment_capacity", "true"),
    ("transport_options", "expected_transit_hours", "0"),
    ("shipments", "delivery_deadline", "2026-10-01"),
    ("shipments", "delivery_deadline", "2026-10-01T12:00:00"),
    ("constraints", "planning_start", "10/01/2026"),
    ("shipments", "delivery_deadline", "2026-09-01T00:00:00Z"),
    ("transport_options", "shipment_id", "missing"), ("transport_options", "service_id", "missing"),
    ("transport_options", "quote_status", "verified_by_app"), ("transport_options", "quote_reference", ""),
    ("capacity", "capacity_status", "live"), ("constraints", "allow_unassigned", "yes"),
    ("constraints", "time_limit_seconds", "11"), ("constraints", "source_label", ""),
    ("constraints", "data_kind", "real_verified"),
])
def test_no_guessing_or_silent_unit_currency_coercion(table, column, value):
    tables = template_tables(); tables[table].loc[0, column] = value
    result = validate_tables(tables)
    assert not result["valid"] and result["payload"] is None
    assert any(error["field"] == column for error in result["errors"])


@pytest.mark.parametrize("table", ["shipments", "capacity", "transport_options"])
def test_duplicate_ids_and_pairs_rejected(table):
    tables = template_tables(); tables[table] = pd.concat([tables[table], tables[table].iloc[[0]]], ignore_index=True)
    result = validate_tables(tables)
    assert not result["valid"] and any("Duplicate" in error["message"] for error in result["errors"])


def test_missing_extra_columns_empty_input_and_service_time_conflicts():
    for change in ("missing", "extra", "empty", "time"):
        tables = template_tables()
        if change == "missing": tables["shipments"] = tables["shipments"].drop(columns="weight_unit")
        elif change == "extra": tables["constraints"]["tenant_id"] = "other"
        elif change == "empty": tables["shipments"] = tables["shipments"].iloc[:0]
        else: tables["transport_options"].loc[2, "expected_transit_hours"] = "25"
        result = validate_tables(tables)
        assert not result["valid"] and result["error_count"] > 0


def test_timezones_and_verified_declarations_are_explicit():
    tables = template_tables()
    tables["shipments"].loc[0, "delivery_deadline"] = "2026-10-03T02:00:00+02:00"
    tables["transport_options"].loc[0, "quote_status"] = "user_verified"
    tables["transport_options"].loc[0, "quote_reference"] = "Uploader reviewed quote REF-1; not an app verification"
    result = validate_tables(tables)
    assert result["valid"] and result["payload"]["data"]["orders"][0]["deadline_hours"] == 48
    assert result["payload"]["declarations"]["quote"] == {"estimate": 3, "user_verified": 1}
    assert result["payload"]["preferences"]["risk"] == 0


def test_native_excel_boolean_is_not_mistaken_for_missing_soft_mode():
    tables = template_tables(); tables["constraints"].loc[0,"allow_unassigned"] = True
    loaded = read_tables({"workbook":("native.xlsx",workbook_bytes(tables))})
    result = validate_tables(loaded)
    assert result["valid"] and result["payload"]["constraints"]["allow_unassigned"] is True


@pytest.mark.parametrize("kind", ["xlsx", "csv"])
def test_api_preview_confirmation_solve_export_and_restart(api, kind):
    item = preview(api, kind=kind)
    assert item["status"] == "previewed" and item["created_by"] == "operator"
    assert item["record"]["row_counts"] == {"shipments": 2, "transport_options": 4, "capacity": 2, "constraints": 1}
    assert all(len(row["sha256"]) == 64 for row in item["record"]["files"])
    assert api("POST", "/api/planning/runs", json={"import_id": item["import_id"]}).status_code == 409
    confirmed = confirm(api, item)
    assert confirmed["confirmed_by"] == "operator" and confirmed["status"] == "confirmed"
    assert confirm(api, confirmed)["confirmed_at"] == confirmed["confirmed_at"]
    response = api("POST", "/api/planning/runs", json={"import_id": item["import_id"]})
    assert response.status_code == 201, response.text
    run = response.json()
    assert run["summary"][0]["total_shipping_cost_usd"] == 120
    assert run["input_mode"] == "uploaded" and run["scenario_count"] == 0
    assert run["planning_import"]["import_id"] == item["import_id"]
    restored = WorkspaceStore(api.access.path)
    assert restored.planning_import(item["import_id"])["status"] == "confirmed"
    assert restored.run(run["run_id"])["planning_import"]["confirmation"] == item["confirmation"]
    assert api("GET", "/api/optimization/runs/latest?input_mode=synthetic").status_code == 404
    assert api("GET", "/api/optimization/runs/latest?input_mode=uploaded").json()["run_id"] == run["run_id"]
    exported = api("GET", f'/api/optimization/runs/{run["run_id"]}/export/allocation')
    rows = pd.read_csv(BytesIO(exported.content))
    assert len(rows) == 2 and rows.cost_usd.sum() == 120
    assert rows.quote_status.eq("estimate").all() and rows.capacity_reference.str.contains("Synthetic").all()
    assert rows.assumed_late_probability.isna().all() and rows.import_id.eq(item["import_id"]).all()
    audited = api("GET", f'/api/planning/imports/{item["import_id"]}/export/json').json()
    assert audited["record"]["tables"]["shipments"][0]["weight_unit"] == "kg"


def test_api_invalid_preview_cannot_be_confirmed_or_rewritten(api):
    tables = template_tables(); tables["transport_options"].loc[0, "currency"] = "EUR"
    item = preview(api, tables)
    assert item["status"] == "invalid" and item["record"]["validation"]["error_count"] > 0
    assert api("POST", f'/api/planning/imports/{item["import_id"]}/confirm', json={"confirmation": item["confirmation"], "acknowledged": True}).status_code == 409
    assert api("POST", "/api/planning/runs", json={"import_id": item["import_id"], "data": {}}).status_code == 422
    item = preview(api)
    assert api("POST", f'/api/planning/imports/{item["import_id"]}/confirm', json={"confirmation": "0"*64, "acknowledged": True}).status_code == 409
    assert api("POST", f'/api/planning/imports/{item["import_id"]}/confirm', json={"confirmation": item["confirmation"], "acknowledged": False}).status_code == 400
    assert api("POST", f'/api/planning/imports/{item["import_id"]}/confirm', json={"confirmation": item["confirmation"], "acknowledged": 1}).status_code == 422


@pytest.mark.parametrize("method,path", [("GET", "/api/planning/contract"), ("GET", "/api/planning/templates/xlsx"),
    ("GET", "/api/planning/imports"), ("GET", "/api/planning/imports/unknown"), ("GET", "/api/planning/imports/unknown/export/json"),
    ("POST", "/api/planning/imports/preview"), ("POST", "/api/planning/imports/unknown/confirm"), ("POST", "/api/planning/runs"),
    ("DELETE", "/api/planning/imports/unknown")])
def test_new_routes_preserve_authentication(api, method, path):
    assert api(method, path, role=None).status_code == 401


def test_viewer_and_operator_permissions_and_origin(api):
    assert api("POST", "/api/planning/imports/preview", role="viewer").status_code == 403
    assert api("POST", "/api/planning/runs", role="viewer", json={}).status_code == 403
    item = preview(api)
    assert api("POST", f'/api/planning/imports/{item["import_id"]}/confirm', role="viewer", json={}).status_code == 403
    assert api("DELETE", f'/api/planning/imports/{item["import_id"]}').status_code == 403
    assert api("GET", f'/api/planning/imports/{item["import_id"]}/export/json', role="viewer").status_code == 200
    assert api("POST", "/api/planning/imports/preview", origin="https://evil.invalid").status_code == 403
    assert api("DELETE", f'/api/planning/imports/{item["import_id"]}', role="admin").status_code == 200


def test_independent_instance_and_server_identity_scope(api, tmp_path, monkeypatch):
    item = preview(api); token_a = api.tokens["operator"]
    monkeypatch.setenv("LOGISTICS_WEB_DB_PATH", str(tmp_path / "B/w.sqlite3")); monkeypatch.setenv("LOGISTICS_DB_PATH", str(tmp_path / "B/h.sqlite3"))
    b = AccessStore(); b.provision("Upload pilot B"); b.set_user("operator", api.password, "operator")
    token_b = b.login("operator", api.password)
    assert api("GET", f'/api/planning/imports/{item["import_id"]}', token=token_a).status_code == 401
    assert api("GET", "/api/planning/imports", token=token_b).json() == []
    assert api("GET", f'/api/planning/imports/{item["import_id"]}/export/json', token=token_b).status_code == 404
    assert api("POST", "/api/planning/runs", token=token_b, json={"import_id": item["import_id"]}).status_code == 404


def test_uploaded_100_orders_end_to_end_through_real_worker(api):
    item = confirm(api, preview(api, template_tables(100), kind="csv"))
    response = api("POST", "/api/planning/runs", json={"import_id": item["import_id"]})
    assert response.status_code == 201, response.text
    run = response.json()
    # 50 cheap slots go to odd orders (saving60 each vs30 for even): 50*40+50*80=6000.
    assert [row["total_shipping_cost_usd"] for row in run["summary"]] == [6000, 9000, 6000]
    assert all(row["assigned_orders"] == 100 and row["status"] == "OPTIMAL" for row in run["summary"])
    allocation = pd.read_csv(BytesIO(api("GET", f'/api/optimization/runs/{run["run_id"]}/export/allocation').content))
    assert len(allocation) == 100 and allocation.shipment_id.nunique() == 100
    assert (allocation.service_id == "SHARED-ECO").sum() == 50


@pytest.mark.parametrize("condition", ["budget", "weight", "volume", "slots", "deadline", "route", "no_options"])
def test_infeasibility_and_soft_assignment_are_not_fake_success(condition):
    tables = template_tables()
    if condition == "budget": tables["constraints"].loc[0, "budget"] = "100"
    elif condition in ("weight", "volume", "slots"):
        col = {"weight":"weight_capacity", "volume":"volume_capacity", "slots":"shipment_capacity"}[condition]
        tables["capacity"][col] = "0"
    elif condition == "deadline": tables["shipments"]["delivery_deadline"] = "2026-10-01T01:00:00Z"
    elif condition == "route": tables["capacity"]["destination"] = "Wrong destination"
    elif condition == "no_options": tables["transport_options"] = tables["transport_options"].iloc[:0]
    validated = validate_tables(tables); assert validated["valid"], validated["errors"]
    strict = run_uploaded(validated["payload"])
    assert all(row["status"] == "INFEASIBLE" and row["total_shipping_cost_usd"] is None for row in strict["summary"])
    assert strict["results"]["Optimized Allocation"]["diagnostics"]
    tables["constraints"].loc[0,"allow_unassigned"] = "true"
    soft = run_uploaded(validate_tables(tables)["payload"])
    assert all(row["status"] == "OPTIMAL" and row["unassigned_orders"] > 0 for row in soft["summary"])
    assert all(row["simulated_on_time_rate_all_orders"] is None for row in soft["summary"])


@pytest.mark.parametrize("status", ["FEASIBLE", "UNKNOWN", "MODEL_INVALID"])
def test_uploaded_adapter_preserves_solver_status(status, monkeypatch):
    monkeypatch.setattr("src.transport.engine.status_name", lambda actual: status)
    result = run_uploaded(validate_tables(template_tables())["payload"])
    assert all(row["status"] == status for row in result["summary"])
    if status != "FEASIBLE":
        assert all(row["total_shipping_cost_usd"] is None for row in result["summary"])
        assert not result["results"]["Optimized Allocation"]["assignments"]


def test_templates_limits_formulas_and_empty_files(api):
    contract = api("GET", "/api/planning/contract").json()
    assert "kg" in contract["fields"]["shipments"]["weight"]
    assert "Z/offset" in contract["fields"]["shipments"]["delivery_deadline"]
    for size in (0, 2, 100):
        response = api("GET", f"/api/planning/templates/xlsx?count={size}")
        assert response.status_code == 200, response.text
        tables = read_tables({"workbook":("template.xlsx",response.content)})
        assert len(tables["shipments"]) == size
    bad = api("POST", "/api/planning/imports/preview", files={"workbook":("empty.xlsx",b"")})
    assert bad.status_code == 201 and bad.json()["status"] == "invalid"
    tables = template_tables(); tables["transport_options"].loc[0,"quoted_cost"] = "=40+5"
    assert preview(api,tables)["status"] == "invalid"
    content = b"x" * (20 * 1024 * 1024 + 1)
    assert api("POST", "/api/planning/imports/preview", content=content).status_code == 413
    with solver_slot():
        item = confirm(api, preview(api))
        assert api("POST", "/api/planning/runs", json={"import_id":item["import_id"]}).status_code == 429


def test_uploaded_parse_budget_and_error_count_disclosure():
    tables = template_tables(100)
    oversized = {key: value.copy() for key, value in tables.items()}
    oversized["shipments"] = pd.concat([tables["shipments"]]*6,ignore_index=True)
    files = {name:(name+".csv",frame.to_csv(index=False).encode()) for name,frame in oversized.items()}
    with pytest.raises(ValueError,match="500 rows"):
        read_tables(files)
    tables["shipments"]["weight_unit"] = "lb"
    tables["shipments"]["volume_unit"] = "litre"
    tables["transport_options"]["currency"] = "EUR"
    result = validate_tables(tables)
    assert result["error_count"] == 400 and len(result["errors"]) == 200
    assert not result["valid"] and result["payload"] is None


def test_sparse_excel_tail_cannot_hide_unread_shipments():
    from openpyxl import load_workbook
    book = load_workbook(BytesIO(workbook_bytes(template_tables())))
    book["shipments"]["A1000"] = "LATE-ROW-MUST-NOT-BE-IGNORED"
    output = BytesIO(); book.save(output); book.close()
    with pytest.raises(ValueError, match="cannot be silently ignored"):
        read_tables({"workbook":("sparse.xlsx",output.getvalue())})


def test_deleted_source_cannot_be_resurrected_by_inflight_solve(api, monkeypatch):
    item = confirm(api, preview(api))
    result = run_uploaded(item["record"]["validation"]["payload"])
    def delete_then_return(*args, **kwargs):
        with WorkspaceStore(api.access.path).connect() as db:
            db.execute("DELETE FROM planning_imports WHERE import_id=?",(item["import_id"],))
        return result
    monkeypatch.setattr("backend.planning_routes.run_bounded", delete_then_return)
    assert api("POST", "/api/planning/runs", json={"import_id":item["import_id"]}).status_code == 409
    assert api("GET", "/api/optimization/runs/latest").status_code == 404


def test_infeasible_export_has_valid_empty_schema_and_trace_identifier(api):
    tables = template_tables(); tables["constraints"].loc[0, "budget"] = "100"
    item = confirm(api, preview(api,tables))
    response = api("POST", "/api/planning/runs", json={"import_id":item["import_id"]})
    assert response.status_code == 201
    run = response.json(); assert run["summary"][0]["status"] == "INFEASIBLE"
    exported = api("GET", f'/api/optimization/runs/{run["run_id"]}/export/allocation')
    frame = pd.read_csv(BytesIO(exported.content))
    assert frame.empty and {"shipment_id", "service_id", "cost_usd"}.issubset(frame.columns)
    assert exported.headers["X-Planning-Import"] == item["import_id"]
    assert item["import_id"] in exported.headers["content-disposition"]


def test_planning_backup_retention_and_import_quota(api, tmp_path):
    item = confirm(api,preview(api))
    solved = api("POST", "/api/planning/runs", json={"import_id":item["import_id"]})
    assert solved.status_code == 201
    run_id = solved.json()["run_id"]
    backup(tmp_path/"backup"); restore(tmp_path/"backup", tmp_path/"restore")
    restored = WorkspaceStore(tmp_path/"restore/workspace.sqlite3")
    copied = restored.planning_import(item["import_id"])
    assert copied["confirmation"] == item["confirmation"] and copied["confirmed_by"] == "operator"
    assert restored.run(run_id)["planning_import"]["import_id"] == item["import_id"]
    assert restored.run(run_id)["summary"][0]["total_shipping_cost_usd"] == 120
    store = WorkspaceStore(api.access.path)
    with store.connect() as db:
        db.execute("UPDATE planning_imports SET created_at=? WHERE import_id=?",((datetime.now(timezone.utc)-timedelta(days=40)).isoformat(),item["import_id"]))
    expired = retain()
    assert expired["planning_imports_deleted"] == 1 and expired["runs_deleted"] == 1
    assert api("GET", f'/api/planning/imports/{item["import_id"]}').status_code == 404
    assert api("GET", f'/api/optimization/runs/{run_id}').status_code == 404
    with store.connect() as db:
        db.executemany("INSERT INTO planning_imports VALUES (?,?,?,?,NULL,NULL,?,?)",[(str(i),"invalid","2026-01-01","test","0"*64,"{}") for i in range(100)])
    assert api("POST", "/api/planning/imports/preview", files={"workbook":("input.xlsx",workbook_bytes(template_tables()))}).status_code == 507
