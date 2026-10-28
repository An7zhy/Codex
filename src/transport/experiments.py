"""Comparable constrained strategy experiments and reproducible JSON exports."""

from dataclasses import asdict, dataclass
import hashlib
import json
import time

import pandas as pd

from .engine import AllocationResult, STRATEGIES, solve_allocation
from .models import Constraints, PlanningData, Preferences
from .simulation import generate_scenarios, simulate_allocation


@dataclass
class Experiment:
    data: PlanningData
    constraints: Constraints
    preferences: Preferences
    summary: pd.DataFrame
    results: dict[str, AllocationResult]
    simulation_details: dict[str, pd.DataFrame]
    seed: int
    scenario_count: int
    fingerprint: str
    elapsed_seconds: float


def compare_strategies(data: PlanningData, constraints: Constraints, preferences=Preferences(),
                       *, scenario_count=2000, seed=2026, simulate=True) -> Experiment:
    started = time.perf_counter()
    if not simulate and preferences.risk:
        raise ValueError("Reliability weight must be zero when no transit distribution is supplied.")
    bank = generate_scenarios(data, scenario_count, seed) if simulate else None
    fingerprint = bank.fingerprint if bank else hashlib.sha256(json.dumps(asdict(data), sort_keys=True).encode()).hexdigest()
    rows, results, details = [], {}, {}
    for strategy in STRATEGIES:
        result = solve_allocation(data, constraints, preferences, strategy)
        if bank:
            metrics, detail = simulate_allocation(data, result, bank)
        else:
            # No MC draws, no inferred reliability, no pretend zero-variance facts.
            metrics = dict(simulated_on_time_rate_all_orders=None, simulated_on_time_rate_assigned=None,
                           simulated_late_probability_assigned=None, on_time_rate_monte_carlo_se=None,
                           expected_on_time_rate_all_orders=None, mean_simulated_delay_hours_assigned=None,
                           p95_total_delay_hours=None, analytic_late_probability_assigned=None,
                           scenario_count=0, scenario_fingerprint=fingerprint, simulation_seconds=0)
            detail = pd.DataFrame()
        results[strategy], details[strategy] = result, detail
        usage = result.capacity
        record = dict(strategy=strategy, status=result.status, has_feasible_solution=result.has_solution,
                      fully_assigned=result.has_solution and not result.unassigned_ids,
                      total_shipping_cost_usd=float(result.assignments.cost_usd.sum()) if result.has_solution else None,
                      unassigned_orders=len(result.unassigned_ids) if result.has_solution else None,
                      unresolved_orders=len(data.orders) if not result.has_solution else 0,
                      assigned_orders=len(result.assignments) if result.has_solution else None,
                      unassigned_penalty_objective_usd=len(result.unassigned_ids) * constraints.unassigned_penalty_usd if result.has_solution else None,
                      allocation_seconds=result.elapsed_seconds,
                      weight_utilization=None, volume_utilization=None, slot_utilization=None)
        if result.has_solution and not usage.empty:
            for name, used, capacity in [("weight_utilization", "weight_used_kg", "weight_capacity_kg"),
                                          ("volume_utilization", "volume_used_m3", "volume_capacity_m3"),
                                          ("slot_utilization", "shipments_used", "shipment_capacity")]:
                denominator = usage[capacity].sum()
                record[name] = float(usage[used].sum() / denominator) if denominator else None
        rows.append({**record, **metrics})
    summary = pd.DataFrame(rows)
    # No savings claim against infeasible or differently fulfilled allocations.
    all_full = bool(summary.fully_assigned.all())
    summary["same_full_fulfillment_comparison"] = all_full
    return Experiment(data, constraints, preferences, summary, results, details, seed,
                      scenario_count if bank else 0, fingerprint, time.perf_counter() - started)


def experiment_json(experiment: Experiment) -> str:
    """No NaN JSON. Includes full inputs so no changing demo generator is required."""
    result = {
        "schema": "logistics-insight-v3-experiment-1",
        "provenance": "Synthetic Demo Data; hypothetical capacities, prices and lognormal transit assumptions",
        "data": asdict(experiment.data), "constraints": asdict(experiment.constraints),
        "preferences": asdict(experiment.preferences), "seed": experiment.seed,
        "scenario_count": experiment.scenario_count, "scenario_fingerprint": experiment.fingerprint,
        "elapsed_seconds": experiment.elapsed_seconds,
        "summary": json.loads(experiment.summary.to_json(orient="records")),
        "results": {key: {"status": value.status, "objective_value_integer_units": value.objective_value,
                           "best_bound_integer_units": value.best_bound, "diagnostics": value.diagnostics,
                           "unassigned_ids": value.unassigned_ids,
                           "assignments": json.loads(value.assignments.to_json(orient="records")),
                           "capacity": json.loads(value.capacity.to_json(orient="records"))}
                    for key, value in experiment.results.items()},
    }
    return json.dumps(result, indent=2, allow_nan=False)


def replay_experiment(payload: str) -> Experiment:
    """Recompute a locally saved run, treating imported JSON as untrusted input."""
    from .models import Candidate, Order, Service

    if len(payload.encode()) > 20_000_000:
        raise ValueError("Experiment JSON exceeds 20 MB.")
    try:
        raw = json.loads(payload)
        if raw["schema"] != "logistics-insight-v3-experiment-1":
            raise ValueError("Unsupported experiment schema.")
        data = PlanningData(tuple(Order(**row) for row in raw["data"]["orders"]),
                            tuple(Service(**row) for row in raw["data"]["services"]),
                            tuple(Candidate(**row) for row in raw["data"]["candidates"]))
        return compare_strategies(data, Constraints(**raw["constraints"]), Preferences(**raw["preferences"]),
                                  scenario_count=raw["scenario_count"], seed=raw["seed"])
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid experiment input structure.") from exc
