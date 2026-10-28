"""Disposable CPU worker. No database access, authentication or network calls."""

import sys
import json

from backend.schemas import OptimizationRequest


def calculate(body):
    # Imports stay in the worker; reuse the existing V3 implementation unchanged.
    from backend.main import records
    from src.transport.demo import generate_planning_demo, adjust_planning, demo_budget
    from src.transport.models import Constraints, Preferences
    from src.transport.experiments import compare_strategies, experiment_json
    from src.transport.engine import single_order_recommendations

    base = generate_planning_demo(body.count, body.data_seed)
    data = adjust_planning(base, deadline_shift_hours=body.deadline_shift_hours,
                           weight_capacity_factor=body.weight_capacity_percent / 100,
                           volume_capacity_factor=body.volume_capacity_percent / 100,
                           shipment_capacity_factor=body.shipment_capacity_percent / 100)
    constraints = Constraints(round(demo_budget(base) * body.budget_percent / 100, 2), body.allow_unassigned,
                              body.unassigned_penalty_usd, body.time_limit_seconds)
    preferences = Preferences(body.cost_weight, body.time_weight, body.risk_weight)
    experiment = compare_strategies(data, constraints, preferences, scenario_count=body.scenario_count, seed=body.seed)
    payload = json.loads(experiment_json(experiment))
    payload["request"] = body.model_dump()
    payload["simulation_details"] = {key: records(value) for key, value in experiment.simulation_details.items()}
    payload["candidate_checks"] = records(experiment.results["Optimized Allocation"].candidates)
    payload["local_recommendations"] = records(single_order_recommendations(experiment.results["Optimized Allocation"].candidates))
    return payload


if __name__ == "__main__":
    raw = json.loads(sys.stdin.buffer.read())
    if raw.get("mode") == "uploaded":
        from src.transport.uploaded import run_uploaded
        result = run_uploaded(raw["planning"])
    else:
        result = calculate(OptimizationRequest.model_validate(raw))
    print(json.dumps(result, allow_nan=False))
