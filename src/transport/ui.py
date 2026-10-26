"""V3 presentation only. Input forms commit together; displayed runs are immutable snapshots."""

from dataclasses import asdict

import pandas as pd
import plotly.express as px
import streamlit as st

from src.exports import csv_bytes
from .demo import adjust_planning, demo_budget, generate_planning_demo
from .engine import STRATEGIES, single_order_recommendations
from .experiments import compare_strategies, experiment_json
from .models import Constraints, Preferences


def render_transportation():
    st.header("V3 Transportation Optimization")
    st.warning("Synthetic Demo Data — fictional international orders, services, prices, capacities and transit distributions. No live quotes, bookings, carrier on-time records or validated predictions.")
    st.caption("This planning sandbox is independent of V1/V2 uploads and saved cases. All times are elapsed hours from a common hypothetical dispatch at hour 0; costs are USD.")
    with st.expander("Planning inputs and what-if controls", expanded=True):
        st.write("Edit assumptions, then click Run transportation optimization. Draft changes do not alter the last applied result.")
        with st.form("v3_planning_form"):
            left, middle, right = st.columns(3)
            with left:
                count = st.selectbox("Synthetic planning orders", [12, 100, 500, 0], key="v3_count")
                data_seed = st.number_input("Planning data seed", 0, 2**32 - 1, 42, key="v3_data_seed")
                budget_percent = st.number_input("Budget (% of all-most-expensive synthetic options)", 0.0, 150.0, 100.0, step=5.0, key="v3_budget_percent")
                deadline_shift = st.number_input("Deadline shift (hours)", -400.0, 400.0, 0.0, step=12.0, key="v3_deadline_shift")
            with middle:
                weight_capacity = st.number_input("Weight capacity (%)", 0.0, 200.0, 100.0, step=10.0, key="v3_weight_capacity")
                volume_capacity = st.number_input("Volume capacity (%)", 0.0, 200.0, 100.0, step=10.0, key="v3_volume_capacity")
                slots = st.number_input("Shipment slots (%)", 0.0, 200.0, 100.0, step=10.0, key="v3_slot_capacity")
                allow_unassigned = st.checkbox("Allow unassigned orders with penalty", key="v3_allow_unassigned")
                penalty = st.number_input("Unassigned penalty (virtual USD per order)", 0.0, 1_000_000.0, 100_000.0, step=1000.0, key="v3_penalty")
            with right:
                cost = st.number_input("Optimization cost weight", 0.0, 100.0, 30.0, key="v3_cost_weight")
                transit = st.number_input("Optimization time weight", 0.0, 100.0, 30.0, key="v3_time_weight")
                risk = st.number_input("Optimization simulated risk weight", 0.0, 100.0, 40.0, key="v3_risk_weight")
                scenario_count = st.number_input("Monte Carlo scenarios", 100, 10_000, 2000, step=100, key="v3_mc_count")
                seed = st.number_input("Monte Carlo seed", 0, 2**32 - 1, 2026, key="v3_mc_seed")
                time_limit = st.number_input("Solver limit per strategy (seconds)", 0.1, 10.0, 5.0, step=0.5, key="v3_time_limit")
            run = st.form_submit_button("Run transportation optimization", type="primary")
    if run:
        try:
            preferences = Preferences(cost, transit, risk)
            base = generate_planning_demo(count, data_seed)
            data = adjust_planning(base, deadline_shift_hours=deadline_shift,
                                   weight_capacity_factor=weight_capacity / 100,
                                   volume_capacity_factor=volume_capacity / 100,
                                   shipment_capacity_factor=slots / 100)
            constraints = Constraints(round(demo_budget(base) * budget_percent / 100, 2),
                                      allow_unassigned, penalty, time_limit)
            with st.spinner("Solving three constrained strategies and evaluating common random scenarios..."):
                experiment = compare_strategies(data, constraints, preferences,
                                                scenario_count=scenario_count, seed=seed)
            previous = st.session_state.get("v3_experiment")
            st.session_state["v3_previous_experiment"] = previous
            st.session_state["v3_experiment"] = experiment
            st.success("Transportation assumptions applied. Results below use this completed run.")
        except (ValueError, RuntimeError) as exc:
            st.error(str(exc))
            st.info("The invalid draft was not applied. Any result below belongs to the previous applied run.")
    experiment = st.session_state.get("v3_experiment")
    if experiment is None:
        st.info("Click Run transportation optimization to start the reproducible 12-order demo. For shortages, try 0% budget or 0% capacity, then run again.")
        return
    preferences, constraints, data = experiment.preferences, experiment.constraints, experiment.data
    wc, wt, wr = preferences.normalized()
    st.caption(f"Applied run: {len(data.orders)} orders | Budget USD {constraints.budget_usd:,.2f} | "
               f"Normalized weights cost {wc:.1%}, time {wt:.1%}, simulated risk {wr:.1%} | "
               f"Monte Carlo seed {experiment.seed}, {experiment.scenario_count} scenarios.")
    st.caption("Hard constraints: exact directional route; expected arrival within deadline; shared service weight, volume and shipment slots; total shipping budget. Weights only rank eligible allocations. Hard deadlines use expected time, not a guarantee under random variability.")
    decision, dashboard, comparison, whatif = st.tabs([
        "Transportation Decision Center", "Optimization Dashboard", "Strategy Comparison", "What-if Scenario Analysis"])
    with decision:
        _decision_view(experiment)
    with dashboard:
        _dashboard_view(experiment)
    with comparison:
        _comparison_view(experiment)
    with whatif:
        _whatif_view(experiment, st.session_state.get("v3_previous_experiment"))


def _decision_view(experiment):
    st.subheader("Single-order hard eligibility and local recommendations")
    if not experiment.data.orders:
        st.info("Empty planning scenario: no shipment to select.")
        return
    ids = sorted(order.shipment_id for order in experiment.data.orders)
    if st.session_state.get("v3_selected_order") not in ids:
        st.session_state["v3_selected_order"] = ids[0]
    selected = st.selectbox("Planning shipment", ids, key="v3_selected_order")
    order = next(order for order in experiment.data.orders if order.shipment_id == selected)
    st.write(f"{order.origin} → {order.destination} | {order.weight_kg:g} kg | {order.volume_m3:g} m³ | deadline {order.deadline_hours:g} h")
    table = experiment.results[STRATEGIES[2]].candidates
    choices = table.loc[table.shipment_id.eq(selected)]
    st.dataframe(choices, hide_index=True, width="stretch")
    recommendations = single_order_recommendations(choices)
    st.dataframe(recommendations, hide_index=True, width="stretch")
    st.caption("Local recommendations do not reserve shared capacity. Only the batch allocation below confirms whether the complete order set is feasible. Simulated late probability is a lognormal assumption, not a real carrier on-time rate.")


def _dashboard_view(experiment):
    st.subheader("Shared-capacity allocation")
    result = experiment.results[STRATEGIES[2]]
    if result.status == "OPTIMAL":
        st.success("OPTIMAL — minimum proved for the integer-rounded model and the applied assumptions.")
    elif result.status == "FEASIBLE":
        st.warning("FEASIBLE — a valid assignment was found; optimality was not proved.")
    else:
        st.error(f"{result.status} — no actionable allocation returned.")
    for message in result.diagnostics:
        st.warning(message)
    if not result.has_solution:
        st.info("No shipping cost, utilization or simulated benefit is reported for an unsuccessful solve. Check candidate rejection reasons and shared resource limits.")
    else:
        a, b, c, d = st.columns(4)
        a.metric("V3 Assigned orders", len(result.assignments))
        b.metric("V3 Unassigned orders", len(result.unassigned_ids))
        c.metric("V3 Shipping cost", f"${result.assignments.cost_usd.sum():,.2f}")
        d.metric("V3 Allocation time", f"{result.elapsed_seconds:.3f} s")
        if result.unassigned_ids:
            st.warning("Unassigned orders: " + ", ".join(result.unassigned_ids))
        st.dataframe(result.assignments, hide_index=True, width="stretch")
        st.dataframe(result.capacity, hide_index=True, width="stretch")
        if not result.capacity.empty:
            chart = result.capacity.melt("service_id", ["weight_utilization", "volume_utilization", "slot_utilization"],
                                          var_name="Resource", value_name="Utilization")
            st.plotly_chart(px.bar(chart, x="service_id", y="Utilization", color="Resource", barmode="group"), use_container_width=True)
        st.caption(f"Integer objective: {result.objective_value}; lower bound: {result.best_bound}. Objectives differ between strategies and are not comparable business costs.")
    st.download_button("V3 allocation CSV", csv_bytes(result.assignments), "v3_allocation.csv", "text/csv", on_click="ignore")
    st.download_button("V3 candidate checks CSV", csv_bytes(result.candidates), "v3_candidate_checks.csv", "text/csv", on_click="ignore")
    with st.expander("Synthetic planning inputs"):
        st.dataframe(pd.DataFrame([asdict(order) for order in experiment.data.orders]), hide_index=True)
        st.dataframe(pd.DataFrame([asdict(service) for service in experiment.data.services]), hide_index=True)


def _comparison_view(experiment):
    st.subheader("Identical constraints and common Monte Carlo scenarios")
    st.caption("A: Lowest Cost and B: Fastest Delivery are constrained OR-Tools baselines, not independent per-order choices that overbook shared services. C: Optimized Allocation balances fixed cost/time/risk scales.")
    st.dataframe(experiment.summary, hide_index=True, width="stretch")
    if not bool(experiment.summary.same_full_fulfillment_comparison.all()):
        st.warning("No savings or benefit claim: at least one strategy lacks a fully assigned feasible solution. Compare feasibility and fulfillment before costs or on-time rates.")
    st.caption("All-order simulated on-time rate = simulated on-time deliveries / every requested order; unassigned orders do not count as on time. Assigned-only rates are separately labeled. Utilization = used / available capacity across all listed services; inspect per-service bottlenecks in the dashboard.")
    st.caption("Transit times are lognormal with supplied means and standard deviations. Shipments sharing a service share its scenario delay; all strategies reuse the same draws. Cost is fixed per option. These probabilities depend entirely on synthetic assumptions.")
    st.download_button("V3 strategy comparison CSV", csv_bytes(experiment.summary), "v3_strategy_comparison.csv", "text/csv", on_click="ignore")
    st.download_button("V3 reproducible experiment JSON", experiment_json(experiment), "v3_experiment.json", "application/json", on_click="ignore")
    st.caption(f"Common scenario SHA-256: {experiment.fingerprint}. Total experiment computation: {experiment.elapsed_seconds:.3f} s.")
    details = experiment.simulation_details[STRATEGIES[2]]
    st.write("Optimized allocation: expected times versus simulated transit times")
    st.dataframe(details, hide_index=True, width="stretch")


def _whatif_view(experiment, previous):
    st.subheader("Applied assumptions and previous-run comparison")
    st.write("Change the form above and run again. Tightening capacity, budget or deadlines can make a previously feasible plan infeasible. Changing preferences cannot override a hard constraint.")
    st.json({"constraints": asdict(experiment.constraints), "preferences": asdict(experiment.preferences),
             "mean_time_scale_hours": 336, "cost_scale_usd": 1000,
             "fastest_objective_time_value_usd_per_hour": 10,
             "risk_source": "Analytical lognormal tail using hypothetical mean/std; not carrier history"})
    st.caption("Soft mode penalty is a virtual objective cost, not a transport invoice. A small penalty may deliberately leave an otherwise feasible order unassigned. Fastest Delivery values transit at an assumed USD 10/hour to compare its objective with that penalty.")
    if previous is None:
        st.info("Run a second scenario to see the previous and current results together.")
        return
    same_demand = [asdict(order) for order in previous.data.orders] == [asdict(order) for order in experiment.data.orders]
    same_scenarios = previous.fingerprint == experiment.fingerprint
    if not same_demand or not same_scenarios:
        st.warning("The requested orders/deadlines or random scenarios differ. Treat the runs as separate scenarios; no controlled improvement claim is made.")
    fields = ["strategy", "status", "total_shipping_cost_usd", "unassigned_orders", "simulated_on_time_rate_all_orders"]
    before = previous.summary[fields].copy()
    after = experiment.summary[fields].copy()
    before.insert(0, "run", "Previous applied run")
    after.insert(0, "run", "Current applied run")
    st.dataframe(pd.DataFrame(before.to_dict("records") + after.to_dict("records")), hide_index=True, width="stretch")
    st.caption("Identical results can be valid: the same solution may remain best over a range of weights. Scaling every weight equally leaves normalized preferences unchanged.")
