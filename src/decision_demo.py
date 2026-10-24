"""Additional fictional context; V1 inputs and results remain unchanged."""

import random
from datetime import datetime, time, timedelta, timezone

import pandas as pd

from src.demo import DEMO_AS_OF, generate_demo_data


def with_demo_context(shipments: pd.DataFrame) -> pd.DataFrame:
    frame = shipments.copy()
    rng = random.Random(73)
    records = []
    for index in range(len(frame)):
        records.append({
            "delivery_deadline": (datetime.combine(DEMO_AS_OF, time(), tzinfo=timezone.utc) + timedelta(hours=24 * (1 + index % 5))).isoformat(),
            "estimated_delay_hours": rng.choice([12, 24, 48, 96]) if index % 7 else "",
            "estimated_financial_impact": rng.choice([0, 100, 500, 2500, 12000]) if index % 4 else "",
            "financial_impact_basis": "Fictional penalty/handling assumption; not realized loss." if index % 4 else "",
            "shipment_value": rng.choice([1000, 5000, 25000, 100000, 200000]),
            "downstream_dependency_count": rng.randint(0, 5),
            "downstream_risk_basis": "Fictional dependent activities supplied for demonstration only.",
            "decision_context_source": "Synthetic scenario assumptions; not validated operational evidence.",
        })
    for column in records[0] if records else []:
        frame[column] = [row[column] for row in records]
    return frame


if __name__ == "__main__":
    from pathlib import Path
    target = Path(__file__).resolve().parents[1] / "data" / "synthetic_decision_shipments.csv"
    with_demo_context(generate_demo_data()).to_csv(target, index=False)
    print("Wrote 160 fictional decision-context rows to", target)
