from dataclasses import replace
import json

import pandas as pd
import pytest

from src.decisions import ACTIONS, ActionAssumption, compare_actions, default_assumptions
from src.history import CaseInput, HistoryStore


def test_action_tradeoffs_and_modified_assumptions():
    cutoff = pd.Timestamp("2026-10-01T00:00:00Z")
    deadline = pd.Timestamp("2026-10-03T00:00:00Z")
    defaults = default_assumptions()
    comparison = compare_actions(cutoff, deadline, defaults)
    assert comparison["estimated_additional_cost_usd"].tolist() == [0, 250, 800]
    assert comparison["estimated_delay_hours"].tolist() == [48, 0, 0]
    changed = list(defaults)
    changed[1] = replace(changed[1], additional_cost=500, remaining_hours=72)
    new = compare_actions(cutoff, deadline, changed)
    assert new.iloc[1]["estimated_delay_hours"] == 24
    assert new.iloc[1]["estimated_additional_cost_usd"] == 500
    assert defaults[1].remaining_hours == 48
    assert "unverified" in new.iloc[1]["key_assumptions"]


def test_unknown_deadline_and_unavailable_action_have_no_invented_outcomes():
    options = default_assumptions()
    options[1] = replace(options[1], assumed_available=False)
    table = compare_actions(pd.Timestamp("2026-10-01"), None, options)
    assert table["estimated_delay_hours"].isna().all()
    assert pd.isna(table.iloc[1]["scenario_arrival_utc"])
    assert table.iloc[1]["deadline_impact"] == "Unavailable in this scenario"
    assert "Insufficient information" in table.iloc[0]["deadline_impact"]


@pytest.mark.parametrize("kwargs", [{"additional_cost": -1}, {"remaining_hours": float("nan")},
    {"remaining_hours": -1}, {"remaining_hours": 87601}, {"additional_cost": float("inf")},
    {"additional_cost": True}, {"assumed_available": "yes"}, {"notes": " "}])
def test_invalid_scenarios_are_rejected(kwargs):
    with pytest.raises(ValueError):
        replace(default_assumptions()[0], **kwargs)


def test_missing_or_duplicate_action_names_are_rejected():
    with pytest.raises(ValueError):
        compare_actions(pd.Timestamp("2026-10-01"), None, default_assumptions()[:2])
    with pytest.raises(ValueError):
        compare_actions(pd.Timestamp("2026-10-01"), None, [default_assumptions()[0]] * 3)


def case(shipment_id="TEST-1", **kwargs):
    return CaseInput(shipment_id, "Overdue in transit", ACTIONS[1], estimated_cost=250,
                     estimated_delay=24, origin="Shanghai, China", destination="Rotterdam, Netherlands",
                     transport_mode="Sea", assumptions_json=json.dumps({"source": "Synthetic test"}), **kwargs)


def test_sqlite_persistence_updates_and_unknown_outcomes(tmp_path):
    path = tmp_path / "local" / "cases.sqlite3"
    first = HistoryStore(path)
    case_id = first.create_case(case())
    # Reopen the database, rather than relying on an in-memory connection.
    reopened = HistoryStore(path)
    original = reopened.get_case(case_id)
    assert original["actual_cost"] is None
    assert original["actual_delay"] is None
    assert original["estimated_cost"] == 250
    reopened.update_case(case_id, "Resolved", 275, 30, "Synthetic outcome entered by test", expected_version=1)
    updated = HistoryStore(path).get_case(case_id)
    assert updated["actual_cost"] == 275
    assert updated["actual_delay"] == 30
    assert updated["resolution_status"] == "Resolved"
    assert updated["version"] == 2
    assert len(reopened.list_cases(resolution_status="Open")) == 0
    assert len(reopened.list_cases(shipment_id="TEST-1", resolution_status="Resolved")) == 1
    with pytest.raises(ValueError, match="another session"):
        first.update_case(case_id, "Cancelled", None, None, "stale", expected_version=1)


def test_similar_cases_require_exact_direction_mode_and_exception(tmp_path):
    store = HistoryStore(tmp_path / "cases.sqlite3")
    store.create_case(case("OLD"))
    store.create_case(case("CURRENT"))
    similar = store.similar_cases(" shanghai, china ", "Rotterdam, Netherlands", "sea", "Overdue in transit", "CURRENT")
    assert similar["shipment_id"].tolist() == ["OLD"]
    assert store.similar_cases("Rotterdam, Netherlands", "Shanghai, China", "sea", "Overdue in transit").empty
    assert store.similar_cases("Unknown", "Rotterdam, Netherlands", "sea", "Overdue in transit").empty
    assert store.similar_cases("Shanghai, China", "Rotterdam, Netherlands", "air", "Overdue in transit").empty
    assert store.similar_cases("Shanghai, China", "Rotterdam, Netherlands", "sea", "High cost").empty


def test_history_inputs_and_queries_are_parameterized(tmp_path):
    store = HistoryStore(tmp_path / "cases.sqlite3")
    injected = "x'; DROP TABLE cases; --"
    store.create_case(case(injected, resolution_notes="=HYPERLINK(1)"))
    assert len(store.list_cases(shipment_id=injected)) == 1
    assert len(store.list_cases(shipment_id="' OR 1=1 --")) == 0
    assert len(store.list_cases()) == 1
    with pytest.raises(LookupError):
        store.get_case("missing")
    with pytest.raises(ValueError):
        store.list_cases(limit=-1)


@pytest.mark.parametrize("kwargs", [{"actual_cost": -1}, {"actual_delay": float("inf")},
    {"resolution_status": "Invented"}, {"resolution_notes": "x" * 4001}])
def test_invalid_history_records_are_not_saved(tmp_path, kwargs):
    store = HistoryStore(tmp_path / "cases.sqlite3")
    with pytest.raises(ValueError):
        store.create_case(case(**kwargs))
    assert store.list_cases().empty
