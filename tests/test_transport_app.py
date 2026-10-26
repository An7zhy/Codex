"""Server-side UI interaction tests, including explicit draft/application boundaries."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def start():
    app = AppTest.from_file(APP).run(timeout=30)
    app.selectbox(key="workspace").set_value("V3 Transportation Optimization").run(timeout=30)
    assert not app.exception
    return app


def solve(app):
    next(button for button in app.button if button.label == "Run transportation optimization").click().run(timeout=60)
    assert not app.exception
    return app.session_state["v3_experiment"]


def test_workspace_navigation_and_v1_regression():
    app = start()
    assert any("Run transportation optimization" in item.value for item in app.info)
    run = solve(app)
    assert len(run.data.orders) == 12
    assert set(run.summary.status) == {"OPTIMAL"}
    assert {tab.label for tab in app.tabs} == {"Transportation Decision Center", "Optimization Dashboard", "Strategy Comparison", "What-if Scenario Analysis"}
    app.selectbox(key="workspace").set_value("V1/V2 Exception Copilot").run(timeout=30)
    assert not app.exception
    assert app.metric[0].value == "158"
    assert next(metric.value for metric in app.metric if metric.label == "On-Time Delivery Rate") == "47.8%"


def test_weights_applied_only_on_submit_and_selection_retained():
    app = start()
    original = solve(app)
    app.selectbox(key="v3_selected_order").set_value("PLAN-0005").run(timeout=30)
    app.number_input(key="v3_cost_weight").set_value(0)
    app.number_input(key="v3_time_weight").set_value(100)
    app.number_input(key="v3_risk_weight").set_value(0).run(timeout=30)
    assert app.session_state["v3_experiment"].preferences == original.preferences
    changed = solve(app)
    assert changed.preferences.normalized() == (0, 1, 0)
    assert changed.fingerprint == original.fingerprint
    assert changed.results["Optimized Allocation"].assignments.expected_hours.sum() <= original.results["Optimized Allocation"].assignments.expected_hours.sum()
    assert app.selectbox(key="v3_selected_order").value == "PLAN-0005"
    assert app.session_state["v3_previous_experiment"].preferences == original.preferences


def test_budget_shortage_penalty_mode_and_invalid_draft():
    app = start()
    app.number_input(key="v3_budget_percent").set_value(0)
    strict = solve(app)
    assert set(strict.summary.status) == {"INFEASIBLE"}
    assert any("no actionable allocation" in error.value for error in app.error)
    app.checkbox(key="v3_allow_unassigned").check()
    soft = solve(app)
    assert soft.summary.unassigned_orders.eq(12).all()
    assert soft.summary.simulated_on_time_rate_all_orders.eq(0).all()
    app.number_input(key="v3_cost_weight").set_value(0)
    app.number_input(key="v3_time_weight").set_value(0)
    app.number_input(key="v3_risk_weight").set_value(0)
    unchanged = solve(app)
    assert any("must be positive" in error.value for error in app.error)
    assert unchanged.preferences == soft.preferences


def test_capacity_deadline_and_empty_controls():
    app = start()
    app.number_input(key="v3_weight_capacity").set_value(0)
    assert solve(app).summary.status.eq("INFEASIBLE").all()
    app.number_input(key="v3_weight_capacity").set_value(100)
    app.number_input(key="v3_deadline_shift").set_value(-400)
    assert solve(app).summary.status.eq("INFEASIBLE").all()
    app.selectbox(key="v3_count").set_value(0)
    empty = solve(app)
    assert empty.summary.status.eq("OPTIMAL").all()
    assert any("Empty planning scenario" in info.value for info in app.info)


@pytest.mark.parametrize("status", ["FEASIBLE", "UNKNOWN"])
def test_ui_does_not_call_unproved_result_optimal(monkeypatch, status):
    monkeypatch.setattr("src.transport.engine.status_name", lambda raw: status)
    app = start()
    run = solve(app)
    assert run.results["Optimized Allocation"].status == status
    assert not any("OPTIMAL" in message.value for message in app.success)
    if status == "FEASIBLE":
        assert any("optimality was not proved" in warning.value for warning in app.warning)
    else:
        assert any("UNKNOWN" in message.value for message in app.error)
        assert run.summary.total_shipping_cost_usd.isna().all()
