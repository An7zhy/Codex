"""Seeded common-random-number lognormal scenarios; never real actual transit."""

from dataclasses import dataclass
import hashlib
import math
import time

import numpy as np
import pandas as pd

from .engine import AllocationResult
from .models import PlanningData, integer


@dataclass(frozen=True)
class ScenarioBank:
    samples: dict[str, np.ndarray]
    seed: int
    count: int
    fingerprint: str


def generate_scenarios(data: PlanningData, count=2000, seed=2026) -> ScenarioBank:
    count = integer(count, "Monte Carlo scenario count", 1, 100_000)
    seed = integer(seed, "Monte Carlo seed", 0, 2**32 - 1)
    if len(data.services) * count > 5_000_000:
        raise ValueError("Scenario matrix exceeds prototype memory limit (5 million values).")
    samples = {}
    digest = hashlib.sha256()
    # Stable service-specific streams preserve common shocks when service order changes.
    for service in sorted(data.services, key=lambda item: item.service_id):
        stable_id = int.from_bytes(hashlib.sha256(service.service_id.encode()).digest()[:8], "little")
        rng = np.random.default_rng(np.random.SeedSequence([seed, stable_id]))
        if service.std_hours == 0:
            times = np.full(count, service.mean_hours)
        else:
            variance = math.log1p((service.std_hours / service.mean_hours) ** 2)
            mu = math.log(service.mean_hours) - variance / 2
            times = rng.lognormal(mu, math.sqrt(variance), size=count)
        times.setflags(write=False)
        samples[service.service_id] = times
        digest.update(service.service_id.encode())
        digest.update(times.tobytes())
    return ScenarioBank(samples, seed, count, digest.hexdigest())


def simulate_allocation(data: PlanningData, result: AllocationResult, scenarios: ScenarioBank):
    started = time.perf_counter()
    summary = dict(simulated_on_time_rate_all_orders=None, simulated_on_time_rate_assigned=None,
                   simulated_late_probability_assigned=None, on_time_rate_monte_carlo_se=None,
                   expected_on_time_rate_all_orders=None, mean_simulated_delay_hours_assigned=None,
                   p95_total_delay_hours=None, analytic_late_probability_assigned=None,
                   scenario_count=scenarios.count, scenario_fingerprint=scenarios.fingerprint)
    details = []
    if not result.has_solution:
        summary["simulation_seconds"] = time.perf_counter() - started
        return summary, pd.DataFrame()
    on_time = np.zeros(scenarios.count)
    total_delay = np.zeros(scenarios.count)
    for row in result.assignments.itertuples():
        times = scenarios.samples[row.service_id]
        met_deadline = times <= row.deadline_hours
        delays = np.maximum(0, times - row.deadline_hours)
        on_time += met_deadline
        total_delay += delays
        details.append(dict(shipment_id=row.shipment_id, service_id=row.service_id,
                            expected_hours=row.expected_hours, deadline_hours=row.deadline_hours,
                            assumed_std_hours=row.std_hours,
                            simulated_transit_hours_scenario_0=float(times[0]),
                            estimated_late_probability=float(1 - met_deadline.mean()),
                            mean_simulated_transit_hours=float(times.mean()),
                            p95_simulated_transit_hours=float(np.quantile(times, 0.95))))
    total, assigned = len(data.orders), len(result.assignments)
    if total:
        summary["simulated_on_time_rate_all_orders"] = float(on_time.mean() / total)
        # Independent scenario draws; within-service shipments share a common shock.
        summary["on_time_rate_monte_carlo_se"] = float(np.std(on_time / total, ddof=1) / math.sqrt(scenarios.count)) if scenarios.count > 1 else None
        summary["expected_on_time_rate_all_orders"] = float((result.assignments.expected_hours <= result.assignments.deadline_hours).sum() / total)
        summary["p95_total_delay_hours"] = float(np.quantile(total_delay, 0.95))
    if assigned:
        summary["simulated_on_time_rate_assigned"] = float(on_time.mean() / assigned)
        summary["simulated_late_probability_assigned"] = float(1 - on_time.mean() / assigned)
        summary["analytic_late_probability_assigned"] = float(result.assignments.assumed_late_probability.mean())
        summary["mean_simulated_delay_hours_assigned"] = float(total_delay.mean() / assigned)
    summary["simulation_seconds"] = time.perf_counter() - started
    return summary, pd.DataFrame(details)
