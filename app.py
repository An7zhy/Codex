"""Streamlit presentation layer. Business rules live in src/ and are testable."""

from datetime import datetime, timezone

import pandas as pd
import plotly.express as px
import streamlit as st

from src.analysis import analyze_shipments, calculate_kpis, carrier_performance, exception_shipments
from src.demo import DEMO_AS_OF, DEMO_LABEL, demo_xlsx_bytes, generate_demo_data
from src.decision_demo import with_demo_context
from src.copilot_ui import render_priority_queue, render_decision_center, render_case_history, render_evaluation
from src.exports import csv_bytes
from src.ingestion import load_shipments
from src.reporting import RuleBasedReportGenerator
from src.schema import DataInputError, KPI_DEFINITIONS

BLUE = "#1469B8"
COLORS = [BLUE, "#D78316", "#167D68", "#AA4860", "#62758C"]
DETAIL_COLUMNS = [
    "source_row", "shipment_id", "included_in_analysis", "origin", "destination",
    "transport_mode", "carrier", "status", "planned_delivery", "actual_delivery",
    "delay_hours", "overdue_hours", "shipping_cost", "cost_assessment",
    "cost_group_size", "cost_threshold", "exception_types", "data_quality_issues",
]


@st.cache_data(show_spinner=False)
def sample_downloads() -> tuple[bytes, bytes]:
    data = generate_demo_data()
    return csv_bytes(data), demo_xlsx_bytes(data)


def show_chart(figure) -> None:
    figure.update_layout(
        template="plotly_white", font={"family": "Arial, sans-serif", "color": "#193247"},
        margin={"l": 8, "r": 8, "t": 16, "b": 8}, height=330,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(figure, use_container_width=True, config={"displaylogo": False})


def show_overview(view: pd.DataFrame) -> None:
    included = view.loc[view["included_in_analysis"]]
    left, right = st.columns(2)
    with left:
        st.subheader("Reported shipment status")
        if included.empty:
            st.info("No retained shipments in this selection.")
        else:
            counts = included["status"].value_counts().rename_axis("Status").reset_index(name="Shipments")
            show_chart(px.pie(counts, names="Status", values="Shipments", hole=0.6, color_discrete_sequence=COLORS))
            st.caption("Uploaded status labels. Delivered KPI additionally requires a valid actual delivery.")
    with right:
        st.subheader("Carrier on-time performance")
        carriers = carrier_performance(view)
        eligible = carriers.dropna(subset=["on_time_rate_pct"])
        if eligible.empty:
            st.info("No eligible completed deliveries for a carrier comparison.")
        else:
            figure = px.bar(eligible, x="carrier", y="on_time_rate_pct",
                            hover_data=["eligible_deliveries", "on_time_shipments"],
                            labels={"carrier": "Carrier", "on_time_rate_pct": "On-time rate (%)"},
                            color_discrete_sequence=[BLUE])
            figure.update_yaxes(range=[0, 100])
            show_chart(figure)
        st.caption("Denominator: each carrier's completed deliveries with valid planned and actual dates.")
    left, right = st.columns(2)
    with left:
        st.subheader("Average cost by transport mode")
        costs = included.loc[included["valid_cost"]]
        if costs.empty:
            st.info("No valid shipping costs in this selection.")
        else:
            average = costs.groupby("transport_mode")["shipping_cost"].agg(["mean", "count"]).reset_index()
            show_chart(px.bar(average, x="transport_mode", y="mean", hover_data=["count"],
                              labels={"transport_mode": "Transport mode", "mean": "Mean cost (USD)"},
                              color_discrete_sequence=["#167D68"]))
        st.caption("Valid costs only, across all statuses. Shipment weight and service levels are not normalized.")
    with right:
        st.subheader("Longest completed delays")
        late = included.loc[included["is_delayed"]].nlargest(10, "delay_hours").sort_values("delay_hours")
        if late.empty:
            st.info("No completed late deliveries in this selection.")
        else:
            show_chart(px.bar(late, x="delay_hours", y="shipment_id", orientation="h",
                              hover_data=["carrier", "origin", "destination"],
                              labels={"delay_hours": "Delay (hours)", "shipment_id": "Shipment"},
                              color_discrete_sequence=["#D78316"]))
        st.caption("Completed deliveries only. Overdue in-transit shipments appear in Exceptions.")


def main() -> None:
    st.set_page_config(page_title="Logistics Insight AI", page_icon="📦", layout="wide")
    st.markdown("""<style>
        .stApp { font-family: 'Segoe UI', Arial, sans-serif; }
        .block-container { padding-top: 2rem; max-width: 1480px; }
        h1 { letter-spacing: -.035em; }
        [data-testid="stMetricValue"] { color: #1469B8; }
        [data-testid="stMetricLabel"] { font-weight: 600; }
        [data-testid="stSidebar"] { border-right: 1px solid #DCE5EE; }
        :focus-visible { outline: 3px solid #1469B8; outline-offset: 2px; }
        @media (max-width: 700px) { .block-container { padding: 1.2rem 1rem; } }
        </style>""", unsafe_allow_html=True)
    st.title("Logistics Insight AI")
    st.write("Lightweight, explainable logistics exception decision copilot for small freight forwarders.")
    st.caption("Engineering prototype validated on synthetic data. Deterministic rules; no live carrier network, validated forecasting or API key required.")

    workspace = st.sidebar.selectbox("Workspace", ["V1/V2 Exception Copilot", "V3 Transportation Optimization"], key="workspace")
    if workspace == "V3 Transportation Optimization":
        from src.transport.ui import render_transportation

        render_transportation()
        return

    with st.sidebar:
        st.header("Analysis controls")
        source = st.radio("Data source", [DEMO_LABEL, "Upload a file"], key="data_source")
        uploaded = None
        if source == "Upload a file":
            uploaded = st.file_uploader("Upload shipment data", type=["csv", "xlsx"],
                                        help="UTF-8 CSV or first Excel sheet; headers on row 1. Up to 20 MB and 100,000 rows.")
        as_of = st.date_input(
            "Analysis date (UTC)",
            value=DEMO_AS_OF if source == DEMO_LABEL else datetime.now(timezone.utc).date(),
            min_value=datetime(2000, 1, 1).date(), key="as_of_" + source,
            help="Inclusive UTC day. Demo reference date: 2026-10-01. This does not reconstruct historical statuses.",
        )
        st.caption("All shipping costs are assumed USD. Convert mixed currencies before uploading.")
        with st.expander("Download example files"):
            sample_csv, sample_xlsx = sample_downloads()
            st.caption("Synthetic Demo Data: 160 fictional input rows with intentional quality problems. Reference date: 2026-10-01.")
            st.download_button("Demo CSV", sample_csv, "synthetic_shipments.csv", "text/csv", key="demo_csv", on_click="ignore")
            st.download_button("Demo Excel", sample_xlsx, "synthetic_shipments.xlsx",
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="demo_xlsx", on_click="ignore")
            st.download_button("Decision demo CSV", csv_bytes(with_demo_context(generate_demo_data())),
                               "synthetic_decision_shipments.csv", "text/csv", on_click="ignore")

    if source == DEMO_LABEL:
        raw = with_demo_context(generate_demo_data())
        source_label = DEMO_LABEL + " — fictional orders and carriers"
        st.info("Synthetic Demo Data — 160 fictional source rows across China, Europe, the USA and Southeast Asia. Includes intentional errors. This is not real enterprise operating data.")
    else:
        st.caption("Uploaded data is user-provided; provenance is not verified. Included example files are Synthetic Demo Data.")
        if uploaded is None:
            st.info("Upload a CSV or Excel file to begin, or select Synthetic Demo Data in the sidebar.")
            with st.expander("Required columns", expanded=True):
                st.code("shipment_id, origin, destination, transport_mode, carrier,\nplanned_delivery, actual_delivery, shipping_cost, status")
                st.write("Use ISO dates (YYYY-MM-DD). Leave actual_delivery blank for shipments still in transit. Optional shipped_at enables chronology checks.")
            return
        try:
            raw = load_shipments(uploaded.getvalue(), uploaded.name)
        except DataInputError as exc:
            st.error(str(exc))
            return
        source_label = "Uploaded file: " + uploaded.name + " (user-provided)"

    result = analyze_shipments(raw, as_of)
    all_rows = result.shipments
    with st.sidebar:
        st.divider()
        st.subheader("Filter records")
        st.caption("An empty filter includes all values. Cost thresholds remain based on the full input.")
        carriers = st.multiselect("Carrier", sorted(all_rows["carrier"].unique()), key="carrier_filter_" + source)
        modes = st.multiselect("Transport mode", sorted(all_rows["transport_mode"].unique()), key="mode_filter_" + source)
        statuses = st.multiselect("Shipment status", sorted(all_rows["status"].unique()), key="status_filter_" + source)
        query = st.text_input("Shipment ID contains", key="id_filter_" + source).strip()

    view = all_rows.copy()
    scope_parts = []
    for column, values in (("carrier", carriers), ("transport_mode", modes), ("status", statuses)):
        if values:
            view = view.loc[view[column].isin(values)]
            scope_parts.append(column + "=" + ", ".join(values))
    if query:
        view = view.loc[view["shipment_id"].str.contains(query, case=False, regex=False, na=False)]
        scope_parts.append("shipment_id contains " + query)
    scope = "; ".join(scope_parts) or "All records"
    issues = result.issues.loc[result.issues["source_row"].isin(view["source_row"])]
    k = calculate_kpis(view)
    if raw.empty:
        st.warning("This file contains headers but no shipment rows. Add data and upload it again.")
    elif view.empty:
        st.warning("No records match these filters. Clear or change the sidebar filters.")
    st.caption(f"{len(view):,} of {len(all_rows):,} source rows selected. {k['excluded_rows']} selected rows excluded for missing or repeated IDs. Analysis cutoff: {as_of.isoformat()}, end of day UTC.")

    columns = st.columns(4)
    metrics = [
        ("Total Shipments", f"{k['total_shipments']:,}"),
        ("Delivered Shipments", f"{k['delivered_shipments']:,}"),
        ("On-Time Delivery Rate", "N/A" if k["on_time_delivery_rate"] is None else f"{k['on_time_delivery_rate']:.1%}"),
        ("Average Delay Hours", "N/A" if k["average_delay_hours"] is None else f"{k['average_delay_hours']:.1f}"),
    ]
    for column, (label, value) in zip(columns, metrics):
        column.metric(label, value, help=KPI_DEFINITIONS[label])
    for column, (label, value) in zip(st.columns(3), [
        ("Overdue Shipments", f"{k['overdue_shipments']:,}"),
        ("Total Shipping Cost", f"${k['total_shipping_cost']:,.2f}"),
        ("Cost Anomalies", f"{k['cost_anomalies']:,}"),
    ]):
        column.metric(label, value, help=KPI_DEFINITIONS[label])
    st.caption(f"On-time denominator: {k['eligible_deliveries']} eligible completed deliveries. Average delay uses {k['delayed_shipments']} late deliveries. Cost total uses {k['cost_eligible_shipments']} valid costs.")

    overview, exceptions_tab, quality_tab, downloads_tab, priority_tab, decision_tab, history_tab, evaluation_tab = st.tabs(
        ["Overview", "Exceptions", "Data quality", "Report & downloads", "Priority queue", "Decision Center", "Case history", "Evaluation"])
    with overview:
        show_overview(view)
        with st.expander("KPI definitions and rule assumptions"):
            for name, definition in KPI_DEFINITIONS.items():
                st.markdown(f"**{name}:** {definition}")
            st.write("High cost threshold: median + max(3.5 × 1.4826 × MAD, 0.5 × median). Groups need at least 8 valid costs. This screens relative high cost; it does not prove overcharging.")
            st.write("ISO dates without an offset are UTC. Optional shipped_at enables delivery-before-shipping checks. Early delivery before the planned date is valid.")
            st.write("Changing the analysis date does not reconstruct historical shipment statuses. Use a snapshot that matches the selected date.")
    with exceptions_tab:
        st.subheader("Shipment exception queue")
        st.caption("Includes operational exceptions and data quality records, including excluded rows. One row can have multiple findings.")
        exceptions = exception_shipments(view)
        if exceptions.empty:
            st.success("No exceptions in this selection.")
        else:
            st.dataframe(exceptions[DETAIL_COLUMNS], hide_index=True, width="stretch")
        if k["cost_insufficient_shipments"]:
            st.info(f"{k['cost_insufficient_shipments']} retained shipments: Insufficient data for cost comparison. No cost anomaly conclusion is made for them.")
        st.subheader("All processed records")
        st.dataframe(view[DETAIL_COLUMNS], hide_index=True, width="stretch")
    with quality_tab:
        st.subheader("Data quality review")
        st.write(f"{k['quality_rows']} selected source rows have {len(issues)} quality findings.")
        st.caption("Source row is the original table row, including the header. The first occurrence of an ID is retained; later duplicates and missing IDs are excluded from shipment KPIs.")
        if issues.empty:
            st.success("No quality findings in this selection.")
        else:
            st.dataframe(issues, hide_index=True, width="stretch")
            with st.expander("Inspect original values for affected records"):
                affected = view.loc[view["has_data_quality_issue"]]
                raw_columns = [column for column in affected if column.endswith("_raw")]
                originals = affected[["source_row", "included_in_analysis"] + raw_columns].copy()
                originals[raw_columns] = originals[raw_columns].astype("string").fillna("")
                st.dataframe(originals, hide_index=True, width="stretch")
    with downloads_tab:
        st.subheader("Export this selection")
        st.caption("All downloads reflect the current filters and analysis date. Original fields are retained as *_raw columns; formula-like CSV text is escaped for Excel.")
        report = RuleBasedReportGenerator().generate(view, issues, result.as_of, source_label, scope)
        columns = st.columns(3)
        columns[0].download_button("Processed orders CSV", csv_bytes(view), "processed_shipments.csv", "text/csv", on_click="ignore")
        columns[1].download_button("Exceptions CSV", csv_bytes(exception_shipments(view)), "shipment_exceptions.csv", "text/csv", on_click="ignore")
        columns[2].download_button("English report", report.encode("utf-8"), "logistics_operations_report.md", "text/markdown", on_click="ignore")
        st.markdown(report)

    with priority_tab:
        priorities, priority_settings = render_priority_queue(view, result.cutoff)
    with decision_tab:
        render_decision_center(priorities, result.cutoff, source_label)
    with history_tab:
        render_case_history()
    with evaluation_tab:
        render_evaluation(priority_settings)


if __name__ == "__main__":
    main()
