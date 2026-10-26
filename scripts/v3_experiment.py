"""Reproducible synthetic V3 cases, measured workloads and saved-input replay.

python -m scripts.v3_experiment --orders 12 --case standard
python -m scripts.v3_experiment --benchmark --output docs/v3_benchmark.json
python -m scripts.v3_experiment --replay artifacts/v3/experiment.json
"""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import platform

import pandas as pd

from src.exports import csv_bytes
from src.transport.demo import adjust_planning, demo_budget, generate_planning_demo
from src.transport.experiments import compare_strategies, experiment_json, replay_experiment
from src.transport.models import Constraints, Preferences


def environment():
    return dict(timestamp_utc=datetime.now(timezone.utc).isoformat(), python=platform.python_version(),
                platform=platform.platform(), processor=platform.processor(),
                packages={name: importlib.metadata.version(name) for name in
                          ("ortools", "numpy", "pandas", "streamlit", "plotly", "pytest")})


def run_case(count=12, case="standard", time_limit=5, scenarios=2000):
    data = generate_planning_demo(0 if case == "empty" else count, seed=42)
    budget = demo_budget(data)
    if case == "capacity-shortage":
        data = adjust_planning(data, weight_capacity_factor=0)
    elif case == "no-eligible-service":
        data = adjust_planning(data, deadline_shift_hours=-400)
    elif case == "budget-shortage":
        budget = 0
    constraints = Constraints(budget, case == "allow-unassigned", time_limit_seconds=time_limit)
    if case == "allow-unassigned":
        data = adjust_planning(data, weight_capacity_factor=0)
    return compare_strategies(data, constraints, Preferences(), scenario_count=scenarios, seed=2026)


def benchmark(output: Path):
    evidence = dict(environment=environment(), provenance="Synthetic Demo Data", runs=[])
    for count in (100, 500):
        for repeat in range(3):
            run = run_case(count)
            row = dict(orders=count, repeat=repeat + 1, elapsed_seconds=run.elapsed_seconds,
                       constraints=asdict(run.constraints), preferences=asdict(run.preferences),
                       data_seed=42, monte_carlo_seed=run.seed, scenario_count=run.scenario_count,
                       strategies=json.loads(run.summary.to_json(orient="records")))
            evidence["runs"].append(row)
            print(f"{count} orders, repeat {repeat + 1}: {run.elapsed_seconds:.3f}s; "
                  + ", ".join(f"{key}={result.status}" for key, result in run.results.items()), flush=True)
            if not run.summary.has_feasible_solution.all():
                raise RuntimeError("Benchmark did not obtain all feasible solutions; inspect solver limits.")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, allow_nan=False), encoding="utf-8")
    print("Measured evidence:", output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--orders", type=int, default=12)
    parser.add_argument("--case", choices=["standard", "capacity-shortage", "budget-shortage",
                                          "no-eligible-service", "allow-unassigned", "empty"], default="standard")
    parser.add_argument("--time-limit", type=float, default=5)
    parser.add_argument("--scenarios", type=int, default=2000)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--benchmark", action="store_true")
    parser.add_argument("--replay", type=Path)
    arguments = parser.parse_args()
    if arguments.benchmark:
        benchmark(arguments.output or Path("docs/v3_benchmark.json"))
        return
    run = replay_experiment(arguments.replay.read_text(encoding="utf-8")) if arguments.replay else run_case(
        arguments.orders, arguments.case, arguments.time_limit, arguments.scenarios)
    output = arguments.output or Path("artifacts/v3/experiment.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(experiment_json(run), encoding="utf-8")
    output.with_suffix(".csv").write_bytes(csv_bytes(run.summary))
    print(run.summary[["strategy", "status", "total_shipping_cost_usd", "unassigned_orders",
                       "simulated_on_time_rate_all_orders", "allocation_seconds"]].to_string(index=False))
    print("Reproducible inputs/results:", output)


if __name__ == "__main__":
    main()
