"""Common scenarios, denominator fairness, reproducible exports and workload checks."""

from dataclasses import replace
import json

import numpy as np
import pytest

from src.transport.demo import demo_budget, generate_planning_demo
from src.transport.engine import STRATEGIES, late_probability, solve_allocation
from src.transport.experiments import compare_strategies, experiment_json, replay_experiment
from src.transport.models import Candidate, Constraints, Order, PlanningData, Preferences, Service
from src.transport.simulation import generate_scenarios, simulate_allocation


def test_lognormal_moments_and_late_probability():
    plan = PlanningData((Order("O", "A", "B", 1, 1, 10),),
                        (Service("S", "A", "B", "Sea", 8, 4, 10, 10, 10),),
                        (Candidate("O", "S", 10),))
    bank = generate_scenarios(plan, 100_000)
    draws = bank.samples["S"]
    assert (draws > 0).all()
    assert draws.mean() == pytest.approx(8, rel=.015)
    assert draws.std() == pytest.approx(4, rel=.02)
    result = solve_allocation(plan, Constraints(100))
    summary, details = simulate_allocation(plan, result, bank)
    analytic = late_probability(8, 4, 10)
    assert summary["simulated_late_probability_assigned"] == pytest.approx(analytic, abs=.01)
    assert details.iloc[0].estimated_late_probability == pytest.approx(analytic, abs=.01)
    assert details.iloc[0].expected_hours == 8
    assert details.iloc[0].simulated_transit_hours_scenario_0 == draws[0]


def test_seed_reproducible_order_independent_and_different_seed_changes():
    data = generate_planning_demo()
    a = generate_scenarios(data, 1000, 42)
    b = generate_scenarios(replace(data, services=tuple(reversed(data.services))), 1000, 42)
    c = generate_scenarios(data, 1000, 43)
    assert a.fingerprint == b.fingerprint != c.fingerprint
    for key in a.samples:
        np.testing.assert_array_equal(a.samples[key], b.samples[key])
        assert not np.array_equal(a.samples[key], c.samples[key])
        assert not a.samples[key].flags.writeable


def test_common_service_shock_and_deterministic_times():
    data = PlanningData(tuple(Order(key, "A", "B", 1, 1, 10) for key in ("O1", "O2")),
                        (Service("S", "A", "B", "Air", 8, 4, 10, 10, 10),),
                        tuple(Candidate(key, "S", 10) for key in ("O1", "O2")))
    result = solve_allocation(data, Constraints(100))
    summary, details = simulate_allocation(data, result, generate_scenarios(data, 1000))
    assert details.estimated_late_probability.nunique() == 1
    assert details.simulated_transit_hours_scenario_0.nunique() == 1
    deterministic = replace(data, services=(replace(data.services[0], std_hours=0),))
    fixed = generate_scenarios(deterministic, 10)
    assert np.all(fixed.samples["S"] == 8)
    assert summary["on_time_rate_monte_carlo_se"] > 0


def test_three_constrained_strategies_share_scenarios_and_denominators():
    data = generate_planning_demo()
    run = compare_strategies(data, Constraints(demo_budget(data)))
    table = run.summary.set_index("strategy")
    assert set(table.status) == {"OPTIMAL"}
    assert table.same_full_fulfillment_comparison.all()
    assert table.scenario_fingerprint.nunique() == 1
    assert table.assigned_orders.eq(12).all()
    assert table.unassigned_orders.eq(0).all()
    assert table.expected_on_time_rate_all_orders.eq(1).all()
    assert table.loc["Lowest Cost", "total_shipping_cost_usd"] <= table.loc["Optimized Allocation", "total_shipping_cost_usd"]
    for strategy in STRATEGIES:
        row, result = table.loc[strategy], run.results[strategy]
        assert row.total_shipping_cost_usd == result.assignments.cost_usd.sum()
        assert row.weight_utilization == pytest.approx(result.assignments.weight_kg.sum() / sum(item.weight_capacity_kg for item in data.services))
        assert 0 <= row.simulated_on_time_rate_all_orders <= 1
        assert row.simulated_on_time_rate_all_orders == row.simulated_on_time_rate_assigned


def test_unassigned_never_removed_from_all_order_denominator():
    data = PlanningData(tuple(Order(key, "A", "B", 1, 1, 10) for key in ("O1", "O2")),
                        (Service("S", "A", "B", "Air", 5, 0, 1, 1, 1),),
                        tuple(Candidate(key, "S", 10) for key in ("O1", "O2")))
    run = compare_strategies(data, Constraints(100, True), scenario_count=10)
    assert run.summary.unassigned_orders.eq(1).all()
    assert run.summary.simulated_on_time_rate_all_orders.eq(.5).all()
    assert run.summary.simulated_on_time_rate_assigned.eq(1).all()
    assert not run.summary.same_full_fulfillment_comparison.any()


def test_infeasible_not_reported_as_zero_cost_benefit():
    data = generate_planning_demo()
    run = compare_strategies(data, Constraints(0), scenario_count=10)
    assert run.summary.status.eq("INFEASIBLE").all()
    assert run.summary.total_shipping_cost_usd.isna().all()
    assert run.summary.simulated_on_time_rate_all_orders.isna().all()
    assert run.summary.unassigned_orders.isna().all()
    assert run.summary.unresolved_orders.eq(12).all()
    assert not run.summary.same_full_fulfillment_comparison.any()


def test_empty_rates_not_zero_or_hundred_percent():
    run = compare_strategies(generate_planning_demo(0), Constraints(0), scenario_count=10)
    assert run.summary.status.eq("OPTIMAL").all()
    assert run.summary.assigned_orders.eq(0).all()
    assert run.summary.simulated_on_time_rate_all_orders.isna().all()
    assert run.summary.total_shipping_cost_usd.eq(0).all()


def test_json_replay_uses_full_inputs_not_claimed_saved_results():
    data = generate_planning_demo()
    run = compare_strategies(data, Constraints(demo_budget(data)), scenario_count=100)
    payload = experiment_json(run)
    assert "NaN" not in payload and "Infinity" not in payload
    saved = json.loads(payload)
    saved["summary"] = [{"total_shipping_cost_usd": -123}]  # outputs are not trusted on replay
    again = replay_experiment(json.dumps(saved))
    assert again.fingerprint == run.fingerprint
    np.testing.assert_allclose(again.summary.total_shipping_cost_usd, run.summary.total_shipping_cost_usd)
    assert again.data == run.data


@pytest.mark.parametrize("payload", ["", "{}", "[]", '{"schema":"unsupported"}'])
def test_invalid_replay_reports_input_error(payload):
    with pytest.raises(ValueError):
        replay_experiment(payload)


@pytest.mark.parametrize("count", [0, -1, 1.5, True])
def test_invalid_scenario_counts(count):
    with pytest.raises(ValueError):
        generate_scenarios(generate_planning_demo(), count)


@pytest.mark.parametrize("count", [100, 500])
def test_required_workloads_remain_feasible_and_respect_capacities(count):
    data = generate_planning_demo(count)
    run = compare_strategies(data, Constraints(demo_budget(data), time_limit_seconds=3), scenario_count=100)
    assert run.summary.has_feasible_solution.all()
    assert run.summary.assigned_orders.eq(count).all()
    assert run.summary.unassigned_orders.eq(0).all()
    for result in run.results.values():
        for resource in ("weight_utilization", "volume_utilization", "slot_utilization"):
            assert (result.capacity[resource].dropna() <= 1 + 1e-9).all()
