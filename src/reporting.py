"""English reports derived only from calculated data. No API key required."""

from datetime import date
import html
from typing import Protocol

import pandas as pd

from src.analysis import calculate_kpis, carrier_performance, exception_shipments
from src.schema import KPI_DEFINITIONS


class ReportGenerator(Protocol):
    """An optional future AI adapter can implement this without changing the UI."""

    def generate(self, shipments: pd.DataFrame, issues: pd.DataFrame, as_of: date,
                 source_label: str, scope: str) -> str: ...


def _text(value: object) -> str:
    text = html.escape(str(value)).replace("\n", " ").replace("\r", " ")
    for character in ("\\", "|", "`", "[", "]", "*", "_"):
        text = text.replace(character, "\\" + character)
    return text


def _rate(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.1%}"


class RuleBasedReportGenerator:
    def generate(self, shipments: pd.DataFrame, issues: pd.DataFrame, as_of: date,
                 source_label: str = "Uploaded data", scope: str = "All records") -> str:
        k = calculate_kpis(shipments)
        delay = "N/A" if k["average_delay_hours"] is None else f"{k['average_delay_hours']:.1f} h"
        lines = [
            "# Logistics Insight AI — Operations Report", "",
            f"**Data source:** {_text(source_label)}  ",
            f"**Analysis date:** {as_of.isoformat()} (inclusive UTC day)  ",
            f"**Scope:** {_text(scope)}", "",
            "## Executive Summary", "",
            f"This selection contains **{k['total_shipments']} unique identified shipments** from "
            f"{k['source_rows']} source rows. There are {k['delivered_shipments']} verified delivered shipments, "
            f"{k['delayed_shipments']} completed late deliveries and {k['overdue_shipments']} overdue in-transit shipments.",
            f"On-time delivery is **{_rate(k['on_time_delivery_rate'])}**, based on {k['eligible_deliveries']} "
            f"deliveries with valid time comparisons. {k['cost_anomalies']} high-cost shipments were identified.",
            "No root cause is inferred from order-level dates, status or cost alone.", "",
            "## Operational KPIs", "",
            "| KPI | Value |", "| --- | ---: |",
            f"| Total Shipments | {k['total_shipments']} |",
            f"| Delivered Shipments | {k['delivered_shipments']} |",
            f"| On-Time Delivery Rate | {_rate(k['on_time_delivery_rate'])} |",
            f"| Average Delay Hours (late deliveries only) | {delay} |",
            f"| Overdue Shipments | {k['overdue_shipments']} |",
            f"| Total Shipping Cost (USD) | {k['total_shipping_cost']:,.2f} |",
            f"| Cost Anomalies | {k['cost_anomalies']} |", "",
            f"Cost totals use {k['cost_eligible_shipments']} valid costs. Missing or invalid costs are not zero-cost shipments. "
            f"{k['cost_insufficient_shipments']} shipments have insufficient comparable cost data.", "",
            "### Metric definitions", "",
        ]
        lines.extend(f"- **{name}:** {definition}" for name, definition in KPI_DEFINITIONS.items())
        lines += ["", "## Key Exceptions", "",
                  "Rows may have more than one exception. Completed delays and overdue in-transit shipments are separate.", ""]
        exceptions = exception_shipments(shipments)
        if exceptions.empty:
            lines.append("No exceptions were detected by the configured rules in this selection.")
        else:
            lines += [f"{len(exceptions)} source rows have an exception or a data quality issue. First {min(15, len(exceptions))} rows are shown; download the exceptions CSV for the complete list.", "",
                      "| Source row | Shipment | Exceptions | Delay hours |",
                      "| ---: | --- | --- | ---: |"]
            for row in exceptions.head(15).itertuples():
                hours = "N/A" if pd.isna(row.delay_hours) else f"{row.delay_hours:.1f}"
                lines.append(f"| {row.source_row} | {_text(row.shipment_id or '(missing ID)')} | {_text(row.exception_types)} | {hours} |")
        lines += ["", "## Carrier Performance", "",
                  "Rates use each carrier's eligible completed deliveries; N/A means there is no valid denominator.", "",
                  "| Carrier | Shipments | Verified delivered | Eligible deliveries | On-time rate |",
                  "| --- | ---: | ---: | ---: | ---: |"]
        carriers = carrier_performance(shipments)
        for row in carriers.itertuples():
            rate = "N/A" if pd.isna(row.on_time_rate_pct) else f"{row.on_time_rate_pct:.1f}%"
            lines.append(f"| {_text(row.carrier)} | {row.shipments} | {row.delivered_shipments} | {row.eligible_deliveries} | {rate} |")
        if carriers.empty:
            lines.append("| No retained shipments | 0 | 0 | 0 | N/A |")
        # Scope the issue list by source row even if the caller passes all issues.
        scoped_issues = issues.loc[issues["source_row"].isin(shipments["source_row"])]
        lines += ["", "## Data Quality Issues", "",
                  f"{k['quality_rows']} source rows have {len(scoped_issues)} quality findings. "
                  f"{k['excluded_rows']} rows are excluded from shipment KPIs because their IDs are missing or repeated.", ""]
        if scoped_issues.empty:
            lines.append("No data quality issues were detected.")
        else:
            lines += ["| Finding | Count |", "| --- | ---: |"]
            for code, count in scoped_issues["code"].value_counts().items():
                lines.append(f"| {_text(code)} | {count} |")
        lines += ["", "## Recommended Next Actions", ""]
        actions = []
        if k["quality_rows"]:
            actions.append("Review the data quality queue, resolve repeated or missing IDs, and correct invalid dates and costs before relying on affected metrics.")
        if k["overdue_shipments"]:
            actions.append("Prioritize overdue in-transit shipments for a manual status check with the carrier; obtain current milestones and a revised ETA.")
        if k["delayed_shipments"]:
            actions.append("Review completed late deliveries by route and carrier. Request milestone evidence before assigning a root cause.")
        if k["cost_anomalies"]:
            actions.append("Check high-cost records against invoices, shipment weight, service level and surcharges before treating them as billing errors.")
        if k["cost_insufficient_shipments"]:
            actions.append("Collect more comparable costs for groups marked Insufficient data; do not interpret them as normal or anomalous yet.")
        if not actions:
            actions.append("Continue monitoring against the same definitions and verify any new exceptions with source records.")
        lines.extend(f"{index}. {action}" for index, action in enumerate(actions, 1))
        lines += ["", "## Method and Limitations", "",
                  "- High cost is strictly above median + max(3.5 × 1.4826 × MAD, 0.5 × median), with at least 8 valid costs per mode and directional route. Thresholds are fixed on the full input before UI filters.",
                  "- All costs are assumed USD. The MVP does not normalize weight, currency, service level or seasonality. The cost rule is a screening heuristic, not proof of overcharging.",
                  "- ISO dates without offsets are UTC. Date-only deliveries occur at 00:00 UTC; the selected analysis day ends at 23:59:59.999999999 UTC.",
                  "- Statuses describe the uploaded snapshot. Changing the analysis date does not reconstruct historical status or historical cost.",
                  "- Without optional shipped_at, chronology checks are limited to valid dates since 2000-01-01 and the analysis cutoff. Early delivery relative to the plan is valid.",
                  "- This report is generated by deterministic Python rules. Synthetic Demo Data is fictional and cannot establish real-world accuracy.", ""]
        return "\n".join(lines)
