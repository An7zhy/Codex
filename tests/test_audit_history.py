from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
import sqlite3

import pytest
from streamlit.testing.v1 import AppTest

from src.decisions import ACTIONS
from src.history import CaseInput, HistoryStore


def example():
    return CaseInput("AUDIT-CASE", "Overdue in transit", ACTIONS[0], estimated_cost=25,
                     origin="Shanghai, China", destination="Rotterdam, Netherlands", transport_mode="Sea")


def test_request_retries_do_not_duplicate_or_overwrite_resolved_outcomes(tmp_path):
    store = HistoryStore(tmp_path / "history.sqlite3")
    record = example()
    first = store.create_case(record, idempotency_key="request-1")
    assert store.create_case(record, idempotency_key="request-1") == first
    store.update_case(first, "Resolved", 30, 12, "Synthetic outcome", expected_version=1)
    assert store.create_case(record, idempotency_key="request-1") == first
    assert store.get_case(first)["actual_cost"] == 30
    assert store.get_case(first)["resolution_status"] == "Resolved"
    with pytest.raises(ValueError, match="different decision"):
        store.create_case(replace(record, estimated_cost=26), idempotency_key="request-1")
    assert len(store.list_cases()) == 1
    second = store.create_case(record, idempotency_key="intentional-second-decision")
    assert second != first
    assert len(store.list_cases()) == 2


def test_concurrent_identical_request_inserts_once(tmp_path):
    store = HistoryStore(tmp_path / "concurrent.sqlite3")
    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(lambda _: store.create_case(example(), idempotency_key="same-request"), range(4)))
    assert len(set(ids)) == 1
    assert len(store.list_cases()) == 1
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_additive_migration_preserves_existing_v2_case(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    old = {**asdict(example()), "case_id": "legacy-case", "created_at": "2026-01-01T00:00:00Z",
           "updated_at": "2026-01-01T00:00:00Z", "version": 7,
           "origin_key": "shanghai, china", "destination_key": "rotterdam, netherlands", "mode_key": "sea"}
    old.update(actual_cost=20, actual_delay=12, resolution_status="Resolved", resolution_notes="Preserve this legacy outcome")
    money = {"estimated_cost", "actual_cost", "estimated_delay", "actual_delay"}
    definitions = [key + (" TEXT PRIMARY KEY" if key == "case_id" else " REAL" if key in money else " INTEGER" if key == "version" else " TEXT") for key in old]
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE cases (" + ",".join(definitions) + ")")
        connection.execute("INSERT INTO cases (" + ",".join(old) + ") VALUES (" + ",".join("?" for _ in old) + ")", list(old.values()))
    migrated = HistoryStore(path)
    row = migrated.get_case("legacy-case")
    for key, value in old.items():
        assert row[key] == value
    assert row["request_key"] is None
    assert row["request_payload_hash"] is None
    assert HistoryStore(path).get_case("legacy-case")["version"] == 7
    migrated.create_case(replace(example(), shipment_id="AFTER-MIGRATION"), idempotency_key="new-request")
    assert len(migrated.list_cases()) == 2


@pytest.mark.parametrize("field,value", [("shipment_id", None), ("shipment_id", 123),
    ("resolution_notes", None), ("origin", None), ("assumptions_json", "[]"),
    ("assumptions_json", '{"value": NaN}'), ("priority_snapshot_json", '{"value": Infinity}')])
def test_invalid_history_types_and_nonfinite_json_are_rejected(tmp_path, field, value):
    store = HistoryStore(tmp_path / "invalid.sqlite3")
    with pytest.raises(ValueError):
        store.create_case(replace(example(), **{field: value}))
    assert store.list_cases().empty


def test_legacy_bad_metadata_does_not_block_outcome_updates(tmp_path, monkeypatch):
    path = tmp_path / "legacy-metadata.sqlite3"
    store = HistoryStore(path)
    case_id = store.create_case(example())
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE cases SET assumptions_json = ? WHERE case_id = ?", ("old malformed metadata", case_id))
    monkeypatch.setenv("LOGISTICS_DB_PATH", str(path))
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py")).run(timeout=30)
    assert not app.exception
    assert any("original record is preserved" in warning.value for warning in app.warning)
    next(widget for widget in app.selectbox if widget.label == "Update resolution status").set_value("Resolved")
    next(widget for widget in app.number_input if widget.label == "Actual additional cost (USD, optional)").set_value(30.0)
    next(widget for widget in app.button if widget.label == "Update saved case").click().run(timeout=30)
    assert not app.exception
    assert store.get_case(case_id)["resolution_status"] == "Resolved"
    assert store.get_case(case_id)["actual_cost"] == 30
    assert store.get_case(case_id)["assumptions_json"] == "old malformed metadata"
