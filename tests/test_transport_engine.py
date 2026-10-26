"""Numerical assertions and independent enumeration, not smoke-only solver tests."""

from dataclasses import replace
from itertools import product
import math

import pandas as pd
import pytest
from ortools.sat.python import cp_model

from src.transport.demo import adjust_planning, generate_planning_demo
from src.transport.engine import (STRATEGIES, audit_assignment, balanced_score, candidate_table,
                                  late_probability, objective_coefficient, single_order_recommendations,
                                  solve_allocation, status_name)
from src.transport.models import Candidate, Constraints, Order, PlanningData, Preferences, Service, units


@pytest.fixture
def small_plan():
    orders = tuple(Order(key, "CN", "EU", 4, 1, 10) for key in ("O1", "O2"))
    services = (Service("slow", "CN", "EU", "Sea", 8, 4, 8, 2, 2),
                Service("fast", "CN", "EU", "Air", 2, 0, 8, 2, 2))
    options = tuple(Candidate(order.shipment_id, service.service_id, 10 if service.service_id == "slow" else 30)
                    for order in orders for service in services)
    return PlanningData(orders, services, options)


def test_cost_time_risk_preferences_have_known_different_results(small_plan):
    limit = Constraints(100)
    cheapest = solve_allocation(small_plan, limit, strategy="Lowest Cost")
    fastest = solve_allocation(small_plan, limit, strategy="Fastest Delivery")
    risk = solve_allocation(small_plan, limit, Preferences(0, 0, 1))
    assert cheapest.status == fastest.status == risk.status == "OPTIMAL"
    assert cheapest.assignments.cost_usd.sum() == 20
    assert fastest.assignments.cost_usd.sum() == risk.assignments.cost_usd.sum() == 60
    assert set(cheapest.assignments.service_id) == {"slow"}
    assert set(fastest.assignments.service_id) == {"fast"}
    assert risk.assignments.assumed_late_probability.sum() == 0


@pytest.mark.parametrize("resource,value", [("weight_capacity_kg", 4), ("volume_capacity_m3", 1), ("shipment_capacity", 1)])
def test_shared_resources_enforced_and_other_service_used(small_plan, resource, value):
    slow = replace(small_plan.services[0], **{resource: value})
    plan = replace(small_plan, services=(slow, small_plan.services[1]))
    result = solve_allocation(plan, Constraints(100), strategy="Lowest Cost")
    assert result.status == "OPTIMAL"
    assert result.assignments.cost_usd.sum() == 40
    assert result.assignments.service_id.value_counts().to_dict() == {"slow": 1, "fast": 1}
    assert not audit_assignment(plan, Constraints(100), result.assignments)


def test_global_budget_infeasible_even_each_order_can_fit(small_plan):
    result = solve_allocation(small_plan, Constraints(19))
    assert result.candidates.eligible.sum() == 2
    assert result.status == "INFEASIBLE"
    assert result.assignments.empty and result.objective_value is None
    assert not result.has_solution


def test_capacity_insufficient_strict_vs_penalized(small_plan):
    plan = replace(small_plan, services=tuple(replace(service, weight_capacity_kg=0) for service in small_plan.services))
    strict = solve_allocation(plan, Constraints(100))
    soft = solve_allocation(plan, Constraints(100, allow_unassigned=True))
    assert strict.status == "INFEASIBLE"
    assert soft.status == "OPTIMAL" and soft.assignments.empty
    assert soft.unassigned_ids == ("O1", "O2")
    assert soft.objective_value == 2 * 100_000 * 100


def test_penalty_can_trade_off_fulfillment(small_plan):
    free_to_skip = solve_allocation(small_plan, Constraints(100, True, 0), strategy="Lowest Cost")
    costly_to_skip = solve_allocation(small_plan, Constraints(10, True, 100), strategy="Lowest Cost")
    assert len(free_to_skip.unassigned_ids) == 2
    assert len(costly_to_skip.assignments) == 1
    assert len(costly_to_skip.unassigned_ids) == 1
    assert costly_to_skip.assignments.cost_usd.sum() == 10
    assert costly_to_skip.objective_value == 11_000


@pytest.mark.parametrize("change,reason", [
    ({"origin": "OTHER"}, "Route mismatch"),
    ({"mean_hours": 11}, "Expected arrival exceeds hard deadline"),
    ({"weight_capacity_kg": 3}, "Weight exceeds service capacity"),
    ({"volume_capacity_m3": .5}, "Volume exceeds service capacity"),
    ({"shipment_capacity": 0}, "No shipment slots"),
])
def test_ineligible_candidate_never_scores_or_wins(small_plan, change, reason):
    plan = replace(small_plan, services=(replace(small_plan.services[0], **change), small_plan.services[1]))
    table = candidate_table(plan, Constraints(100), Preferences(100, 0, 0))
    rejected = table.loc[table.service_id.eq("slow")]
    assert not rejected.eligible.any()
    assert rejected.balanced_score.isna().all()
    assert rejected.rejection_reasons.str.contains(reason).all()
    result = solve_allocation(plan, Constraints(100), Preferences(100, 0, 0))
    assert set(result.assignments.service_id) == {"fast"}


def test_single_order_checks_and_recommendations(small_plan):
    table = candidate_table(small_plan, Constraints(100), Preferences(0, 1, 0))
    recommendations = single_order_recommendations(table)
    assert len(recommendations) == 6
    assert set(recommendations.loc[recommendations.strategy.eq("Lowest Cost"), "service_id"]) == {"slow"}
    assert set(recommendations.loc[recommendations.strategy.eq("Optimized Allocation"), "service_id"]) == {"fast"}
    rejected = single_order_recommendations(candidate_table(small_plan, Constraints(0)))
    assert rejected.service_id.isna().all()
    assert set(rejected.explanation) == {"No hard-eligible candidate"}


def test_weights_normalized_proportionally_and_zero_rejected():
    assert Preferences(3, 3, 4).normalized() == Preferences(30, 30, 40).normalized()
    assert balanced_score(1000, 336, .5, Preferences(3, 3, 4)) == pytest.approx(.8)
    with pytest.raises(ValueError, match="positive"):
        Preferences(0, 0, 0)


def test_deadline_boundary_is_eligible_but_uncertain(small_plan):
    plan = replace(small_plan, orders=tuple(replace(order, deadline_hours=8) for order in small_plan.orders))
    rows = candidate_table(plan, Constraints(100))
    slow = rows.loc[rows.service_id.eq("slow")]
    assert slow.eligible.all()
    assert (slow.assumed_late_probability > .3).all()
    assert late_probability(8, 0, 8) == 0
    assert late_probability(8, 0, 7.99) == 1
    assert late_probability(8, 4, 0) == 1


def test_conservative_quantization_does_not_overbook_or_overspend():
    assert units(.0011, 1000) == 2
    assert units(.0019, 1000, capacity=True) == 1
    order = Order("O", "A", "B", .0011, .001, 1)
    service = Service("S", "A", "B", "Air", 1, 0, .0019, .001, 1)
    plan = PlanningData((order,), (service,), (Candidate("O", "S", .009),))
    assert solve_allocation(plan, Constraints(1)).status == "INFEASIBLE"
    plan = replace(plan, services=(replace(service, weight_capacity_kg=.002),))
    assert solve_allocation(plan, Constraints(.0091)).status == "INFEASIBLE"
    assert solve_allocation(plan, Constraints(.01)).status == "OPTIMAL"


def test_empty_and_missing_candidates():
    empty = PlanningData((), (), ())
    result = solve_allocation(empty, Constraints(0))
    assert result.status == "OPTIMAL" and result.assignments.empty
    assert result.objective_value == 0
    plan = replace(empty, orders=(Order("O", "A", "B", 1, 1, 10),))
    assert solve_allocation(plan, Constraints(100)).status == "INFEASIBLE"


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_solver_matches_independent_exhaustive_enumeration(small_plan, strategy):
    plan = replace(small_plan, services=(replace(small_plan.services[0], shipment_capacity=1), small_plan.services[1]))
    limit, prefs = Constraints(50), Preferences()
    result = solve_allocation(plan, limit, prefs, strategy)
    # Enumerate all 2^2 service choices, with independent resource/budget arithmetic.
    values = []
    table = candidate_table(plan, limit, prefs)
    for choices in product(("slow", "fast"), repeat=2):
        if choices.count("slow") > 1:
            continue
        cost = sum(10 if service == "slow" else 30 for service in choices)
        if cost > 50:
            continue
        objective = 0
        for order, service in zip(plan.orders, choices):
            row = table.loc[table.shipment_id.eq(order.shipment_id) & table.service_id.eq(service)].iloc[0]
            objective += objective_coefficient(row, strategy, prefs)
        values.append(objective)
    assert result.status == "OPTIMAL"
    assert result.objective_value == min(values)
    assert result.best_bound == result.objective_value


@pytest.mark.parametrize("status,expected", [(cp_model.OPTIMAL, "OPTIMAL"), (cp_model.FEASIBLE, "FEASIBLE"),
    (cp_model.INFEASIBLE, "INFEASIBLE"), (cp_model.UNKNOWN, "UNKNOWN"), (cp_model.MODEL_INVALID, "MODEL_INVALID")])
def test_all_solver_status_mappings(status, expected):
    assert status_name(status) == expected


@pytest.mark.parametrize("forced", ["FEASIBLE", "UNKNOWN", "MODEL_INVALID"])
def test_nonoptimal_states_never_misrepresented(small_plan, monkeypatch, forced):
    # Controlled status injection exercises branches; not a claim the solver timed out.
    monkeypatch.setattr("src.transport.engine.status_name", lambda status: forced)
    result = solve_allocation(small_plan, Constraints(100))
    assert result.status == forced
    if forced == "FEASIBLE":
        assert result.has_solution and len(result.assignments) == 2
    else:
        assert not result.has_solution and result.assignments.empty
        assert result.objective_value is result.best_bound is None


def test_real_tiny_time_limit_returns_unknown():
    result = solve_allocation(generate_planning_demo(100), Constraints(1e9, time_limit_seconds=1e-9))
    assert result.status == "UNKNOWN"
    assert not result.has_solution


@pytest.mark.parametrize("invalid", [-1, float("nan"), float("inf"), True, "100"])
def test_invalid_costs_blocked(invalid):
    with pytest.raises(ValueError):
        Candidate("O", "S", invalid)


@pytest.mark.parametrize("kwargs", [{"weight_kg": 0}, {"volume_m3": -1}, {"deadline_hours": None}, {"shipment_id": ""}])
def test_missing_or_invalid_order_inputs(kwargs):
    with pytest.raises(ValueError):
        Order(**{**dict(shipment_id="O", origin="A", destination="B", weight_kg=1, volume_m3=1, deadline_hours=10), **kwargs})


def test_duplicate_unknown_references_and_invalid_configuration(small_plan):
    with pytest.raises(ValueError, match="unique"):
        replace(small_plan, orders=(small_plan.orders[0], small_plan.orders[0]))
    with pytest.raises(ValueError, match="Duplicate"):
        replace(small_plan, candidates=(small_plan.candidates[0], small_plan.candidates[0]))
    with pytest.raises(ValueError, match="unknown"):
        replace(small_plan, candidates=(Candidate("MISSING", "slow", 1),))
    for configuration in ({"budget_usd": -1}, {"budget_usd": 1, "allow_unassigned": 1},
                           {"budget_usd": 1, "time_limit_seconds": 0}):
        with pytest.raises(ValueError):
            Constraints(**configuration)
    with pytest.raises(ValueError):
        Service("S", "A", "B", "Air", 1, 0, 1, 1, 1.5)


def test_audit_detects_invalid_assignment(small_plan):
    result = solve_allocation(small_plan, Constraints(100), strategy="Lowest Cost")
    overfilled = pd.concat([result.assignments] * 2, ignore_index=True)
    errors = audit_assignment(small_plan, Constraints(15), overfilled)
    assert "More than one assignment for an order" in errors
    assert "Total budget exceeded" in errors
    assert any("shared weight capacity" in error for error in errors)


def test_demo_adjustments_do_not_mutate_original():
    data = generate_planning_demo(100)
    changed = adjust_planning(data, deadline_shift_hours=-500, weight_capacity_factor=0)
    assert all(order.deadline_hours == 0 for order in changed.orders)
    assert all(service.weight_capacity_kg == 0 for service in changed.services)
    assert data.orders[0].deadline_hours == 48
    assert all(service.weight_capacity_kg > 0 for service in data.services)
