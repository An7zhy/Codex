"""The small, explicit data contract used by the MVP."""

REQUIRED_COLUMNS = (
    "shipment_id", "origin", "destination", "transport_mode", "carrier",
    "planned_delivery", "actual_delivery", "shipping_cost", "status",
)
MIN_COST_GROUP_SIZE = 8
EARLIEST_DATE = "2000-01-01"
# Technical guardrail, not a market-rate benchmark. With the 100,000-row input
# limit this also bounds cost aggregates well below float64 overflow.
MAX_SHIPPING_COST = 1_000_000_000_000

KPI_DEFINITIONS = {
    "Total Shipments": "Unique, nonblank shipment IDs; keep the first occurrence. Other field errors remain reviewable.",
    "Delivered Shipments": "Retained shipments reported Delivered with a valid actual delivery at or before the analysis cutoff and valid actual chronology.",
    "On-Time Delivery Rate": "On-time deliveries / delivered shipments with a valid planned date and valid planned chronology. Incomplete shipments are excluded.",
    "Average Delay Hours": "Mean positive delay among eligible delayed deliveries only. Zero when eligible deliveries exist but none is late; N/A when none is eligible.",
    "Overdue Shipments": "Retained In Transit shipments with a valid planned date before the cutoff and no reported actual delivery; counted separately from completed delays.",
    "Total Shipping Cost": "Sum of finite USD costs from 0 to 1,000,000,000,000 on retained shipments across all statuses; missing/invalid costs are excluded. The upper limit is a technical guardrail, not a market benchmark.",
    "Cost Anomalies": "High-cost retained shipments in a mode + directional origin/destination group with at least 8 valid comparable costs; thresholds use the complete uploaded dataset before filtering.",
}


class DataInputError(ValueError):
    """An input file cannot be interpreted as the required shipment table."""
