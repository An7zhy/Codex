"""Adapt confirmed records to the ORIGINAL CP-SAT allocation/strategy functions."""

from datetime import datetime, timedelta
from importlib.metadata import version
import json

from .engine import single_order_recommendations
from .experiments import compare_strategies, experiment_json
from .models import Candidate, Constraints, Order, PlanningData, Preferences, Service


def run_uploaded(payload):
    data = PlanningData(tuple(Order(**row) for row in payload["data"]["orders"]),
                        tuple(Service(**row) for row in payload["data"]["services"]),
                        tuple(Candidate(**row) for row in payload["data"]["candidates"]))
    constraints, preferences = Constraints(**payload["constraints"]), Preferences(**payload["preferences"])
    if len(data.orders) > 500 or len(data.services) > 100 or len(data.candidates) > 5000 or preferences.risk != 0:
        raise ValueError("Uploaded planning limits or reliability policy violated.")
    experiment = compare_strategies(data, constraints, preferences, simulate=False, seed=0)
    result = json.loads(experiment_json(experiment))
    result.update(schema="logistics-insight-uploaded-run-1", input_mode="uploaded",
                  solver_backend="Original V3 Google OR-Tools CP-SAT", ortools_version=version("ortools"),
                  provenance=("Synthetic template data uploaded by user" if payload["data_kind"] == "synthetic_test" else "User-provided planning data; independent verification not performed"),
                  source_info={key: payload[key] for key in ("source_label", "data_kind", "planning_start", "declarations", "policy", "reliability")},
                  request=dict(count=len(data.orders), cost_weight=preferences.cost, time_weight=preferences.time,
                               risk_weight=0, time_limit_seconds=constraints.time_limit_seconds),
                  simulation_details={}, candidate_checks=json.loads(experiment.results["Optimized Allocation"].candidates.to_json(orient="records")),
                  local_recommendations=json.loads(single_order_recommendations(experiment.results["Optimized Allocation"].candidates).to_json(orient="records")))
    # Remove internal deterministic placeholders from every public/exported table.
    start = datetime.fromisoformat(payload["planning_start"])
    tables = payload.get("input_tables", {})
    quotes = {(row["shipment_id"], row["service_id"]): row for row in tables.get("transport_options", [])}
    capacities = {row["service_id"]: row for row in tables.get("capacity", [])}
    def annotate(rows):
        for row in rows:
            row.update(input_source=payload["source_label"], data_kind=payload["data_kind"],
                       reliability_status="Not estimated; no historical distribution", planning_start_utc=payload["planning_start"],
                       currency="USD", weight_unit="kg", volume_unit="m3", time_unit="h")
            quote = quotes.get((row["shipment_id"], row["service_id"]), {})
            capacity = capacities.get(row["service_id"], {})
            for field in ("quote_status", "quote_reference", "time_status", "time_reference"):
                row[field] = quote.get(field, "Not supplied")
            for field in ("capacity_status", "capacity_reference"):
                row[field] = capacity.get(field, "Not supplied")
            if "expected_hours" in row:
                try:
                    row["estimated_arrival_utc"] = (start + timedelta(hours=row["expected_hours"])).isoformat()
                except OverflowError:
                    row["estimated_arrival_utc"] = None  # Ineligible candidate beyond representable dates.
            if "deadline_hours" in row:
                row["delivery_deadline_utc"] = (start + timedelta(hours=row["deadline_hours"])).isoformat()
            for key in ("assumed_late_probability", "std_hours"):
                if key in row: row[key] = None
    annotate(result["candidate_checks"])
    for allocation in result["results"].values():
        annotate(allocation["assignments"])
    for row in result["summary"]:
        row.update(input_mode="uploaded", input_source=payload["source_label"], data_kind=payload["data_kind"],
                   reliability_status="Not estimated; deterministic cost/time optimization only")
    # Raw input records, not a made-up transport distribution, are the replay source.
    result["data"]["services"] = [{key: val for key, val in row.items() if key != "std_hours"} for row in result["data"]["services"]]
    return result
