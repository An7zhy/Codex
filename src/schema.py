"""The small, explicit data contract used by the MVP."""

REQUIRED_COLUMNS = (
    "shipment_id", "origin", "destination", "transport_mode", "carrier",
    "planned_delivery", "actual_delivery", "shipping_cost", "status",
)
MIN_COST_GROUP_SIZE = 8
EARLIEST_DATE = "2000-01-01"

KPI_DEFINITIONS = {
    "Total Shipments": "Unique, nonblank shipment IDs; keep the first occurrence. Other field errors remain reviewable.",
    "Delivered Shipments": "Retained shipments reported Delivered with a valid actual delivery at or before the analysis cutoff and valid actual chronology.",
    "On-Time Delivery Rate": "On-time deliveries / delivered shipments with a valid planned date and valid planned chronology. Incomplete shipments are excluded.",
    "Average Delay Hours": "Mean positive delay among eligible delayed deliveries only. Zero when eligible deliveries exist but none is late; N/A when none is eligible.",
    "Overdue Shipments": "Retained In Transit shipments with a valid planned date before the cutoff and no reported actual delivery; counted separately from completed delays.",
    "Total Shipping Cost": "Sum of finite, nonnegative costs on retained shipments, across all statuses. All costs must use USD; missing or invalid costs are excluded.",
    "Cost Anomalies": "High-cost retained shipments in a mode + directional origin/destination group with at least 8 valid comparable costs; thresholds use the complete uploaded dataset before filtering.",
}


class DataInputError(ValueError):
    """An input file cannot be interpreted as the required shipment table."""
