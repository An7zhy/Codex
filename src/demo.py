"""Reproducible, explicitly fictional international shipment data."""

import argparse
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
import random

import pandas as pd
from openpyxl.styles import Font, PatternFill

DEMO_AS_OF = date(2026, 10, 1)
DEMO_LABEL = "Synthetic Demo Data"


def generate_demo_data(seed: int = 42) -> pd.DataFrame:
    """160 rows, including intentional quality errors; no company/customer data."""
    rng = random.Random(seed)
    routes = [
        ("Shanghai, China", "Rotterdam, Netherlands", "Sea", 1800),
        ("Shanghai, China", "Rotterdam, Netherlands", "Air", 4300),
        ("Shenzhen, China", "Los Angeles, USA", "Sea", 2200),
        ("Shenzhen, China", "Los Angeles, USA", "Air", 5100),
        ("Singapore, Singapore", "Hamburg, Germany", "Air", 3100),
        ("Hamburg, Germany", "Shanghai, China", "Sea", 1900),
        ("Los Angeles, USA", "Singapore, Singapore", "Air", 4800),
        ("Ho Chi Minh City, Vietnam", "Seattle, USA", "Sea", 2400),
    ]
    reference = datetime.combine(DEMO_AS_OF, datetime.min.time(), tzinfo=timezone.utc)
    rows = []
    for index in range(160):
        origin, destination, mode, base_cost = routes[index // 20]
        delivered = index % 10 < 6
        planned = reference - timedelta(days=rng.randint(5, 25)) if delivered else reference + timedelta(days=rng.randint(-9, 9))
        shipped = planned - timedelta(days=5 if mode == "Air" else 30)
        actual = planned + timedelta(hours=(-24, -4, 0, 12, 24, 72)[index % 6]) if delivered else None
        cost = round(base_cost * rng.uniform(0.85, 1.15), 2)
        if index in (18, 58, 98, 138):
            cost = round(base_cost * 4.5, 2)
        rows.append({
            "shipment_id": f"SYN-{index + 1:04d}", "origin": origin, "destination": destination,
            "transport_mode": mode, "carrier": ("Demo Air One" if index % 2 else "Demo Air Two") if mode == "Air" else ("Demo Ocean One" if index % 2 else "Demo Ocean Two"),
            "planned_delivery": planned.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "actual_delivery": actual.strftime("%Y-%m-%dT%H:%M:%SZ") if actual else "",
            "shipping_cost": cost, "status": "Delivered" if delivered else "In Transit",
            "shipped_at": shipped.strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
    # Intentional defects exercise field-level handling and the review queue.
    rows[1]["actual_delivery"] = ""
    rows[2]["planned_delivery"] = "not-a-date"
    rows[3]["actual_delivery"] = "2026-99-99"
    rows[4]["shipping_cost"] = -250
    rows[5]["origin"] = ""
    rows[6]["carrier"] = ""
    rows[7]["shipment_id"] = ""
    rows[8]["planned_delivery"] = "1995-01-01"
    rows[10]["shipping_cost"] = ""
    rows[11]["shipping_cost"] = "not-a-cost"
    rows[12]["status"] = "unexpected-status"
    rows[13]["actual_delivery"] = "2026-12-01T00:00:00Z"
    rows[15]["transport_mode"] = ""
    rows[16]["actual_delivery"] = "2026-09-25T00:00:00Z"
    rows[20]["actual_delivery"] = rows[20]["shipped_at"][:10] + "T00:00:00Z"
    rows[20]["shipped_at"] = "2026-09-30T00:00:00Z"
    rows[159]["shipment_id"] = rows[0]["shipment_id"]
    return pd.DataFrame(rows)


def demo_xlsx_bytes(frame: pd.DataFrame | None = None) -> bytes:
    """First sheet contains raw inputs; the second states provenance and assumptions."""
    frame = generate_demo_data() if frame is None else frame
    buffer = BytesIO()
    notes = pd.DataFrame({"Topic": ["Provenance", "Reference date", "Currency", "Dates", "Intentional defects", "Editing", "Example", "Cost comparison"],
                          "Details": [
                              "Synthetic Demo Data. Fictional carriers and shipments; no real enterprise data.",
                              str(DEMO_AS_OF) + " inclusive UTC calendar day.",
                              "All shipping_cost inputs are USD; prices are invented test inputs.",
                              "ISO YYYY-MM-DD or ISO timestamp. Naive dates are interpreted as UTC.",
                              "Some IDs, dates and costs are missing, invalid or duplicated to test quality handling.",
                              "Edit the Shipments sheet; keep its column headers. actual_delivery is blank while In Transit.",
                              "SYN-0001 is an example shipment; all rows are fictional examples.",
                              "Compare mode + directional route; group sizes and prices are demo assumptions, not industry benchmarks.",
                          ]})
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="Shipments", index=False)
        notes.to_excel(writer, sheet_name="Read me", index=False)
        for sheet in writer.book.worksheets:
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            for row in sheet:
                for cell in row:
                    cell.font = Font(name="Arial", size=11, bold=cell.row == 1, color="FFFFFF" if cell.row == 1 else "193247")
                    if cell.row == 1:
                        cell.fill = PatternFill("solid", fgColor="193247")
            for column in sheet.columns:
                letter = column[0].column_letter
                sheet.column_dimensions[letter].width = min(70, max(18, max(len(str(cell.value or "")) for cell in column) + 2))
    # These worksheets are raw test inputs, not calculated financial models.
    # They contain no formulas and therefore do not require formula recalculation.
    return buffer.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Synthetic Demo Data (CSV and XLSX).")
    parser.add_argument("--output-dir", default="data")
    args = parser.parse_args()
    target = Path(args.output_dir)
    target.mkdir(parents=True, exist_ok=True)
    data = generate_demo_data()
    data.to_csv(target / "synthetic_shipments.csv", index=False, encoding="utf-8")
    (target / "synthetic_shipments.xlsx").write_bytes(demo_xlsx_bytes(data))
    print(f"Wrote {len(data)} synthetic rows per file to {target}; reference date {DEMO_AS_OF}.")


if __name__ == "__main__":
    main()
