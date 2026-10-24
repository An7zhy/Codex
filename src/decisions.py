"""Deterministic what-if comparisons. Inputs are assumptions, not freight quotes."""

from dataclasses import asdict, dataclass
import json
import math

import pandas as pd

ACTIONS = ("Wait and monitor", "Request expedited handling", "Alternative transport arrangement")


@dataclass(frozen=True)
class ActionAssumption:
    action: str
    additional_cost: float
    remaining_hours: float
    assumed_available: bool = True
    notes: str = "Simulation only; capacity, price and service commitments are unverified."

    def __post_init__(self):
        if self.action not in ACTIONS:
            raise ValueError("Unsupported action.")
        for key, maximum in (("additional_cost", 1_000_000_000), ("remaining_hours", 87600)):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= maximum:
                raise ValueError(f"{key} must be finite and between 0 and {maximum}.")
        if not isinstance(self.assumed_available, bool) or not self.notes.strip():
            raise ValueError("Availability must be a boolean and assumptions must be documented.")


def default_assumptions() -> list[ActionAssumption]:
    return [ActionAssumption(action, cost, hours) for action, cost, hours in zip(ACTIONS, (0.0, 250.0, 800.0), (96.0, 48.0, 24.0))]


def compare_actions(cutoff: pd.Timestamp, deadline: pd.Timestamp | None,
                    assumptions: list[ActionAssumption]) -> pd.DataFrame:
    """Remaining time starts at the inclusive analysis cutoff; all costs are additional USD.

    An overdue age is never used as a forecast of remaining transit time.
    """
    if len(assumptions) != 3 or {option.action for option in assumptions} != set(ACTIONS):
        raise ValueError("Provide exactly one scenario for each of the three actions.")
    cutoff = pd.Timestamp(cutoff)
    if pd.isna(cutoff):
        raise ValueError("A valid scenario starting time is required.")
    cutoff = cutoff.tz_localize("UTC") if cutoff.tzinfo is None else cutoff.tz_convert("UTC")
    if deadline is not None:
        deadline = pd.Timestamp(deadline)
        if pd.isna(deadline):
            deadline = None
        else:
            deadline = deadline.tz_localize("UTC") if deadline.tzinfo is None else deadline.tz_convert("UTC")
    records = []
    for option in assumptions:
        arrival = pd.Timestamp(cutoff.value + pd.Timedelta(option.remaining_hours, unit="h").value, tz="UTC") if option.assumed_available else None
        slack = (deadline.value - arrival.value) / 3_600_000_000_000 if deadline is not None and arrival is not None else None
        impact = "Unavailable in this scenario" if not option.assumed_available else "Insufficient information: valid deadline required"
        if slack is not None:
            impact = f"Within deadline in scenario ({slack:.1f}h spare)" if slack >= 0 else f"Misses deadline in scenario ({-slack:.1f}h late)"
        records.append({
            "action": option.action, "estimated_additional_cost_usd": option.additional_cost,
            "assumed_remaining_hours": option.remaining_hours, "assumed_available": option.assumed_available,
            "scenario_arrival_utc": arrival.isoformat(timespec="minutes") if arrival is not None else None,
            "estimated_delay_hours": max(0.0, -slack) if slack is not None else None,
            "deadline_impact": impact, "key_assumptions": option.notes,
            "assumptions_json": json.dumps(asdict(option)),
        })
    return pd.DataFrame(records)
