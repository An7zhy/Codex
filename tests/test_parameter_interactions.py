"""User-reported parameter changes must apply visibly without resetting context."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest


def widget(app, kind, label):
    return next(item for item in getattr(app, kind) if item.label == label)


def priority_table(app):
    return next(item.value for item in app.dataframe if {"priority_score", "explanation", "shipment_id"}.issubset(item.value.columns))


def comparison(app):
    return next(item.value for item in app.dataframe if "estimated_additional_cost_usd" in item.value)


def test_apply_weights_changes_the_same_shipment_score_and_preserves_context():
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py")).run(timeout=30)
    before = priority_table(app).set_index("shipment_id").loc["SYN-0027", "priority_score"]
    assert before == pytest.approx(78.6667)
    # Select a different active shipment and edit a scenario before changing weights.
    widget(app, "selectbox", "Shipment for decision review").set_value("SYN-0159").run(timeout=30)
    next(item for item in app.number_input if item.label == "Additional cost (USD)").set_value(333.0)
    widget(app, "button", "Recalculate scenarios").click().run(timeout=30)
    widget(app, "number_input", "Financial weight").set_value(100.0)
    # Draft values alone must not masquerade as an applied calculation.
    app.run(timeout=30)
    assert priority_table(app).set_index("shipment_id").loc["SYN-0027", "priority_score"] == before
    # Streamlit 1.66 AppTest sends form values ONLY on submission. A forced
    # run rebuilds its tree from committed server values, unlike a browser's
    # pending form buffer. Re-stage the same client input; keep every assertion.
    widget(app, "number_input", "Financial weight").set_value(100.0)
    widget(app, "button", "Apply priority settings").click().run(timeout=30)
    assert not app.exception
    after = priority_table(app).set_index("shipment_id").loc["SYN-0027", "priority_score"]
    assert after == pytest.approx(88.1481)
    assert widget(app, "selectbox", "Shipment for decision review").value == "SYN-0159"
    assert comparison(app).iloc[0]["estimated_additional_cost_usd"] == 333


def test_calculate_commits_cost_and_time_and_parameters_survive_switching_shipments():
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py")).run(timeout=30)
    original = comparison(app).copy()
    assert original.iloc[0]["estimated_delay_hours"] == pytest.approx(72)
    next(item for item in app.number_input if item.label == "Additional cost (USD)").set_value(450.0)
    next(item for item in app.number_input if item.label == "Remaining time (hours)").set_value(48.0)
    app.run(timeout=30)
    assert comparison(app).iloc[0]["estimated_additional_cost_usd"] == 0
    # Re-stage the client draft after AppTest's explicit, unsubmitted rerun.
    next(item for item in app.number_input if item.label == "Additional cost (USD)").set_value(450.0)
    next(item for item in app.number_input if item.label == "Remaining time (hours)").set_value(48.0)
    widget(app, "button", "Recalculate scenarios").click().run(timeout=30)
    assert not app.exception
    assert comparison(app).iloc[0]["estimated_additional_cost_usd"] == 450
    assert comparison(app).iloc[0]["estimated_delay_hours"] == pytest.approx(24)
    widget(app, "selectbox", "Shipment for decision review").set_value("SYN-0159").run(timeout=30)
    widget(app, "selectbox", "Shipment for decision review").set_value("SYN-0027").run(timeout=30)
    assert comparison(app).iloc[0]["estimated_additional_cost_usd"] == 450
    assert next(item for item in app.number_input if item.label == "Additional cost (USD)").value == 450
    widget(app, "button", "Save decision to local history").click().run(timeout=30)
    assert not app.exception
    saved = next(item.value for item in app.dataframe if "estimated_cost" in item.value.columns and "case_id" in item.value.columns)
    assert saved.iloc[0]["estimated_cost"] == 450
    assert saved.iloc[0]["estimated_delay"] == pytest.approx(24)


def test_evaluation_results_refresh_after_applied_weights_without_disappearing():
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py")).run(timeout=30)
    widget(app, "button", "Run synthetic comparison").click().run(timeout=30)
    before = next(item.value for item in app.dataframe if "reference_disposition_matches" in item.value.columns)
    original = before.set_index("case_name").loc["urgent_low_value", "priority_score"]
    widget(app, "number_input", "Financial weight").set_value(100.0)
    widget(app, "button", "Apply priority settings").click().run(timeout=30)
    assert not app.exception
    after = next(item.value for item in app.dataframe if "reference_disposition_matches" in item.value.columns)
    assert after.set_index("case_name").loc["urgent_low_value", "priority_score"] != original
    assert app.session_state["applied_evaluation_result"].summary["config"]["weights"]["financial"] == 100
