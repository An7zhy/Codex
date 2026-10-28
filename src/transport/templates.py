"""Editable templates and explicitly synthetic, independently hand-checkable fixtures."""

from io import BytesIO

import pandas as pd

from .input_contract import HEADERS, FIELD_NOTES


def template_tables(count=2):
    if count not in (0, 2, 100):
        raise ValueError("Template sizes: 0 (headers only), 2 or 100 synthetic shipments.")
    if not count:
        return {name: pd.DataFrame(columns=columns) for name, columns in HEADERS.items()}
    shipments, options = [], []
    for index in range(count):
        odd = index % 2 == 0
        sid = f"UPLOAD-{index + 1:04d}"
        shipments.append(dict(shipment_id=sid, origin="Shanghai, China", destination="Rotterdam, Netherlands",
            weight="6", weight_unit="kg", volume="1", volume_unit="m3",
            delivery_deadline="2026-10-03T00:00:00Z" if odd else "2026-10-02T00:00:00Z"))
        for service, price, hours in (("SHARED-ECO", 40 if odd else 50, 24), ("SHARED-FAST", 100 if odd else 80, 12)):
            options.append(dict(shipment_id=sid, service_id=service, quoted_cost=str(price), currency="USD",
                expected_transit_hours=str(hours), time_unit="h", quote_status="estimate", quote_reference="Synthetic example quote; replace with your source",
                time_status="estimate", time_reference="Synthetic expected transit, not a carrier commitment"))
    capacity = []
    for service, slots in (("SHARED-ECO", count // 2), ("SHARED-FAST", count)):
        capacity.append(dict(service_id=service, origin="Shanghai, China", destination="Rotterdam, Netherlands", transport_mode="Air",
            weight_capacity=str(slots * 6), weight_unit="kg", volume_capacity=str(slots), volume_unit="m3", shipment_capacity=str(slots),
            capacity_status="estimate", capacity_reference="Synthetic common capacity pool; not repeated per shipment"))
    constraints = [dict(planning_start="2026-10-01T00:00:00Z", budget=str(count * 100), currency="USD", allow_unassigned="false",
        unassigned_penalty="100000", penalty_currency="USD", cost_weight="100", time_weight="0", time_limit_seconds="3",
        source_label=f"Synthetic template example: {count} shipments (not real business data)", data_kind="synthetic_test")]
    return {name: pd.DataFrame(rows, columns=HEADERS[name]) for name, rows in
            (("shipments", shipments), ("transport_options", options), ("capacity", capacity), ("constraints", constraints))}


def workbook_bytes(tables):
    stream = BytesIO()
    with pd.ExcelWriter(stream, engine="openpyxl") as writer:
        from openpyxl.comments import Comment
        for name, frame in tables.items():
            frame.to_excel(writer, sheet_name=name, index=False)
            sheet = writer.sheets[name]
            sheet.freeze_panes = "A2"
            for column in sheet.columns:
                sheet.column_dimensions[column[0].column_letter].width = min(45, max(18, len(str(column[0].value)) + 3))
                column[0].comment = Comment(FIELD_NOTES.get(str(column[0].value), "See the planning input contract."), "Logistics Insight AI")
    return stream.getvalue()
