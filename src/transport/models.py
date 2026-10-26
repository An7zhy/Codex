"""Validated planning inputs and documented conservative integer conversions."""

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import math
from numbers import Real


def number(value, name: str, low=0.0, high=1e9) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite number.")
    value = float(value)
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}.")
    return value


def integer(value, name: str, low=0, high=1_000_000) -> int:
    checked = number(value, name, low, high)
    if not checked.is_integer():
        raise ValueError(f"{name} must be an integer.")
    return int(checked)


def text(value, name):
    if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > 150:
        raise ValueError(f"{name} must be nonblank trimmed text (at most 150 characters).")


def units(value: float, scale: int, *, capacity=False) -> int:
    """Round demands/costs/time up, resources/budget/deadlines down."""
    return int((Decimal(str(value)) * scale).to_integral_value(
        rounding=ROUND_FLOOR if capacity else ROUND_CEILING))


@dataclass(frozen=True)
class Order:
    shipment_id: str
    origin: str
    destination: str
    weight_kg: float
    volume_m3: float
    deadline_hours: float

    def __post_init__(self):
        for name in ("shipment_id", "origin", "destination"):
            text(getattr(self, name), name)
        number(self.weight_kg, "Order weight", 0.001, 1e6)
        number(self.volume_m3, "Order volume", 0.001, 1e5)
        number(self.deadline_hours, "Deadline hours", 0, 87600)


@dataclass(frozen=True)
class Service:
    service_id: str
    origin: str
    destination: str
    mode: str
    mean_hours: float
    std_hours: float
    weight_capacity_kg: float
    volume_capacity_m3: float
    shipment_capacity: int

    def __post_init__(self):
        for name in ("service_id", "origin", "destination", "mode"):
            text(getattr(self, name), name)
        number(self.mean_hours, "Expected transport hours", 1 / 60, 87600)
        number(self.std_hours, "Transport standard deviation", 0, 87600)
        number(self.weight_capacity_kg, "Weight capacity", 0, 1e9)
        number(self.volume_capacity_m3, "Volume capacity", 0, 1e8)
        object.__setattr__(self, "shipment_capacity", integer(self.shipment_capacity, "Shipment capacity"))


@dataclass(frozen=True)
class Candidate:
    shipment_id: str
    service_id: str
    cost_usd: float

    def __post_init__(self):
        text(self.shipment_id, "Candidate shipment ID")
        text(self.service_id, "Candidate service ID")
        number(self.cost_usd, "Candidate cost", 0, 1e9)


@dataclass(frozen=True)
class PlanningData:
    orders: tuple[Order, ...]
    services: tuple[Service, ...]
    candidates: tuple[Candidate, ...]

    def __post_init__(self):
        for values, cls, name in ((self.orders, Order, "orders"), (self.services, Service, "services"),
                                  (self.candidates, Candidate, "candidates")):
            if not isinstance(values, tuple) or not all(isinstance(value, cls) for value in values):
                raise ValueError(f"{name} must be a tuple of {cls.__name__} objects.")
        if len(self.orders) > 5000 or len(self.services) > 1000 or len(self.candidates) > 50_000:
            raise ValueError("Prototype limit: 5000 orders, 1000 services, 50000 candidates.")
        ids = [order.shipment_id for order in self.orders]
        services = [service.service_id for service in self.services]
        if len(ids) != len(set(ids)) or len(services) != len(set(services)):
            raise ValueError("Shipment and service IDs must be unique.")
        pairs = [(item.shipment_id, item.service_id) for item in self.candidates]
        if len(pairs) != len(set(pairs)):
            raise ValueError("Duplicate shipment/service candidate.")
        order_ids, service_ids = set(ids), set(services)
        if any(order not in order_ids or service not in service_ids for order, service in pairs):
            raise ValueError("Candidate references an unknown order or service.")


@dataclass(frozen=True)
class Preferences:
    cost: float = 0.3
    time: float = 0.3
    risk: float = 0.4

    def __post_init__(self):
        for key in ("cost", "time", "risk"):
            number(getattr(self, key), key + " weight", 0, 1e6)
        if self.cost + self.time + self.risk <= 0:
            raise ValueError("At least one optimization weight must be positive.")

    def normalized(self):
        total = self.cost + self.time + self.risk
        return self.cost / total, self.time / total, self.risk / total


@dataclass(frozen=True)
class Constraints:
    budget_usd: float
    allow_unassigned: bool = False
    unassigned_penalty_usd: float = 100_000.0
    time_limit_seconds: float = 5.0

    def __post_init__(self):
        number(self.budget_usd, "Budget", 0, 1e12)
        number(self.unassigned_penalty_usd, "Unassigned penalty", 0, 1e9)
        number(self.time_limit_seconds, "Solver time limit", 1e-9, 60)
        if not isinstance(self.allow_unassigned, bool):
            raise ValueError("allow_unassigned must be a boolean.")
