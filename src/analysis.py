"""Explainable shipment rules and KPIs. No model calls or Streamlit imports."""

from dataclasses import dataclass
from datetime import date
import math

import pandas as pd

from src.ingestion import validate_columns
from src.schema import EARLIEST_DATE, MAX_SHIPPING_COST, MIN_COST_GROUP_SIZE, REQUIRED_COLUMNS

ISSUE_COLUMNS = ["source_row", "shipment_id", "field", "code", "severity", "message", "raw_value"]
STATUS_ALIASES = {
    "delivered": "Delivered", "in transit": "In Transit", "in_transit": "In Transit",
    "pending": "Pending", "delivery failed": "Delivery Failed", "returned": "Returned",
}
MODE_ALIASES = {
    "air": "Air", "sea": "Sea", "ocean": "Sea", "road": "Road", "rail": "Rail",
}


@dataclass
class AnalysisResult:
    shipments: pd.DataFrame
    issues: pd.DataFrame
    as_of: date
    cutoff: pd.Timestamp


def _text(values: pd.Series) -> pd.Series:
    return values.astype("string").fillna("").str.strip()


def _dates(values: pd.Series) -> pd.Series:
    """Accept ISO dates/timestamps only. Numeric serials and ambiguous dates are invalid."""
    text = _text(values)
    iso = text.str.match(r"^\d{4}-\d{2}-\d{2}(?:[Tt ].*)?$")
    return pd.to_datetime(text.where(iso), format="ISO8601", errors="coerce", utc=True)


def analyze_shipments(raw: pd.DataFrame, as_of: date | str) -> AnalysisResult:
    """Retain every source row; quarantine missing IDs and subsequent duplicate IDs.

    The analysis date is an inclusive UTC calendar day. Field-level quality errors
    affect only the metrics that need those fields, rather than dropping whole rows.
    """
    original = validate_columns(raw).reset_index(drop=True)
    frame = original.copy()
    frame["source_row"] = pd.Series(range(2, len(frame) + 2), dtype="int64")
    for column in REQUIRED_COLUMNS:
        frame[column + "_raw"] = original[column]
        frame[column] = _text(original[column])
    day = pd.Timestamp(as_of)
    if pd.isna(day):
        raise ValueError("Choose a valid analysis date.")
    day = (day.tz_localize("UTC") if day.tzinfo is None else day.tz_convert("UTC")).normalize()
    # Parse at nanosecond resolution; Timestamp.replace on a seconds-resolution
    # Timestamp can display fractions that its underlying value does not retain.
    cutoff = pd.Timestamp(day.date().isoformat() + "T23:59:59.999999999Z")
    earliest = pd.Timestamp(EARLIEST_DATE, tz="UTC")
    issues: list[dict] = []

    def add(mask: pd.Series, field: str, code: str, message: str, severity: str = "error") -> None:
        for index in frame.index[mask.fillna(False)]:
            value = original.at[index, field] if field in original else ""
            issues.append({
                "source_row": int(frame.at[index, "source_row"]),
                "shipment_id": str(frame.at[index, "shipment_id"]),
                "field": field, "code": code, "severity": severity,
                "message": message, "raw_value": "" if pd.isna(value) else str(value),
            })

    missing_id = frame["shipment_id"].eq("")
    duplicate = frame["shipment_id"].duplicated(keep="first") & ~missing_id
    duplicate_first = frame["shipment_id"].duplicated(keep=False) & ~duplicate & ~missing_id
    frame["included_in_analysis"] = ~(missing_id | duplicate)
    add(missing_id, "shipment_id", "missing_shipment_id", "Missing ID: row excluded from shipment KPIs.")
    add(duplicate, "shipment_id", "duplicate_id", "Repeated ID: first occurrence retained; this row excluded.")
    add(duplicate_first, "shipment_id", "duplicate_id_retained", "ID is repeated elsewhere; this first occurrence is retained.", "warning")

    for column in ("origin", "destination", "transport_mode", "carrier", "status"):
        add(frame[column].eq(""), column, "missing_" + column, "Missing required " + column + ".")
    for column in ("origin", "destination", "carrier"):
        frame[column] = frame[column].str.replace(r"\s+", " ", regex=True).replace("", "Unknown")
    for column, mapping in (("status", STATUS_ALIASES), ("transport_mode", MODE_ALIASES)):
        normalized = frame[column].str.casefold().map(mapping)
        add(normalized.isna() & frame[column].ne(""), column, "unsupported_" + column,
            "Unsupported value; see the documented accepted values.")
        frame[column] = normalized.fillna("Unknown")

    for column in ("planned_delivery", "actual_delivery"):
        supplied = frame[column].ne("")
        parsed = _dates(original[column])
        add(supplied & parsed.isna(), column, "invalid_" + column, "Invalid date: use ISO YYYY-MM-DD or an ISO timestamp.")
        too_early = parsed.lt(earliest)
        add(too_early, column, "implausible_" + column, "Date before 2000-01-01; excluded from time metrics.")
        frame[column] = parsed.mask(too_early)
        if column == "planned_delivery":
            add(~supplied, column, "missing_planned_delivery", "Missing planned delivery: excluded from on-time and overdue calculations.")
        else:
            actual_supplied = supplied
            add(~supplied & frame["status"].eq("Delivered"), column, "missing_actual_delivery", "Reported Delivered but actual delivery is missing; completion is unverified.")

    actual_before_shipping = pd.Series(False, index=frame.index)
    planned_before_shipping = pd.Series(False, index=frame.index)
    invalid_shipping = pd.Series(False, index=frame.index)
    if "shipped_at" in original:
        frame["shipped_at_raw"] = original["shipped_at"]
        supplied = _text(original["shipped_at"]).ne("")
        parsed = _dates(original["shipped_at"])
        invalid_shipping = supplied & (parsed.isna() | parsed.lt(earliest))
        add(invalid_shipping, "shipped_at", "invalid_shipped_at", "Invalid supplied shipping date; temporal KPIs cannot verify chronology.")
        frame["shipped_at"] = parsed.mask(invalid_shipping)
        actual_before_shipping = frame["actual_delivery"].lt(frame["shipped_at"])
        planned_before_shipping = frame["planned_delivery"].lt(frame["shipped_at"])
        add(actual_before_shipping, "actual_delivery", "delivery_before_shipping", "Actual delivery precedes shipped_at; excluded from completion metrics.")
        add(planned_before_shipping, "planned_delivery", "plan_before_shipping", "Planned delivery precedes shipped_at; excluded from time comparisons.")
    future_actual = frame["actual_delivery"].gt(cutoff)
    add(future_actual, "actual_delivery", "actual_after_cutoff", "Actual delivery is after the analysis cutoff; completion is not counted in this snapshot.")
    add(actual_supplied & frame["status"].ne("Delivered"), "status", "status_date_conflict", "An actual delivery is supplied for a status other than Delivered; verify the record.")

    # Commas are accepted only when they are properly grouped thousands separators.
    cost_text = _text(original["shipping_cost"])
    thousands = cost_text.str.match(r"^-?\d{1,3}(?:,\d{3})+(?:\.\d+)?$")
    cost_text = cost_text.where(~thousands, cost_text.str.replace(",", "", regex=False))
    cost = pd.to_numeric(cost_text, errors="coerce").astype("float64")
    finite = cost.map(math.isfinite).astype(bool)
    numeric_cost_valid = finite & cost.ge(0) & cost.le(MAX_SHIPPING_COST)
    currency_columns = [name for name in ("currency", "shipping_currency", "cost_currency") if name in original]
    currency_valid = pd.Series(True, index=frame.index)
    for column in currency_columns:
        currency_valid &= _text(original[column]).str.upper().eq("USD")
        add(~_text(original[column]).str.upper().eq("USD"), column, "unsupported_currency",
            "Currency must be explicitly USD. This cost is excluded; no FX conversion is performed.")
    frame["valid_cost"] = numeric_cost_valid & currency_valid
    frame["shipping_cost"] = cost.where(frame["valid_cost"])
    add(_text(original["shipping_cost"]).eq(""), "shipping_cost", "missing_cost", "Missing cost; excluded from cost metrics.")
    add(_text(original["shipping_cost"]).ne("") & ~numeric_cost_valid, "shipping_cost", "invalid_cost", f"Cost must be a finite USD number between 0 and {MAX_SHIPPING_COST:,} (technical safety limit).")

    plan_valid = frame["planned_delivery"].notna() & ~planned_before_shipping & ~invalid_shipping
    frame["is_delivered"] = (
        frame["included_in_analysis"] & frame["status"].eq("Delivered")
        & frame["actual_delivery"].notna() & ~future_actual
        & ~actual_before_shipping & ~invalid_shipping
    )
    frame["delivery_eligible"] = frame["is_delivered"] & plan_valid
    difference = (frame["actual_delivery"] - frame["planned_delivery"]).dt.total_seconds() / 3600
    frame["delay_hours"] = difference.clip(lower=0).where(frame["delivery_eligible"])
    frame["is_delayed"] = frame["delivery_eligible"] & difference.gt(0)
    frame["is_on_time"] = frame["delivery_eligible"] & difference.le(0)
    frame["is_overdue"] = (
        frame["included_in_analysis"] & frame["status"].eq("In Transit")
        & plan_valid & frame["planned_delivery"].lt(cutoff) & ~actual_supplied
    )
    frame["overdue_hours"] = ((cutoff - frame["planned_delivery"]).dt.total_seconds() / 3600).where(frame["is_overdue"])
    _assess_costs(frame)

    issue_frame = pd.DataFrame(issues, columns=ISSUE_COLUMNS)
    issue_codes = issue_frame.groupby("source_row")["code"].agg(lambda values: "; ".join(values))
    frame["data_quality_issues"] = frame["source_row"].map(issue_codes).fillna("")
    frame["has_data_quality_issue"] = frame["data_quality_issues"].ne("")
    frame["exception_types"] = [
        "; ".join(label for flag, label in (
            (late, "Delayed delivery"), (overdue, "Overdue in transit"),
            (cost_flag, "High cost"), (quality, "Data quality"),
        ) if flag)
        for late, overdue, cost_flag, quality in zip(
            frame["is_delayed"], frame["is_overdue"], frame["is_cost_anomaly"], frame["has_data_quality_issue"],
        )
    ]
    frame["is_exception"] = frame["exception_types"].ne("")
    return AnalysisResult(frame, issue_frame, day.date(), cutoff)


def _assess_costs(frame: pd.DataFrame) -> None:
    """Upper-only robust threshold; use a 50% median margin when MAD is small.

    Threshold = median + max(3.5 * 1.4826 * MAD, 0.5 * median).
    Comparisons use exact mode and case-insensitive directional location labels.
    """
    frame["cost_assessment"] = "Insufficient data"
    frame.loc[~frame["valid_cost"], "cost_assessment"] = "Invalid cost"
    frame.loc[~frame["included_in_analysis"], "cost_assessment"] = "Excluded row"
    frame["cost_group_size"] = 0
    frame["cost_group_median"] = float("nan")
    frame["cost_threshold"] = float("nan")
    frame["is_cost_anomaly"] = False
    comparable = frame["included_in_analysis"] & frame["valid_cost"]
    for column in ("origin", "destination", "transport_mode"):
        comparable &= frame[column].str.casefold().ne("unknown")
    subset = frame.loc[comparable].copy()
    keys = [subset[column].str.casefold() for column in ("transport_mode", "origin", "destination")]
    groups = subset.groupby(keys, dropna=False)["shipping_cost"]
    counts = groups.transform("size")
    median = groups.transform("median")
    mad = groups.transform(lambda values: (values - values.median()).abs().median())
    margin = pd.concat([3.5 * 1.4826 * mad, 0.5 * median], axis=1).max(axis=1)
    threshold = median + margin
    frame.loc[subset.index, "cost_group_size"] = counts
    enough = counts.ge(MIN_COST_GROUP_SIZE)
    assessed = subset.index[enough]
    frame.loc[assessed, "cost_group_median"] = median.loc[assessed]
    frame.loc[assessed, "cost_threshold"] = threshold.loc[assessed]
    frame.loc[assessed, "cost_assessment"] = "Within range"
    high = assessed[subset.loc[assessed, "shipping_cost"].gt(threshold.loc[assessed])]
    frame.loc[high, "is_cost_anomaly"] = True
    frame.loc[high, "cost_assessment"] = "High cost"


def calculate_kpis(shipments: pd.DataFrame) -> dict[str, int | float | None]:
    """Aggregate precomputed flags; filtering must never refit the cost thresholds."""
    included = shipments.loc[shipments["included_in_analysis"]]
    eligible = int(included["delivery_eligible"].sum())
    delayed = included.loc[included["is_delayed"], "delay_hours"]
    valid_cost = included["valid_cost"]
    return {
        "total_shipments": len(included),
        "delivered_shipments": int(included["is_delivered"].sum()),
        "eligible_deliveries": eligible,
        "on_time_shipments": int(included["is_on_time"].sum()),
        "delayed_shipments": len(delayed),
        "on_time_delivery_rate": float(included["is_on_time"].sum() / eligible) if eligible else None,
        "average_delay_hours": float(delayed.mean()) if len(delayed) else (0.0 if eligible else None),
        "overdue_shipments": int(included["is_overdue"].sum()),
        "total_shipping_cost": float(included.loc[valid_cost, "shipping_cost"].sum()),
        "cost_eligible_shipments": int(valid_cost.sum()),
        "cost_anomalies": int(included["is_cost_anomaly"].sum()),
        "cost_insufficient_shipments": int(included["cost_assessment"].eq("Insufficient data").sum()),
        "source_rows": len(shipments),
        "excluded_rows": int((~shipments["included_in_analysis"]).sum()),
        "quality_rows": int(shipments["has_data_quality_issue"].sum()),
    }


def carrier_performance(shipments: pd.DataFrame) -> pd.DataFrame:
    records = []
    included = shipments.loc[shipments["included_in_analysis"]]
    for carrier, group in included.groupby("carrier", sort=True):
        kpis = calculate_kpis(group)
        records.append({
            "carrier": carrier, "shipments": kpis["total_shipments"],
            "delivered_shipments": kpis["delivered_shipments"],
            "eligible_deliveries": kpis["eligible_deliveries"],
            "on_time_shipments": kpis["on_time_shipments"],
            "on_time_rate_pct": 100 * kpis["on_time_delivery_rate"] if kpis["on_time_delivery_rate"] is not None else None,
        })
    return pd.DataFrame(records, columns=["carrier", "shipments", "delivered_shipments", "eligible_deliveries", "on_time_shipments", "on_time_rate_pct"])


def exception_shipments(shipments: pd.DataFrame) -> pd.DataFrame:
    return shipments.loc[shipments["is_exception"]].copy()
