"""Fictional planning inputs: no carrier data, market quotes or transit benchmarks."""

from dataclasses import replace
import math

import numpy as np

from .models import Candidate, Order, PlanningData, Service, integer, number


def generate_planning_demo(count=12, seed=42) -> PlanningData:
    count = integer(count, "Order count", 0, 5000)
    seed = integer(seed, "Seed", 0, 2**32 - 1)
    rng = np.random.default_rng(seed)
    lanes = [("Shanghai, China", "Rotterdam, Netherlands"),
             ("Shenzhen, China", "Los Angeles, USA"),
             ("Singapore", "Hamburg, Germany")]
    orders = []
    for index in range(count):
        origin, destination = lanes[index % 3]
        deadline = [48.0, 96.0, 384.0, 384.0][(index // 3) % 4]
        orders.append(Order(f"PLAN-{index + 1:04d}", origin, destination,
                            float(rng.integers(50, 301)), round(float(rng.uniform(0.2, 2)), 3), deadline))
    services, candidates = [], []
    for lane, (origin, destination) in enumerate(lanes):
        group = [order for order in orders if order.origin == origin and order.destination == destination]
        if not group:
            continue
        weight = max(max(order.weight_kg for order in group), sum(order.weight_kg for order in group) * 0.75)
        volume = max(max(order.volume_m3 for order in group), sum(order.volume_m3 for order in group) * 0.75)
        for name, mode, hours, std, fixed, per_kg in [
            ("PRIORITY", "Air", 24.0, 6.0, 900, 8),
            ("REGULAR", "Air", 48.0, 12.0, 500, 5),
            ("ECONOMY", "Sea", 336.0, 48.0, 150, 1.5),
        ]:
            sid = f"SYN-L{lane + 1}-{name}"
            services.append(Service(sid, origin, destination, mode, hours, std,
                                    round(weight, 3), round(volume, 3), math.ceil(len(group) * 0.75)))
            candidates.extend(Candidate(order.shipment_id, sid, fixed + per_kg * order.weight_kg)
                              for order in group)
    return PlanningData(tuple(orders), tuple(services), tuple(candidates))


def adjust_planning(data: PlanningData, *, deadline_shift_hours=0.0, weight_capacity_factor=1.0,
                    volume_capacity_factor=1.0, shipment_capacity_factor=1.0) -> PlanningData:
    """Create a new scenario; never mutate a previous run's input objects."""
    number(deadline_shift_hours, "Deadline shift", -87600, 87600)
    for value in (weight_capacity_factor, volume_capacity_factor, shipment_capacity_factor):
        number(value, "Capacity factor", 0, 10)
    orders = tuple(replace(order, deadline_hours=max(0, order.deadline_hours + deadline_shift_hours))
                   for order in data.orders)
    services = tuple(replace(service,
                             weight_capacity_kg=round(service.weight_capacity_kg * weight_capacity_factor, 3),
                             volume_capacity_m3=round(service.volume_capacity_m3 * volume_capacity_factor, 3),
                             shipment_capacity=math.floor(service.shipment_capacity * shipment_capacity_factor))
                     for service in data.services)
    return PlanningData(orders, services, data.candidates)


def demo_budget(data: PlanningData) -> float:
    """Sum of each order's most expensive synthetic option, not a market estimate."""
    maxima = {order.shipment_id: 0.0 for order in data.orders}
    for option in data.candidates:
        maxima[option.shipment_id] = max(maxima[option.shipment_id], option.cost_usd)
    return sum(maxima.values())
