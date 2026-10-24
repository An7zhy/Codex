"""V2 Streamlit views. Scoring, scenarios, storage and evaluation remain separate."""

from dataclasses import replace
import json
import os
from pathlib import Path
import sqlite3

import pandas as pd
import streamlit as st

from src.decisions import ACTIONS, ActionAssumption, compare_actions, default_assumptions
from src.evaluation import run_evaluation
from src.exports import csv_bytes
from src.history import CaseInput, HistoryStore, RESOLUTION_STATUSES
from src.priority import COMPONENTS, PriorityConfig, active_exception, delivery_deadline, prioritize_shipments

ROOT = Path(__file__).resolve().parents[1]
HISTORY_COLUMNS = ["case_id", "shipment_id", "exception_type", "selected_action", "estimated_cost", "actual_cost",
                   "estimated_delay", "actual_delay", "resolution_status", "resolution_notes", "created_at", "updated_at"]


def history_store() -> HistoryStore:
    return HistoryStore(os.environ.get("LOGISTICS_DB_PATH", str(ROOT / "data" / "local" / "exception_history.sqlite3")))


def render_priority_queue(view: pd.DataFrame, cutoff: pd.Timestamp):
    st.subheader("Explainable exception priority")
    st.caption("Triage active In Transit exceptions. Completed, unidentified and conflicting records remain in separate review lanes. No predictive or realized-loss claim is made.")
    try:
        base = PriorityConfig.load()
        with st.expander("Configure priority rules"):
            st.write("Weights are normalized by their positive sum. A zero weight disables a component. Required enabled inputs must all be valid for a complete score.")
            columns = st.columns(5)
            weights = {key: column.number_input(key.capitalize() + " weight", min_value=0.0,
                                                value=float(base.weights[key]), step=5.0, key="weight_" + key)
                       for key, column in zip(COMPONENTS, columns)}
            columns = st.columns(3)
            urgency_window = columns[0].number_input("Urgency window (hours)", min_value=0.0, value=float(base.urgency_window_hours))
            delay_scale = columns[1].number_input("Delay full-scale (hours)", min_value=0.0, value=float(base.delay_scale_hours))
            medium = columns[2].number_input("Medium priority threshold", 0.0, 100.0, float(base.medium_threshold))
            columns = st.columns(3)
            financial_scale = columns[0].number_input("Financial full-scale (USD)", min_value=0.0, value=float(base.financial_scale_usd))
            value_scale = columns[1].number_input("Value full-scale (USD)", min_value=0.0, value=float(base.value_scale_usd))
            dependency_scale = columns[2].number_input("Dependency full-scale (count)", min_value=0.0, value=float(base.dependency_scale))
            high = st.number_input("High priority threshold", 0.0, 100.0, float(base.high_threshold))
            settings = replace(base, weights=weights, urgency_window_hours=urgency_window,
                               delay_scale_hours=delay_scale, financial_scale_usd=financial_scale,
                               value_scale_usd=value_scale, dependency_scale=dependency_scale,
                               medium_threshold=medium, high_threshold=high)
            st.download_button("Priority settings JSON", json.dumps(settings.to_dict(), indent=2),
                               "priority_rules.json", "application/json", on_click="ignore")
    except (OSError, ValueError, TypeError) as exc:
        st.error(f"Priority settings need correction: {exc}")
        return None, None
    priorities = prioritize_shipments(view, cutoff, settings)
    complete = priorities.dropna(subset=["priority_score"]).sort_values(["priority_score", "shipment_id"], ascending=[False, True])
    missing = priorities.loc[priorities["priority_level"].eq("Insufficient information")]
    columns = ["shipment_id", "exception_types", "priority_score", "priority_level", "explanation", "missing_information"]
    st.write(f"{len(complete)} fully scored active exceptions; {len(missing)} require additional information.")
    if complete.empty:
        st.info("No fully scored active exceptions. V1-only uploads need the optional decision-context fields described in README.")
    else:
        st.dataframe(complete[columns], hide_index=True, width="stretch")
    st.subheader("Information needed before ranking")
    st.caption("Incomplete records are not assigned Low priority. Bounds show only possible weighted score range, not a risk prediction or a ranking.")
    st.dataframe(missing[["shipment_id", "priority_level", "coverage_percent", "priority_lower_bound", "priority_upper_bound", "missing_information"]], hide_index=True, width="stretch")
    with st.expander("Retrospective and excluded records"):
        review = priorities.loc[~priorities.index.isin(complete.index) & ~priorities.index.isin(missing.index)]
        st.dataframe(review[columns], hide_index=True, width="stretch")
    if not priorities.empty:
        source_row = st.selectbox("Explain a priority record", priorities["source_row"].tolist(),
                                 format_func=lambda value: f"Row {value}: {priorities.loc[priorities['source_row'].eq(value), 'shipment_id'].iloc[0] or '(missing ID)'}")
        chosen = priorities.loc[priorities["source_row"].eq(source_row)].iloc[0]
        st.write(chosen["explanation"])
        st.json(json.loads(chosen["priority_details_json"]), expanded=False)
    st.download_button("Priority queue CSV", csv_bytes(priorities), "priority_queue.csv", "text/csv", on_click="ignore")
    return priorities, settings


def render_decision_center(priorities: pd.DataFrame | None, cutoff: pd.Timestamp, source_label: str):
    st.subheader("Decision Center")
    st.warning("Simulation only. Costs, remaining transit time and availability below are editable assumptions, not live quotes, ETA predictions or carrier commitments.")
    if priorities is None:
        st.info("Correct the priority settings to continue.")
        return
    active = priorities.loc[[active_exception(row) for row in priorities.to_dict("records")]] if not priorities.empty else priorities
    if active.empty:
        st.info("No active In Transit exception in this selection. Completed shipments remain available in V1 and case history.")
        return
    active = active.sort_values("priority_score", ascending=False, na_position="last")
    source_row = st.selectbox("Shipment for decision review", active["source_row"].tolist(),
                             format_func=lambda value: str(active.loc[active["source_row"].eq(value), "shipment_id"].iloc[0]))
    row = active.loc[active["source_row"].eq(source_row)].iloc[0]
    shipment_id = str(row["shipment_id"])
    deadline, deadline_source = delivery_deadline(row)
    st.write(f"Priority: {row['priority_level']}. Score: {'Insufficient information' if pd.isna(row['priority_score']) else format(row['priority_score'], '.1f')}.")
    if row["missing_information"]:
        st.info("Missing information: " + row["missing_information"])
    st.caption(f"Scenario starts at {cutoff.isoformat()}. Deadline source: {deadline_source}. "
               f"Deadline: {deadline.isoformat() if deadline is not None else 'Insufficient information'}. Historical overdue age is not a remaining-time estimate.")
    options = []
    for index, (column, option) in enumerate(zip(st.columns(3), default_assumptions())):
        with column:
            st.markdown("**" + option.action + "**")
            prefix = f"scenario_{shipment_id}_{index}"
            cost = st.number_input("Additional cost (USD)", 0.0, 1_000_000_000.0, option.additional_cost, step=50.0, key=prefix + "_cost")
            hours = st.number_input("Remaining time (hours)", 0.0, 87600.0, option.remaining_hours, step=4.0, key=prefix + "_hours")
            available = st.checkbox("Assume available in scenario", value=True, key=prefix + "_available")
            notes = st.text_input("Key assumptions", value=option.notes, key=prefix + "_notes")
            try:
                options.append(ActionAssumption(option.action, cost, hours, available, notes))
            except ValueError as exc:
                st.error(str(exc))
    if len(options) != 3:
        return
    try:
        comparison = compare_actions(cutoff, deadline, options)
    except ValueError as exc:
        st.error(str(exc))
        return
    st.dataframe(comparison.drop(columns=["assumptions_json"]), hide_index=True, width="stretch")
    st.caption("Estimated delay is lateness against the selected deadline in this scenario. All cost figures are incremental USD. No action is automatically selected or booked.")
    st.download_button("Scenario comparison CSV", csv_bytes(comparison), "scenario_comparison.csv", "text/csv", on_click="ignore")
    types = row["exception_types"].split("; ")
    exception_type = st.selectbox("Exception type for case history", types, key="case_exception_" + shipment_id)
    available_actions = comparison.loc[comparison["assumed_available"], "action"].tolist()
    if available_actions:
        with st.form("save_case_" + shipment_id):
            selected = st.selectbox("Selected action", available_actions)
            notes = st.text_area("Decision notes", max_chars=4000)
            submitted = st.form_submit_button("Save decision to local history")
        if submitted:
            chosen = comparison.loc[comparison["action"].eq(selected)].iloc[0]
            snapshot = {"priority_score": None if pd.isna(row["priority_score"]) else float(row["priority_score"]),
                        "priority_level": row["priority_level"], "details": json.loads(row["priority_details_json"]), "source": source_label}
            assumptions = {"comparison": json.loads(comparison.to_json(orient="records")), "analysis_cutoff": cutoff.isoformat(),
                           "deadline": deadline.isoformat() if deadline is not None else None,
                           "provenance": "User-editable simulation assumptions, not a carrier offer."}
            try:
                case_id = history_store().create_case(CaseInput(
                    shipment_id, exception_type, selected,
                    estimated_cost=float(chosen["estimated_additional_cost_usd"]),
                    estimated_delay=None if pd.isna(chosen["estimated_delay_hours"]) else float(chosen["estimated_delay_hours"]),
                    resolution_notes=notes, origin=row["origin"], destination=row["destination"],
                    transport_mode=row["transport_mode"], carrier=row["carrier"],
                    assumptions_json=json.dumps(assumptions, allow_nan=False),
                    priority_snapshot_json=json.dumps(snapshot, allow_nan=False), analysis_date=str(cutoff.date()),
                ))
                st.success("Decision saved locally. Case ID: " + case_id + ". Actual cost and actual delay remain unknown until entered.")
            except (sqlite3.Error, OSError, ValueError) as exc:
                st.error(f"Could not save case history: {exc}. V1 analysis is still available.")
    else:
        st.info("All three actions are unavailable in this scenario; no action can be saved.")
    st.subheader("Past similar cases")
    st.caption("Exact directional route, mode and exception-type match; excludes this shipment. Matching records are not a validated recommendation or a predicted outcome.")
    try:
        similar = history_store().similar_cases(row["origin"], row["destination"], row["transport_mode"], exception_type, shipment_id)
        if similar.empty:
            st.info("No comparable local cases found, or route/mode information is incomplete.")
        else:
            st.dataframe(similar[HISTORY_COLUMNS + ["match_reason"]], hide_index=True, width="stretch")
    except (sqlite3.Error, OSError) as exc:
        st.warning(f"Local history is unavailable: {exc}. Scenario analysis remains usable.")


def render_case_history():
    st.subheader("Local exception handling history")
    st.caption("SQLite persists records across app restarts on this computer. These filters are independent of dashboard filters. Unknown actual outcomes remain blank, never zero-filled.")
    if notice := st.session_state.pop("history_update_notice", None):
        st.success(notice)
    shipment_filter = st.text_input("History shipment ID (exact)", key="history_shipment_filter").strip()
    columns = st.columns(2)
    status = columns[0].selectbox("Resolution status filter", ["All"] + list(RESOLUTION_STATUSES))
    exception_filter = columns[1].text_input("History exception type (exact)").strip()
    try:
        store = history_store()
        cases = store.list_cases(shipment_filter or None, None if status == "All" else status, exception_filter or None)
        st.caption("Showing at most 200 matching cases, newest first. Database: " + str(store.path))
        if cases.empty:
            st.info("No saved cases match these filters. Choose and save a simulated action in Decision Center to create a record.")
            return
        st.dataframe(cases[HISTORY_COLUMNS], hide_index=True, width="stretch")
        st.download_button("Case history CSV", csv_bytes(cases), "case_history.csv", "text/csv", on_click="ignore")
        selected = st.selectbox("Case to update", cases["case_id"].tolist(),
                                format_func=lambda value: f"{value[:8]} — {cases.loc[cases['case_id'].eq(value), 'shipment_id'].iloc[0]}")
        current = store.get_case(selected)
        with st.expander("Saved assumptions and priority snapshot"):
            st.json(json.loads(current["assumptions_json"]), expanded=False)
            st.json(json.loads(current["priority_snapshot_json"]), expanded=False)
        with st.form(f"update_case_{selected}_{current['version']}"):
            resolution = st.selectbox("Update resolution status", list(RESOLUTION_STATUSES), index=RESOLUTION_STATUSES.index(current["resolution_status"]))
            columns = st.columns(2)
            actual_cost = columns[0].number_input("Actual additional cost (USD, optional)", min_value=0.0, max_value=1_000_000_000.0, value=current["actual_cost"])
            actual_delay = columns[1].number_input("Actual delay (hours, optional)", min_value=0.0, max_value=1_000_000_000.0, value=current["actual_delay"])
            notes = st.text_area("Resolution notes", value=current["resolution_notes"], max_chars=4000)
            st.caption(f"Editing case {selected}, version {current['version']}.")
            submitted = st.form_submit_button("Update saved case")
        if submitted:
            store.update_case(selected, resolution, actual_cost, actual_delay, notes, expected_version=current["version"])
            st.session_state["history_update_notice"] = "Case updated locally: " + selected
            st.rerun()
    except (sqlite3.Error, OSError, ValueError, LookupError) as exc:
        st.warning(f"Local history needs attention: {exc}. V1 analysis remains available.")


def render_evaluation(settings: PriorityConfig | None):
    st.subheader("Reproducible V1 / V2 comparison")
    st.write("Nine hand-authored synthetic cases include four independent ordinal reference priorities, missing/invalid context, a normal record, a completed record and an unidentified record.")
    st.warning("Agreement with these teaching cases is not predictive accuracy. References are not generated by the scoring formula and have not been validated by real logistics operators.")
    if settings is None:
        st.info("Correct the priority settings before running the comparison.")
        return
    if st.button("Run synthetic comparison"):
        result = run_evaluation(settings)
        st.json(result.summary)
        st.subheader("V1 detection versus V2 triage")
        st.dataframe(result.comparison, hide_index=True, width="stretch")
        st.subheader("Weight sensitivity")
        st.dataframe(result.weight_sensitivity, hide_index=True, width="stretch")
        st.subheader("Scenario assumption sensitivity")
        st.dataframe(result.action_sensitivity.drop(columns=["assumptions_json"]), hide_index=True, width="stretch")
        st.download_button("Evaluation JSON", result.json_bytes(), "synthetic_evaluation.json", "application/json", on_click="ignore")
