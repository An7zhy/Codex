from dataclasses import replace
import json

import pandas as pd
import pytest

from src.analysis import analyze_shipments
from src.priority import COMPONENTS, PriorityConfig, prioritize_shipments


@pytest.fixture
def active(make_rows):
    def make(**overrides):
        fields = dict(status="In Transit", actual_delivery="", delivery_deadline="2026-10-02T00:00:00Z",
                      estimated_delay_hours=36, estimated_financial_impact=5000,
                      financial_impact_basis="Fictional explicit contract exposure", shipment_value=50000,
                      downstream_dependency_count=2, downstream_risk_basis="Two declared fictional dependent activities")
        fields.update(overrides)
        return analyze_shipments(make_rows(fields), "2026-10-01")
    return make


def triage(result, config=None):
    return prioritize_shipments(result.shipments, result.cutoff, config).iloc[0]


def test_hand_calculated_score_and_explanation(active):
    row = triage(active())
    # 30 urgency + 12.5 delay + 10 financial + 5 value + 6 downstream.
    assert row["priority_score"] == pytest.approx(63.5)
    assert row["priority_level"] == "Medium"
    assert row["coverage_percent"] == 100
    assert "not a loss estimate" in row["explanation"]
    assert "not inferred from overdue age" in row["explanation"]


def test_level_threshold_uses_the_reported_score_precision(active):
    row = triage(active(), replace(PriorityConfig(), high_threshold=63.5))
    assert row["priority_score"] == 63.5
    assert row["priority_level"] == "High"


def test_high_value_cannot_fill_missing_financial_information(active):
    row = triage(active(shipment_value=1_000_000, estimated_financial_impact=None))
    assert pd.isna(row["priority_score"])
    assert row["priority_level"] == "Insufficient information"
    assert "financial" in row["missing_information"]
    assert row["coverage_percent"] == 80
    assert json.loads(row["priority_details_json"])["components"]["financial"] is None
    assert row["priority_upper_bound"] - row["priority_lower_bound"] == pytest.approx(20)


@pytest.mark.parametrize("field,value", [("estimated_delay_hours", -1), ("estimated_delay_hours", float("inf")),
    ("estimated_delay_hours", "bad"), ("financial_impact_basis", ""), ("shipment_value", None),
    ("shipment_value", -10), ("downstream_dependency_count", 1.5), ("downstream_risk_basis", ""),
    ("delivery_deadline", "not-a-date")])
def test_invalid_optional_context_is_not_zero_imputed(active, field, value):
    row = triage(active(**{field: value}))
    assert pd.isna(row["priority_score"])
    assert row["missing_information"]
    assert row["priority_level"] == "Insufficient information"


def test_zero_weight_explicitly_disables_a_component(active):
    config = replace(PriorityConfig(), weights=dict(urgency=30, delay=25, financial=0, value=10, downstream=15))
    row = triage(active(estimated_financial_impact=None, financial_impact_basis=""), config)
    assert not pd.isna(row["priority_score"])
    assert row["coverage_percent"] == 100
    assert "financial:" not in row["missing_information"]


@pytest.mark.parametrize("kwargs", [
    {"weights": dict.fromkeys(COMPONENTS, 0)}, {"weights": {"value": 100}},
    {"weights": dict(urgency=-1, delay=25, financial=20, value=10, downstream=15)},
    {"weights": dict(urgency=float("nan"), delay=25, financial=20, value=10, downstream=15)},
    {"weights": dict(urgency="30", delay=25, financial=20, value=10, downstream=15)},
    {"delay_scale_hours": 0}, {"financial_scale_usd": float("inf")},
    {"high_threshold": 20, "medium_threshold": 40}, {"urgency_window_hours": True},
])
def test_configuration_errors_are_actionable(kwargs):
    with pytest.raises(ValueError):
        PriorityConfig(**kwargs)


def test_completed_normal_and_unidentified_rows_have_no_active_priority(active):
    assert triage(active(status="Delivered", actual_delivery="2026-09-30T20:00:00Z"))["priority_level"] == "Review only"
    assert triage(active(planned_delivery="2026-10-10"))["priority_level"] == "Not an exception"
    assert triage(active(shipment_id=""))["priority_level"] == "Excluded"


def test_deadline_fallback_is_explicit_and_input_is_unchanged(active):
    result = active(delivery_deadline="")
    original = result.shipments.copy(deep=True)
    row = triage(result)
    assert "planned_delivery (fallback)" in row["explanation"]
    pd.testing.assert_frame_equal(result.shipments, original)


def test_empty_selection_and_reference_labels_cannot_change_scores(active):
    result = active()
    assert prioritize_shipments(result.shipments.iloc[:0], result.cutoff).empty
    original = triage(result)["priority_score"]
    result.shipments["reference_rank"] = -99999
    result.shipments["reference_disposition"] = "Anything"
    assert triage(result)["priority_score"] == original
