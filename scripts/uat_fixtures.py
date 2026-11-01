"""Hand-authored synthetic UAT fixtures; never customer or carrier operational data."""
from pathlib import Path
import pandas as pd

AS_OF = "2026-10-01"


def orders(*, all_active=False):
    records = []
    for index in range(120):
        active = all_active or index < 7 or 20 <= index < 50
        late = not all_active and (7 <= index < 20 or 50 <= index < 63)
        records.append(dict(
            shipment_id=f"UAT-{index+1:04d}", carrier=f"合成承运商 {index//15+1}",
            origin="Shanghai, China", destination="Rotterdam, Netherlands",
            transport_mode="Air" if index % 2 == 0 else "Sea",
            status="In Transit" if active else "Delivered",
            shipped_at="2026-09-01T00:00:00Z", planned_delivery="2026-09-30T12:00:00Z",
            actual_delivery="" if active else "2026-10-01T08:00:00Z" if late else "2026-09-30T12:00:00Z",
            shipping_cost=100, currency="USD",
        ))
    return pd.DataFrame(records)


def write(directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    for name, active in (("synthetic_uat_120.csv",False),("synthetic_uat_120_active.csv",True)):
        orders(all_active=active).to_csv(directory/name,index=False,encoding="utf-8-sig")


if __name__ == "__main__":
    write(Path(__file__).resolve().parents[1]/"data/uat")
