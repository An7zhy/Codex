from pathlib import Path
from dataclasses import replace

from streamlit.testing.v1 import AppTest

from src.history import HistoryStore
from src.history import CaseInput
from src.decisions import ACTIONS
from src.priority import PriorityConfig

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def element(elements, label):
    return next(widget for widget in elements if widget.label == label)


def test_scenario_edit_save_and_actual_outcome_update(tmp_path, monkeypatch):
    database = tmp_path / "cases.sqlite3"
    monkeypatch.setenv("LOGISTICS_DB_PATH", str(database))
    app = AppTest.from_file(APP).run(timeout=30)
    assert not app.exception
    assert len(app.metric) == 7
    first_cost = next(widget for widget in app.number_input if widget.label == "Additional cost (USD)")
    first_cost.set_value(111.0).run(timeout=30)
    table = next(widget.value for widget in app.dataframe if "estimated_additional_cost_usd" in widget.value)
    assert table.iloc[0]["estimated_additional_cost_usd"] == 111
    element(app.button, "Save decision to local history").click().run(timeout=30)
    assert not app.exception
    store = HistoryStore(database)
    records = store.list_cases()
    assert len(records) == 1
    case_id = records.iloc[0]["case_id"]
    saved = store.get_case(case_id)
    assert saved["estimated_cost"] == 111
    assert saved["actual_cost"] is None
    assert saved["actual_delay"] is None
    assert "comparison" in saved["assumptions_json"]
    element(app.selectbox, "Update resolution status").set_value("Resolved")
    element(app.number_input, "Actual additional cost (USD, optional)").set_value(125.0)
    element(app.number_input, "Actual delay (hours, optional)").set_value(10.0)
    element(app.text_area, "Resolution notes").set_value("Fictional outcome for test only")
    element(app.button, "Update saved case").click().run(timeout=30)
    assert not app.exception
    updated = HistoryStore(database).get_case(case_id)
    assert updated["resolution_status"] == "Resolved"
    assert updated["actual_cost"] == 125
    assert updated["actual_delay"] == 10
    assert len(store.list_cases()) == 1  # widget reruns never create extra decisions


def test_bad_priority_settings_and_unavailable_database_preserve_v1(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGISTICS_DB_PATH", str(tmp_path))  # a directory cannot be a database file
    app = AppTest.from_file(APP).run(timeout=30)
    assert not app.exception
    assert any("history" in item.value.lower() for item in app.warning)
    for widget in app.number_input:
        if widget.key and widget.key.startswith("weight_"):
            widget.set_value(0.0)
    app.run(timeout=30)
    assert not app.exception
    assert any("Weights" in item.value for item in app.error)
    assert app.metric[0].value == "158"


def test_evaluation_tab_runs_without_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGISTICS_DB_PATH", str(tmp_path / "cases.sqlite3"))
    app = AppTest.from_file(APP).run(timeout=30)
    element(app.button, "Run synthetic comparison").click().run(timeout=30)
    assert not app.exception
    comparison = next(widget.value for widget in app.dataframe if "reference_disposition_matches" in widget.value)
    assert len(comparison) == 9
    assert comparison["reference_disposition_matches"].all()


def test_similar_case_is_visible_in_decision_center(tmp_path, monkeypatch):
    database = tmp_path / "cases.sqlite3"
    monkeypatch.setenv("LOGISTICS_DB_PATH", str(database))
    HistoryStore(database).create_case(CaseInput(
        "PAST-SYNTHETIC-ANALOG", "Overdue in transit", ACTIONS[0],
        origin="Shanghai, China", destination="Rotterdam, Netherlands", transport_mode="Air",
        resolution_status="Resolved", actual_cost=0, actual_delay=24,
        resolution_notes="Fictional historical example for UI testing only",
    ))
    app = AppTest.from_file(APP).run(timeout=30)
    assert not app.exception
    similar = next(widget.value for widget in app.dataframe if "match_reason" in widget.value)
    assert "PAST-SYNTHETIC-ANALOG" in similar["shipment_id"].tolist()


def test_valid_custom_config_is_supported_by_ui_controls(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGISTICS_DB_PATH", str(tmp_path / "cases.sqlite3"))
    config = replace(PriorityConfig(), weights=dict(urgency=200, delay=25, financial=20, value=10, downstream=15),
                     urgency_window_hours=0.5, medium_threshold=0.5, high_threshold=1.5)
    monkeypatch.setattr(PriorityConfig, "load", classmethod(lambda cls: config))
    app = AppTest.from_file(APP).run(timeout=30)
    assert not app.exception
    assert not app.error
    assert app.metric[0].value == "158"
