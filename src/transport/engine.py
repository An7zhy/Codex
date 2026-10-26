"""Hard eligibility first; deterministic CP-SAT shared-capacity assignment second."""

from dataclasses import dataclass
import math
import time

import pandas as pd
from ortools.sat.python import cp_model

from .models import Constraints, PlanningData, Preferences, units

STRATEGIES = ("Lowest Cost", "Fastest Delivery", "Optimized Allocation")
COST_SCALE_USD = 1000.0
TIME_SCALE_HOURS = 336.0
TIME_VALUE_USD_PER_HOUR = 10.0
ASSIGNMENT_COLUMNS = ["shipment_id", "service_id", "cost_usd", "expected_hours", "std_hours",
                      "deadline_hours", "assumed_late_probability", "weight_kg", "volume_m3"]
CANDIDATE_COLUMNS = ["shipment_id", "service_id", "cost_usd", "expected_hours", "std_hours",
                     "deadline_hours", "assumed_late_probability", "eligible", "rejection_reasons",
                     "balanced_score"]


def late_probability(mean: float, std: float, deadline: float) -> float:
    """Analytical tail of the assumed lognormal, not historical carrier reliability."""
    if std == 0:
        return float(mean > deadline)
    if deadline <= 0:
        return 1.0
    variance = math.log1p((std / mean) ** 2)
    mu = math.log(mean) - variance / 2
    z = (math.log(deadline) - mu) / math.sqrt(variance)
    return 0.5 * math.erfc(z / math.sqrt(2))


def balanced_score(cost, hours, risk, preferences: Preferences) -> float:
    wc, wt, wr = preferences.normalized()
    return wc * cost / COST_SCALE_USD + wt * hours / TIME_SCALE_HOURS + wr * risk


def candidate_table(data: PlanningData, constraints: Constraints,
                    preferences: Preferences = Preferences()) -> pd.DataFrame:
    orders = {order.shipment_id: order for order in data.orders}
    services = {service.service_id: service for service in data.services}
    records = []
    for item in data.candidates:
        order, service = orders[item.shipment_id], services[item.service_id]
        reasons = []
        if (order.origin, order.destination) != (service.origin, service.destination):
            reasons.append("Route mismatch")
        if units(order.weight_kg, 1000) > units(service.weight_capacity_kg, 1000, capacity=True):
            reasons.append("Weight exceeds service capacity")
        if units(order.volume_m3, 1000) > units(service.volume_capacity_m3, 1000, capacity=True):
            reasons.append("Volume exceeds service capacity")
        if service.shipment_capacity == 0:
            reasons.append("No shipment slots")
        if units(service.mean_hours, 60) > units(order.deadline_hours, 60, capacity=True):
            reasons.append("Expected arrival exceeds hard deadline")
        if units(item.cost_usd, 100) > units(constraints.budget_usd, 100, capacity=True):
            reasons.append("Individual cost exceeds total budget")
        risk = late_probability(service.mean_hours, service.std_hours, order.deadline_hours)
        records.append(dict(shipment_id=item.shipment_id, service_id=item.service_id,
                            cost_usd=item.cost_usd, expected_hours=service.mean_hours,
                            std_hours=service.std_hours, deadline_hours=order.deadline_hours,
                            assumed_late_probability=risk, eligible=not reasons,
                            rejection_reasons="; ".join(reasons),
                            balanced_score=balanced_score(item.cost_usd, service.mean_hours, risk, preferences)
                            if not reasons else None))
    return pd.DataFrame(records, columns=CANDIDATE_COLUMNS)


def single_order_recommendations(table: pd.DataFrame) -> pd.DataFrame:
    """Local suggestions only: other orders can consume the same capacity/budget."""
    records = []
    for shipment_id, group in table.groupby("shipment_id", sort=True):
        feasible = group.loc[group.eligible]
        for strategy, column in zip(STRATEGIES, ("cost_usd", "expected_hours", "balanced_score")):
            if feasible.empty:
                records.append(dict(shipment_id=shipment_id, strategy=strategy, service_id=None,
                                    explanation="No hard-eligible candidate", value=None))
            else:
                best = feasible.sort_values([column, "service_id"], kind="stable").iloc[0]
                records.append(dict(shipment_id=shipment_id, strategy=strategy, service_id=best.service_id,
                                    explanation="Passes individual checks; shared capacity not yet reserved",
                                    value=float(best[column])))
    return pd.DataFrame(records, columns=["shipment_id", "strategy", "service_id", "explanation", "value"])


def objective_coefficient(row, strategy, preferences):
    if strategy == "Lowest Cost":
        return units(row["cost_usd"], 100)
    if strategy == "Fastest Delivery":
        return round(row["expected_hours"] * TIME_VALUE_USD_PER_HOUR * 100)
    return round(balanced_score(row["cost_usd"], row["expected_hours"],
                                row["assumed_late_probability"], preferences) * COST_SCALE_USD * 100)


def status_name(status):
    return {cp_model.OPTIMAL: "OPTIMAL", cp_model.FEASIBLE: "FEASIBLE",
            cp_model.INFEASIBLE: "INFEASIBLE", cp_model.UNKNOWN: "UNKNOWN",
            cp_model.MODEL_INVALID: "MODEL_INVALID"}.get(status, "UNKNOWN")


@dataclass
class AllocationResult:
    strategy: str
    status: str
    assignments: pd.DataFrame
    unassigned_ids: tuple[str, ...]
    candidates: pd.DataFrame
    capacity: pd.DataFrame
    diagnostics: tuple[str, ...]
    elapsed_seconds: float
    objective_value: float | None = None
    best_bound: float | None = None

    @property
    def has_solution(self):
        return self.status in ("OPTIMAL", "FEASIBLE")


def capacity_usage(data: PlanningData, assignments: pd.DataFrame) -> pd.DataFrame:
    records = []
    for service in data.services:
        group = assignments.loc[assignments.service_id.eq(service.service_id)]
        weight, volume, count = group.weight_kg.sum(), group.volume_m3.sum(), len(group)
        records.append(dict(service_id=service.service_id, weight_used_kg=weight,
                            weight_capacity_kg=service.weight_capacity_kg,
                            volume_used_m3=volume, volume_capacity_m3=service.volume_capacity_m3,
                            shipments_used=count, shipment_capacity=service.shipment_capacity,
                            weight_utilization=weight / service.weight_capacity_kg if service.weight_capacity_kg else None,
                            volume_utilization=volume / service.volume_capacity_m3 if service.volume_capacity_m3 else None,
                            slot_utilization=count / service.shipment_capacity if service.shipment_capacity else None))
    return pd.DataFrame(records, columns=["service_id", "weight_used_kg", "weight_capacity_kg",
                                         "volume_used_m3", "volume_capacity_m3", "shipments_used",
                                         "shipment_capacity", "weight_utilization", "volume_utilization", "slot_utilization"])


def solve_allocation(data: PlanningData, constraints: Constraints, preferences: Preferences = Preferences(),
                     strategy="Optimized Allocation") -> AllocationResult:
    if strategy not in STRATEGIES:
        raise ValueError("Unknown optimization strategy.")
    started = time.perf_counter()
    table = candidate_table(data, constraints, preferences)
    records = table.to_dict("records")
    orders = {order.shipment_id: order for order in data.orders}
    services = {service.service_id: service for service in data.services}
    model = cp_model.CpModel()
    variables = {index: model.new_bool_var(f"x_{index}") for index, row in enumerate(records) if row["eligible"]}
    order_variables = {key: [] for key in orders}
    service_variables = {key: [] for key in services}
    for index, var in variables.items():
        row = records[index]
        order_variables[row["shipment_id"]].append(var)
        service_variables[row["service_id"]].append(index)
    unassigned = {}
    for key, choices in order_variables.items():
        if constraints.allow_unassigned:
            unassigned[key] = model.new_bool_var("unassigned_" + key)
            model.add(sum(choices) + unassigned[key] == 1)
        else:
            model.add(sum(choices) == 1)
    for key, indices in service_variables.items():
        service = services[key]
        model.add(sum(variables[index] for index in indices) <= service.shipment_capacity)
        model.add(sum(units(orders[records[index]["shipment_id"]].weight_kg, 1000) * variables[index]
                      for index in indices) <= units(service.weight_capacity_kg, 1000, capacity=True))
        model.add(sum(units(orders[records[index]["shipment_id"]].volume_m3, 1000) * variables[index]
                      for index in indices) <= units(service.volume_capacity_m3, 1000, capacity=True))
    model.add(sum(units(records[index]["cost_usd"], 100) * var for index, var in variables.items())
              <= units(constraints.budget_usd, 100, capacity=True))
    model.minimize(sum(objective_coefficient(records[index], strategy, preferences) * var
                       for index, var in variables.items())
                   + units(constraints.unassigned_penalty_usd, 100) * sum(unassigned.values()))
    error = model.validate()
    if error:
        raise ValueError("Invalid optimization model: " + error)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = constraints.time_limit_seconds
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 42
    status = status_name(solver.solve(model))
    selected = []
    diagnostics = []
    no_options = [key for key, choices in order_variables.items() if not choices]
    if no_options:
        diagnostics.append(f"{len(no_options)} order(s) have no hard-eligible candidate: " + ", ".join(no_options[:10]))
    eligible = table.loc[table.eligible.astype(bool)]
    if not no_options and not eligible.empty:
        lower_cost = sum(units(group.cost_usd.min(), 100) for _, group in eligible.groupby("shipment_id"))
        if lower_cost > units(constraints.budget_usd, 100, capacity=True):
            diagnostics.append(f"Even the sum of cheapest eligible individual choices (USD {lower_cost / 100:,.2f}) exceeds the total budget (USD {constraints.budget_usd:,.2f}).")
    if status == "INFEASIBLE":
        diagnostics.append("No assignment satisfies all constraints. Inspect individual rejections, shared capacities and budget. This is not an infeasibility proof for one specific constraint.")
    elif status == "UNKNOWN":
        diagnostics.append("No solution or infeasibility proof returned within the solver limit. Try a longer limit; do not interpret UNKNOWN as infeasible.")
    elif status == "MODEL_INVALID":
        diagnostics.append("Solver rejected the model. No recommendation is available.")
    if status in ("OPTIMAL", "FEASIBLE"):
        for index, var in variables.items():
            if solver.value(var):
                row = records[index]
                order = orders[row["shipment_id"]]
                selected.append({**{key: row[key] for key in ASSIGNMENT_COLUMNS if key in row},
                                 "weight_kg": order.weight_kg, "volume_m3": order.volume_m3})
    assignments = pd.DataFrame(selected, columns=ASSIGNMENT_COLUMNS)
    # In failed solves, these IDs are unresolved, not an accepted partial solution.
    assigned_ids = set(assignments.shipment_id)
    remaining = tuple(order for order in orders if order not in assigned_ids)
    result = AllocationResult(strategy, status, assignments, remaining, table,
                              capacity_usage(data, assignments), tuple(diagnostics), time.perf_counter() - started,
                              solver.objective_value if status in ("OPTIMAL", "FEASIBLE") else None,
                              solver.best_objective_bound if status in ("OPTIMAL", "FEASIBLE") else None)
    if result.has_solution:
        violations = audit_assignment(data, constraints, assignments)
        if violations:
            raise RuntimeError("Solver output failed independent feasibility audit: " + "; ".join(violations))
    return result


def audit_assignment(data: PlanningData, constraints: Constraints, assignments: pd.DataFrame) -> list[str]:
    """Recompute hard constraints from source objects, independent of solver expressions."""
    errors = []
    orders = {order.shipment_id: order for order in data.orders}
    services = {service.service_id: service for service in data.services}
    options = {(item.shipment_id, item.service_id): item for item in data.candidates}
    if assignments.shipment_id.duplicated().any():
        errors.append("More than one assignment for an order")
    if not constraints.allow_unassigned and set(assignments.shipment_id) != set(orders):
        errors.append("Not all required orders assigned")
    costs, used = 0, {key: [0, 0, 0] for key in services}
    for row in assignments.itertuples():
        if (row.shipment_id, row.service_id) not in options:
            errors.append("Unknown shipment/service pair")
            continue
        order, service = orders[row.shipment_id], services[row.service_id]
        option = options[row.shipment_id, row.service_id]
        costs += units(option.cost_usd, 100)
        if (order.origin, order.destination) != (service.origin, service.destination):
            errors.append("Route mismatch")
        if units(service.mean_hours, 60) > units(order.deadline_hours, 60, capacity=True):
            errors.append("Hard expected-time deadline violated")
        used[row.service_id][0] += units(order.weight_kg, 1000)
        used[row.service_id][1] += units(order.volume_m3, 1000)
        used[row.service_id][2] += 1
        if not math.isclose(float(row.cost_usd), option.cost_usd):
            errors.append("Assignment cost does not match input")
    if costs > units(constraints.budget_usd, 100, capacity=True):
        errors.append("Total budget exceeded")
    for key, (weight, volume, count) in used.items():
        service = services[key]
        if weight > units(service.weight_capacity_kg, 1000, capacity=True):
            errors.append(key + ": shared weight capacity exceeded")
        if volume > units(service.volume_capacity_m3, 1000, capacity=True):
            errors.append(key + ": shared volume capacity exceeded")
        if count > service.shipment_capacity:
            errors.append(key + ": shared shipment slots exceeded")
    return errors
