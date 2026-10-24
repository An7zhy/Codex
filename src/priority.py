"""Explainable triage of active V1 exceptions, never a prediction or loss model."""

from dataclasses import asdict, dataclass, field
import json
import math
from pathlib import Path
from typing import Mapping

import pandas as pd

COMPONENTS = ("urgency", "delay", "financial", "value", "downstream")
DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config" / "priority_rules.json"


@dataclass(frozen=True)
class PriorityConfig:
    weights: dict[str, float] = field(default_factory=lambda: dict(zip(COMPONENTS, (30, 25, 20, 10, 15))))
    urgency_window_hours: float = 72
    delay_scale_hours: float = 72
    financial_scale_usd: float = 10000
    value_scale_usd: float = 100000
    dependency_scale: float = 5
    medium_threshold: float = 40
    high_threshold: float = 70

    def __post_init__(self):
        if not isinstance(self.weights, dict) or set(self.weights) != set(COMPONENTS):
            raise ValueError("Weights must define urgency, delay, financial, value and downstream.")
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in self.weights.values()):
            raise ValueError("Weights must be numeric values, not booleans or strings.")
        weights = [number(self.weights[key]) for key in COMPONENTS]
        if any(value is None for value in weights) or not 0 < sum(weights) <= 1_000_000:
            raise ValueError("Weights must be finite, nonnegative, with a positive sum at most 1,000,000.")
        for key in ("urgency_window_hours", "delay_scale_hours", "financial_scale_usd", "value_scale_usd", "dependency_scale"):
            value = number(getattr(self, key))
            if isinstance(getattr(self, key), bool) or not isinstance(getattr(self, key), (int, float)) or value is None or value <= 0:
                raise ValueError(f"{key} must be finite and positive.")
        if not (all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in (self.medium_threshold, self.high_threshold))
                and number(self.medium_threshold) is not None and number(self.high_threshold) is not None
                and 0 < self.medium_threshold < self.high_threshold <= 100):
            raise ValueError("Thresholds must satisfy 0 < medium < high <= 100.")

    @classmethod
    def load(cls, path: Path = DEFAULT_CONFIG):
        return cls(**json.loads(path.read_text(encoding="utf-8")))

    def to_dict(self):
        return asdict(self)


def number(value) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) and result >= 0 else None


def text(value) -> str:
    return "" if value is None or pd.isna(value) else str(value).strip()


def timestamp(value) -> pd.Timestamp | None:
    value = text(value)
    if not value or not (len(value) >= 10 and value[4] == "-" and value[7] == "-"):
        return None
    result = pd.to_datetime(value, format="ISO8601", utc=True, errors="coerce")
    return None if pd.isna(result) or result.year < 2000 else result


def delivery_deadline(row: Mapping) -> tuple[pd.Timestamp | None, str]:
    """Explicit deadline wins; invalid supplied deadlines never silently fall back."""
    explicit = text(row.get("delivery_deadline"))
    if explicit:
        value, source = timestamp(explicit), "delivery_deadline"
    else:
        codes = text(row.get("data_quality_issues"))
        if any(code in codes for code in ("plan_before_shipping", "invalid_shipped_at")):
            return None, "planned_delivery has invalid chronology"
        value, source = timestamp(row.get("planned_delivery")), "planned_delivery (fallback)"
    shipped = timestamp(row.get("shipped_at"))
    if value is not None and shipped is not None and value < shipped:
        return None, source + " precedes shipped_at"
    return value, source


def active_exception(row: Mapping) -> bool:
    return bool(row.get("included_in_analysis", False) and row.get("is_exception", False)
                and row.get("status") == "In Transit"
                and not text(row.get("actual_delivery_raw", row.get("actual_delivery"))))


def score_shipment(row: Mapping, cutoff: pd.Timestamp, config: PriorityConfig) -> dict:
    result = {"priority_score": None, "priority_level": "Insufficient information",
              "explanation": "", "missing_information": "", "coverage_percent": 0.0,
              "priority_lower_bound": None, "priority_upper_bound": None,
              "priority_details_json": "{}"}
    if not row.get("included_in_analysis", False):
        result.update(priority_level="Excluded", explanation="Missing/repeated ID: excluded by V1 rules.")
        return result
    if not row.get("is_exception", False):
        result.update(priority_level="Not an exception", explanation="V1 did not detect an exception; no active-exception priority assigned.")
        return result
    if not active_exception(row):
        result.update(priority_level="Review only", explanation="Completed/non-transit/conflicting record: review V1 evidence; no active transport priority or action forecast assigned.")
        return result

    scores: dict[str, float | None] = dict.fromkeys(COMPONENTS)
    explanations, missing = [], []
    deadline, deadline_source = delivery_deadline(row)
    if deadline is not None:
        hours = (deadline.value - cutoff.value) / 3_600_000_000_000
        scores["urgency"] = min(1.0, max(0.0, 1 - hours / config.urgency_window_hours))
        explanations.append(f"Urgency: {hours:.1f} hours to {deadline_source}; window {config.urgency_window_hours:g}h.")
    else:
        missing.append("urgency: valid delivery_deadline or valid planned_delivery required")
    delay = number(row.get("estimated_delay_hours"))
    if delay is not None:
        scores["delay"] = min(1.0, delay / config.delay_scale_hours)
        explanations.append(f"Delay: supplied scenario estimate {delay:g}h; not inferred from overdue age.")
    else:
        missing.append("delay: finite nonnegative estimated_delay_hours required")
    financial = number(row.get("estimated_financial_impact"))
    if financial is not None and text(row.get("financial_impact_basis")):
        scores["financial"] = min(1.0, financial / config.financial_scale_usd)
        explanations.append(f"Financial: declared estimate USD {financial:,.2f}; basis: {text(row.get('financial_impact_basis'))}. This is not realized loss.")
    else:
        missing.append("financial: estimated_financial_impact and financial_impact_basis required")
    value = number(row.get("shipment_value"))
    if value is not None:
        scores["value"] = min(1.0, value / config.value_scale_usd)
        explanations.append(f"Value: declared USD {value:,.2f} exposure context only; not a loss estimate.")
    else:
        missing.append("value: finite nonnegative shipment_value required")
    dependencies = number(row.get("downstream_dependency_count"))
    if dependencies is not None and dependencies.is_integer() and text(row.get("downstream_risk_basis")):
        scores["downstream"] = min(1.0, dependencies / config.dependency_scale)
        explanations.append(f"Downstream: {int(dependencies)} declared dependent activities; basis: {text(row.get('downstream_risk_basis'))}. Count is a proxy, not a failure probability.")
    else:
        missing.append("downstream: nonnegative integer downstream_dependency_count and downstream_risk_basis required")

    total_weight = sum(config.weights.values())
    enabled = {key for key in COMPONENTS if config.weights[key] > 0}
    known = {key for key in enabled if scores[key] is not None}
    missing = [entry for entry in missing if entry.split(":", 1)[0] in enabled]
    known_weight = sum(config.weights[key] for key in known)
    lower = sum(config.weights[key] * scores[key] for key in known) * 100 / total_weight
    upper = lower + (total_weight - known_weight) * 100 / total_weight
    if not missing:
        score = round(lower, 4)
        level = "High" if score >= config.high_threshold else "Medium" if score >= config.medium_threshold else "Low"
        result.update(priority_score=score, priority_level=level)
    result.update(
        coverage_percent=round(known_weight * 100 / total_weight, 2),
        priority_lower_bound=round(lower, 4), priority_upper_bound=round(upper, 4),
        explanation=" ".join(explanations) + (" Missing inputs are not treated as low risk; no complete score assigned." if missing else " Weighted score is a triage heuristic, not predicted loss."),
        missing_information="; ".join(missing),
        priority_details_json=json.dumps({"components": scores, "enabled": sorted(enabled), "known": sorted(known),
                                          "config": config.to_dict(), "context_source": text(row.get("decision_context_source"))}, allow_nan=False),
    )
    return result


def prioritize_shipments(shipments: pd.DataFrame, cutoff: pd.Timestamp, config: PriorityConfig | None = None) -> pd.DataFrame:
    config = config or PriorityConfig.load()
    # frozen dataclasses do not freeze nested dictionaries: validate/copy at the
    # public batch boundary so mutated settings cannot silently corrupt scores.
    config = PriorityConfig(**config.to_dict())
    frame = shipments.copy()
    records = [score_shipment(row, cutoff, config) for row in frame.to_dict("records")]
    columns = list(score_shipment({}, cutoff, config))
    for column in columns:
        frame[column] = pd.Series([record[column] for record in records], index=frame.index, dtype="float64" if column in {"priority_score", "coverage_percent", "priority_lower_bound", "priority_upper_bound"} else "object")
    return frame
