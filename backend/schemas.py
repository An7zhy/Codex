"""HTTP validation; domain classes remain the authoritative business validators."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    @field_validator("*", mode="before")
    @classmethod
    def reject_numeric_booleans(cls, value, info):
        if isinstance(value, bool) and info.field_name not in {"allow_unassigned", "assumed_available"}:
            raise ValueError("Booleans cannot substitute for numeric or text inputs.")
        if info.field_name == "weights" and isinstance(value, dict) and any(isinstance(item, bool) for item in value.values()):
            raise ValueError("Weights must be numbers, not booleans.")
        return value


class PrioritySettings(StrictBody):
    expected_version: int = Field(ge=1, strict=True)
    weights: dict[str, float] = Field(default_factory=lambda: dict(zip(
        ("urgency", "delay", "financial", "value", "downstream"), (30, 25, 20, 10, 15))))
    urgency_window_hours: float = 72
    delay_scale_hours: float = 72
    financial_scale_usd: float = 10000
    value_scale_usd: float = 100000
    dependency_scale: float = 5
    medium_threshold: float = 40
    high_threshold: float = 70


class ScenarioInput(StrictBody):
    action: Literal["Wait and monitor", "Request expedited handling", "Alternative transport arrangement"]
    additional_cost: float = Field(ge=0, le=1e9)
    remaining_hours: float = Field(ge=0, le=87600)
    assumed_available: bool = True
    notes: str = Field(default="Simulation only; availability and service commitments are unverified.", min_length=1, max_length=2000)


class DecisionRequest(StrictBody):
    dataset_id: str = "demo"
    as_of: date = date(2026, 10, 1)
    shipment_id: str = Field(min_length=1, max_length=200)
    assumptions: list[ScenarioInput] = Field(min_length=3, max_length=3)


class SaveCaseRequest(DecisionRequest):
    comparison_token: str = Field(min_length=64, max_length=64)
    selected_action: str
    exception_type: str = Field(min_length=1, max_length=500)
    resolution_notes: str = Field(default="", max_length=4000)


class UpdateCaseRequest(StrictBody):
    resolution_status: Literal["Open", "In Progress", "Resolved", "Cancelled"]
    actual_cost: float | None = Field(default=None, ge=0, le=1e9)
    actual_delay: float | None = Field(default=None, ge=0, le=1e9)
    resolution_notes: str = Field(default="", max_length=4000)
    expected_version: int = Field(ge=1)


class OptimizationRequest(StrictBody):
    count: int = Field(default=12, ge=0, le=500)
    data_seed: int = Field(default=42, ge=0, le=2**32 - 1)
    budget_percent: float = Field(default=100, ge=0, le=150)
    deadline_shift_hours: float = Field(default=0, ge=-400, le=400)
    weight_capacity_percent: float = Field(default=100, ge=0, le=200)
    volume_capacity_percent: float = Field(default=100, ge=0, le=200)
    shipment_capacity_percent: float = Field(default=100, ge=0, le=200)
    allow_unassigned: bool = False
    unassigned_penalty_usd: float = Field(default=100000, ge=0, le=1e6)
    cost_weight: float = Field(default=30, ge=0, le=100)
    time_weight: float = Field(default=30, ge=0, le=100)
    risk_weight: float = Field(default=40, ge=0, le=100)
    scenario_count: int = Field(default=2000, ge=100, le=10000)
    seed: int = Field(default=2026, ge=0, le=2**32 - 1)
    time_limit_seconds: float = Field(default=5, ge=.1, le=10)
