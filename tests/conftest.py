import pandas as pd
import pytest


@pytest.fixture(autouse=True)
def isolated_history_database(tmp_path, monkeypatch):
    """Even read-only-looking AppTest runs initialize SQLite; never use user history."""
    monkeypatch.setenv("LOGISTICS_DB_PATH", str(tmp_path / "history.sqlite3"))


@pytest.fixture
def make_rows():
    def make(*overrides):
        records = []
        for index, override in enumerate(overrides):
            row = {
                "shipment_id": f"TEST-{index + 1}", "origin": "Shanghai, China",
                "destination": "Rotterdam, Netherlands", "transport_mode": "Sea",
                "carrier": "Fictional Carrier", "planned_delivery": "2026-09-30T12:00:00Z",
                "actual_delivery": "2026-09-30T12:00:00Z", "shipping_cost": 100,
                "status": "Delivered", "shipped_at": "2026-09-01T00:00:00Z",
            }
            row.update(override)
            records.append(row)
        return pd.DataFrame(records)
    return make
