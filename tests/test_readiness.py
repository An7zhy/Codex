"""Durable settings CAS and a genuinely sealed, account-free demo boundary."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from fastapi import HTTPException

from backend.access import AccessStore, COOKIE
from backend.demo_policy import DemoBudget, validate_demo
from backend.deployment import check_storage_bound
from backend.main import app
from backend.store import WorkspaceStore
from scripts.prepare_demo import prepare
from src.decisions import default_assumptions
from src.history import CaseInput, HistoryStore
from src.priority import PriorityConfig


@pytest.fixture
def business(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGISTICS_INSTANCE_MODE", "business")
    monkeypatch.setenv("LOGISTICS_WEB_DB_PATH", str(tmp_path / "business/workspace.sqlite3"))
    monkeypatch.setenv("LOGISTICS_DB_PATH", str(tmp_path / "business/history.sqlite3"))
    monkeypatch.setenv("LOGISTICS_ALLOWED_ORIGINS", "http://test")
    monkeypatch.setenv("LOGISTICS_PILOT_MODE", "0")
    monkeypatch.setenv("LOGISTICS_COOKIE_SECURE", "0")
    monkeypatch.delenv("LOGISTICS_REQUIRE_BOUNDED_STORAGE", raising=False)
    access = AccessStore(); access.provision("Synthetic readiness test organization")
    password = secrets.token_urlsafe(24); tokens = {}
    for name, role in (("a", "admin"), ("b", "admin"), ("viewer", "viewer"), ("operator", "operator")):
        access.set_user(name, password, role); tokens[name] = access.login(name, password)
    storage = WorkspaceStore(access.path)
    return access, storage, tokens


def request(method, url, token=None, **kwargs):
    async def send():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                base_url="http://test", cookies={COOKIE: token} if token else {}, headers={"Origin": "http://test"}) as client:
            return await client.request(method, url, **kwargs)
    return asyncio.run(send())


def test_original_audit_two_admin_scenario_is_409_and_preserves_first_write(business):
    access, storage, tokens = business
    original = request("GET", "/api/settings", tokens["a"]).json()
    a = deepcopy(original["priority"]); b = deepcopy(a)
    a["weights"]["urgency"] = 81; b["weights"]["financial"] = 82
    first = request("PUT", "/api/settings/priority", tokens["a"], json={**a, "expected_version": original["version"]})
    stale = request("PUT", "/api/settings/priority", tokens["b"], json={**b, "expected_version": original["version"]})
    assert first.status_code == 200 and stale.status_code == 409
    final = request("GET", "/api/settings", tokens["b"]).json()
    assert final["priority"]["weights"]["urgency"] == 81
    assert final["priority"]["weights"]["financial"] == 20
    assert final["version"] == original["version"] + 1
    assert WorkspaceStore(access.path).setting_snapshot("priority")["version"] == final["version"]
    history = request("GET", "/api/settings/priority/history", tokens["a"]).json()
    assert len(history) == 1 and history[0]["actor"] == "a" and history[0]["changed_at"]
    assert history[0]["old_version"] == original["version"] and history[0]["new_version"] == final["version"]
    assert history[0]["diff"] == {"weights.urgency": {"before": 30, "after": 81}}
    revised = deepcopy(final["priority"]); revised["weights"]["financial"] = 82
    assert request("PUT", "/api/settings/priority", tokens["b"], json={**revised,"expected_version":final["version"]}).status_code == 200
    assert storage.setting_snapshot("priority")["priority"]["weights"]["urgency"] == 81


def test_true_concurrent_sqlite_connections_have_exactly_one_winner(business):
    access, storage, _ = business
    base = storage.setting_snapshot("priority")
    def save(actor):
        value = deepcopy(base["priority"]); value["weights"]["urgency"] = 80 if actor == "a" else 90
        try:
            return storage.save_setting("priority", value, expected_version=base["version"], actor=actor)["version"]
        except HTTPException as exc:
            return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(save, ("a", "b")))
    assert sorted(result) == [2, 409]
    assert storage.setting_snapshot("priority")["version"] == 2
    assert len(storage.setting_history(100,0)) == 1


@pytest.mark.parametrize("version", [None, True, 0, -1, 1.5, "1"])
def test_version_is_mandatory_strict_integer(business, version):
    _, storage, tokens = business
    body = PriorityConfig.load().to_dict()
    if version is not None: body["expected_version"] = version
    assert request("PUT", "/api/settings/priority", tokens["a"], json=body).status_code == 422
    assert storage.setting_snapshot("priority")["version"] == 1 and storage.setting_history(100,0) == []


@pytest.mark.parametrize("role", [None, "viewer", "operator"])
def test_settings_version_and_audit_do_not_bypass_roles(business, role):
    _, _, tokens = business; token = tokens.get(role)
    body = {**PriorityConfig.load().to_dict(), "expected_version": 1}
    expected = 401 if role is None else 403
    assert request("PUT", "/api/settings/priority", token, json=body).status_code == expected
    assert request("GET", "/api/settings/priority/history", token).status_code == expected


def test_aba_change_invalidates_old_comparison_even_when_config_values_match(business):
    _, storage, tokens = business
    body = dict(dataset_id="demo", as_of="2026-10-01", shipment_id="SYN-0027", assumptions=[asdict(x) for x in default_assumptions()])
    old = request("POST", "/api/decisions/compare", tokens["a"], json=body).json()
    original = storage.setting_snapshot("priority")
    changed = deepcopy(original["priority"]); changed["weights"]["financial"] = 100
    storage.save_setting("priority", changed, expected_version=1, actor="a")
    storage.save_setting("priority", original["priority"], expected_version=2, actor="b")
    now = request("POST", "/api/decisions/compare", tokens["a"], json=body).json()
    assert old["priority_score"] == now["priority_score"] == 78.6667
    assert now["config_version"] == 3 and old["comparison_token"] != now["comparison_token"]
    save = {**body,"selected_action":"Wait and monitor","exception_type":"Overdue in transit","comparison_token":old["comparison_token"]}
    assert request("POST", "/api/cases", tokens["a"], json=save).status_code == 409


def test_additive_old_settings_migration_preserves_values_and_assigns_version_one(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGISTICS_INSTANCE_MODE", "business")
    path = tmp_path / "old.sqlite3"
    cfg = PriorityConfig.load().to_dict(); cfg["weights"]["financial"] = 82
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE web_settings(setting_key TEXT PRIMARY KEY,value_json TEXT NOT NULL)")
        db.execute("INSERT INTO web_settings VALUES ('priority',?)",(json.dumps(cfg),))
    snapshot = WorkspaceStore(path).setting_snapshot("priority")
    assert snapshot == {"priority":cfg,"version":1}
    assert WorkspaceStore(path).setting_snapshot("priority") == snapshot


@pytest.fixture(scope="module")
def seed(tmp_path_factory):
    root = tmp_path_factory.mktemp("readiness-seeds") / "sealed"
    prepare(root)
    yield root
    root.chmod(0o755)


@pytest.fixture
def demo(seed, monkeypatch):
    monkeypatch.setenv("LOGISTICS_INSTANCE_MODE", "demo")
    monkeypatch.setenv("LOGISTICS_DEMO_ROOT", str(seed))
    monkeypatch.setenv("LOGISTICS_PILOT_MODE", "0")
    monkeypatch.delenv("LOGISTICS_WEB_DB_PATH", raising=False)
    monkeypatch.delenv("LOGISTICS_DB_PATH", raising=False)
    # Isolate budgets between tests; production uses a single bounded worker.
    for middleware in (app.middleware_stack,):
        current = middleware
        while current:
            if hasattr(current,"demo_budget"): current.demo_budget = DemoBudget()
            current = getattr(current,"app",None)
    return seed


def test_demo_is_account_free_read_only_and_has_actual_calculated_outputs(demo):
    before = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in demo.iterdir()}
    session = request("GET", "/api/auth/session").json()
    assert session["role"] == "viewer" and session["read_only_demo"] is True
    workspace = request("GET", "/api/workspace").json()
    assert workspace["kpis"]["total_shipments"] == 158 and workspace["kpis"]["total_shipping_cost"] == 539830.75
    assert request("GET", "/api/cases").json()[0]["shipment_id"] == "SYN-0027"
    run = request("GET", "/api/optimization/runs/latest").json()
    assert run["scenario_count"] == 1000 and run["provenance"].startswith("Synthetic")
    assert request("GET", f'/api/optimization/runs/{run["run_id"]}/export/allocation').status_code == 200
    assert request("GET", "/api/ready").json()["read_only_demo"]
    assert before == {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in demo.iterdir()}
    assert not list(demo.glob('*-wal'))


@pytest.mark.parametrize("method,path", [
    ("POST","/api/auth/login"),("POST","/api/datasets"),("POST","/api/datasets/preview"),
    ("POST","/api/planning/imports/preview"),("POST","/api/planning/runs"),("POST","/api/optimization/runs"),
    ("POST","/api/decisions/compare"),("POST","/api/cases"),("PATCH","/api/cases/id"),
    ("PUT","/api/settings/priority"),("DELETE","/api/datasets/demo")])
def test_demo_denies_writes_before_parsing_even_with_forged_admin(demo, method, path):
    response = request(method, path, token="production-or-forged-token", headers={"X-Role":"admin"}, content=b"malformed input")
    assert response.status_code == 403


def test_demo_no_account_store_and_no_mutable_sql_connections(demo):
    with pytest.raises(HTTPException): AccessStore()
    store = WorkspaceStore(demo / "workspace.sqlite3")
    with pytest.raises(sqlite3.OperationalError,match="readonly"):
        with store.connect() as db: db.execute("DELETE FROM web_datasets")
    with pytest.raises(sqlite3.OperationalError,match="readonly"):
        HistoryStore(demo / "history.sqlite3",read_only=True).create_case(CaseInput("bad","Data quality","Wait and monitor"))


def test_demo_refuses_business_path_overrides_before_touching_databases(demo, tmp_path, monkeypatch):
    path = tmp_path / "real/workspace.sqlite3"
    monkeypatch.setenv("LOGISTICS_WEB_DB_PATH",str(path))
    assert request("GET", "/api/workspace").status_code == 503
    assert not path.parent.exists()


def test_business_accounts_and_scope_cannot_be_reused_in_demo(business, seed, monkeypatch):
    access, storage, tokens = business
    original = hashlib.sha256(access.path.read_bytes()).hexdigest()
    monkeypatch.setenv("LOGISTICS_INSTANCE_MODE","demo"); monkeypatch.setenv("LOGISTICS_DEMO_ROOT",str(seed))
    assert request("GET","/api/workspace",tokens["a"]).status_code == 503  # conflicting business paths
    monkeypatch.delenv("LOGISTICS_WEB_DB_PATH"); monkeypatch.delenv("LOGISTICS_DB_PATH")
    assert request("GET","/api/auth/session",tokens["a"]).json()["username"] == "synthetic-visitor"
    monkeypatch.setenv("LOGISTICS_INSTANCE_MODE","business"); monkeypatch.setenv("LOGISTICS_WEB_DB_PATH",str(access.path)); monkeypatch.setenv("LOGISTICS_DB_PATH",str(access.history_path))
    assert request("GET","/api/workspace").status_code == 401
    assert hashlib.sha256(access.path.read_bytes()).hexdigest() == original


def test_seed_rebuild_never_overwrites_existing_directory(seed):
    with pytest.raises(FileExistsError): prepare(seed)


def test_demo_refuses_tampered_seed_and_recovers_with_original_files(demo, tmp_path, monkeypatch):
    import shutil
    copy = tmp_path / "tampered"; shutil.copytree(demo,copy); copy.chmod(0o755)
    path = copy / "workspace.sqlite3"; path.chmod(0o644)
    path.write_bytes(path.read_bytes()+b"tampered")
    monkeypatch.setenv("LOGISTICS_DEMO_ROOT",str(copy))
    assert request("GET","/api/workspace").status_code == request("GET","/api/ready").status_code == 503
    assert request("GET","/api/health").status_code == 200
    path.write_bytes((demo / path.name).read_bytes())
    assert request("GET","/api/workspace").status_code == 200


def test_demo_cannot_bless_modified_business_data_even_with_updated_manifest(demo,tmp_path,monkeypatch):
    import shutil
    copy=tmp_path/"changed"; shutil.copytree(demo,copy); copy.chmod(0o755)
    path=copy/"workspace.sqlite3";path.chmod(0o644)
    with sqlite3.connect(path) as db: db.execute("UPDATE web_datasets SET raw_json=replace(raw_json,'SYN-0027','CUSTOMER-SECRET')")
    manifest=copy/"manifest.json";manifest.chmod(0o644);data=json.loads(manifest.read_text());data["files"][path.name]=hashlib.sha256(path.read_bytes()).hexdigest();manifest.write_text(json.dumps(data))
    monkeypatch.setenv("LOGISTICS_DEMO_ROOT",str(copy))
    assert request("GET","/api/workspace").status_code == 503


def test_demo_budget_limits_releases_on_error_and_resets():
    budget=DemoBudget()
    with budget.slot(),budget.slot():
        with pytest.raises(HTTPException) as e:
            with budget.slot(): pass
        assert e.value.status_code == 429
    assert budget.active == 0
    with pytest.raises(RuntimeError):
        with budget.slot(): raise RuntimeError("test")
    assert budget.active == 0
    budget.count=120
    with pytest.raises(HTTPException):
        with budget.slot(): pass
    budget.started -= 61
    with budget.slot(): assert budget.count == 1


def test_demo_query_and_get_body_are_bounded(demo):
    assert request("GET","/api/workspace?q="+"x"*1025).status_code == 413
    assert request("GET","/api/workspace",content=b"upload disguised as GET").status_code == 413
    assert request("GET","/api/settings/priority/history").status_code == 403


def test_deployment_refuses_unbounded_or_exhausted_storage(business,monkeypatch):
    monkeypatch.setenv("LOGISTICS_REQUIRE_BOUNDED_STORAGE","1")
    for blocks,available in ((2*1024**3,100*1024**2),(512*1024**2,1)):
        monkeypatch.setattr(os,"statvfs",lambda _:SimpleNamespace(f_blocks=blocks,f_bavail=available,f_frsize=1))
        with pytest.raises(HTTPException) as e: check_storage_bound()
        assert e.value.status_code == 503
    monkeypatch.setattr(os,"statvfs",lambda _:SimpleNamespace(f_blocks=512*1024**2,f_bavail=100*1024**2,f_frsize=1))
    check_storage_bound()


def test_audit_insert_failure_rolls_back_configuration_and_version(business):
    _,storage,tokens=business
    with storage.connect() as db:
        db.execute("CREATE TRIGGER fail_audit BEFORE INSERT ON setting_changes BEGIN SELECT RAISE(ABORT,'test audit unavailable'); END")
    cfg=PriorityConfig.load().to_dict();cfg["weights"]["urgency"]=81
    response=request("PUT","/api/settings/priority",tokens["a"],json={**cfg,"expected_version":1})
    assert response.status_code==503
    assert storage.setting_snapshot("priority")=={"priority":PriorityConfig.load().to_dict(),"version":1}
    assert storage.setting_history(100,0)==[]


def test_demo_refuses_accounts_even_with_forged_updated_manifest(demo,tmp_path,monkeypatch):
    import shutil
    copy=tmp_path/"with-account";shutil.copytree(demo,copy);copy.chmod(0o755)
    path=copy/"workspace.sqlite3";path.chmod(0o644)
    with sqlite3.connect(path) as db:db.execute("INSERT INTO access_users VALUES ('production-admin','salt','hash','admin',1)")
    manifest=copy/"manifest.json";manifest.chmod(0o644);data=json.loads(manifest.read_text());data["files"][path.name]=hashlib.sha256(path.read_bytes()).hexdigest();manifest.write_text(json.dumps(data))
    monkeypatch.setenv("LOGISTICS_DEMO_ROOT",str(copy))
    assert request("GET","/api/auth/session").status_code==503


def test_invalid_instance_mode_fails_closed_before_business_read(business,monkeypatch):
    _,_,tokens=business
    monkeypatch.setenv("LOGISTICS_INSTANCE_MODE","demmo")
    assert request("GET","/api/workspace",tokens["a"]).status_code==503
