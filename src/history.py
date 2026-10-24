"""Local SQLite case history with parameterized queries and explicit unknown outcomes."""

from dataclasses import asdict, dataclass
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import uuid

import pandas as pd

from src.decisions import ACTIONS
from src.priority import number

RESOLUTION_STATUSES = ("Open", "In Progress", "Resolved", "Cancelled")


@dataclass
class CaseInput:
    shipment_id: str
    exception_type: str
    selected_action: str
    estimated_cost: float | None = None
    actual_cost: float | None = None
    estimated_delay: float | None = None
    actual_delay: float | None = None
    resolution_status: str = "Open"
    resolution_notes: str = ""
    origin: str = ""
    destination: str = ""
    transport_mode: str = ""
    carrier: str = ""
    assumptions_json: str = "{}"
    priority_snapshot_json: str = "{}"
    analysis_date: str = ""

    def validate(self):
        if not self.shipment_id.strip() or len(self.shipment_id) > 200:
            raise ValueError("Shipment ID is required (at most 200 characters).")
        if not self.exception_type.strip() or len(self.exception_type) > 500:
            raise ValueError("Exception type is required (at most 500 characters).")
        if self.selected_action not in ACTIONS or self.resolution_status not in RESOLUTION_STATUSES:
            raise ValueError("Unsupported action or resolution status.")
        for key in ("estimated_cost", "actual_cost", "estimated_delay", "actual_delay"):
            value = getattr(self, key)
            if value is not None and (number(value) is None or number(value) > 1_000_000_000):
                raise ValueError(f"{key} must be unknown or a finite nonnegative value at most 1,000,000,000.")
        if len(self.resolution_notes) > 4000:
            raise ValueError("Resolution notes must have at most 4,000 characters.")


def _key(value: str) -> str:
    return " ".join(str(value).split()).casefold()


class HistoryStore:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("""CREATE TABLE IF NOT EXISTS cases (
                case_id TEXT PRIMARY KEY, shipment_id TEXT NOT NULL, exception_type TEXT NOT NULL,
                selected_action TEXT NOT NULL, estimated_cost REAL, actual_cost REAL,
                estimated_delay REAL, actual_delay REAL, resolution_status TEXT NOT NULL,
                resolution_notes TEXT NOT NULL, origin TEXT, destination TEXT, transport_mode TEXT,
                carrier TEXT, assumptions_json TEXT NOT NULL, priority_snapshot_json TEXT NOT NULL,
                analysis_date TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1, origin_key TEXT, destination_key TEXT, mode_key TEXT
            )""")
            connection.execute("CREATE INDEX IF NOT EXISTS case_shipment_idx ON cases(shipment_id)")
            connection.execute("CREATE INDEX IF NOT EXISTS case_match_idx ON cases(origin_key, destination_key, mode_key, exception_type)")

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def create_case(self, case: CaseInput) -> str:
        case.validate()
        record = asdict(case)
        for key in ("estimated_cost", "actual_cost", "estimated_delay", "actual_delay"):
            if record[key] is not None:
                record[key] = float(record[key])
        record["shipment_id"] = record["shipment_id"].strip()
        record["exception_type"] = record["exception_type"].strip()
        record.update(case_id=uuid.uuid4().hex, created_at=datetime.now(timezone.utc).isoformat(),
                      updated_at=datetime.now(timezone.utc).isoformat(), version=1,
                      origin_key=_key(case.origin), destination_key=_key(case.destination), mode_key=_key(case.transport_mode))
        columns = list(record)
        with self._connect() as connection:
            connection.execute(f"INSERT INTO cases ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", [record[key] for key in columns])
        return record["case_id"]

    def list_cases(self, shipment_id: str | None = None, resolution_status: str | None = None,
                   exception_type: str | None = None, limit: int = 200) -> pd.DataFrame:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 1000:
            raise ValueError("Limit must be an integer from 1 to 1,000.")
        conditions, values = [], []
        for column, value in (("shipment_id", shipment_id), ("resolution_status", resolution_status), ("exception_type", exception_type)):
            if value:
                conditions.append(column + " = ?")
                values.append(value.strip())
        query = "SELECT * FROM cases" + (" WHERE " + " AND ".join(conditions) if conditions else "")
        with self._connect() as connection:
            return pd.read_sql_query(query + " ORDER BY created_at DESC, case_id DESC LIMIT ?", connection, params=values + [limit])

    def get_case(self, case_id: str) -> dict:
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,)).fetchone()
        if row is None:
            raise LookupError("Case not found.")
        return dict(row)

    def update_case(self, case_id: str, resolution_status: str, actual_cost: float | None,
                    actual_delay: float | None, resolution_notes: str, expected_version: int | None = None) -> None:
        current = self.get_case(case_id)
        candidate = CaseInput(current["shipment_id"], current["exception_type"], current["selected_action"],
                              actual_cost=actual_cost, actual_delay=actual_delay,
                              resolution_status=resolution_status, resolution_notes=resolution_notes)
        candidate.validate()
        version = current["version"] if expected_version is None else expected_version
        with self._connect() as connection:
            cursor = connection.execute("""UPDATE cases SET resolution_status = ?, actual_cost = ?,
                actual_delay = ?, resolution_notes = ?, updated_at = ?, version = version + 1
                WHERE case_id = ? AND version = ?""", (
                    resolution_status, float(actual_cost) if actual_cost is not None else None,
                    float(actual_delay) if actual_delay is not None else None, resolution_notes,
                    datetime.now(timezone.utc).isoformat(), case_id, version,
                ))
            if cursor.rowcount != 1:
                raise ValueError("This case changed in another session. Refresh before updating.")

    def similar_cases(self, origin: str, destination: str, transport_mode: str,
                      exception_type: str, exclude_shipment_id: str = "") -> pd.DataFrame:
        keys = [_key(value) for value in (origin, destination, transport_mode)]
        if any(value in ("", "unknown") for value in keys) or not exception_type.strip():
            return pd.DataFrame()
        with self._connect() as connection:
            result = pd.read_sql_query("""SELECT * FROM cases WHERE origin_key = ?
                AND destination_key = ? AND mode_key = ? AND exception_type = ?
                AND shipment_id != ? ORDER BY created_at DESC, case_id DESC LIMIT 50""",
                connection, params=keys + [exception_type.strip(), exclude_shipment_id])
        result["match_reason"] = "Exact directional route, transport mode and exception type"
        return result
