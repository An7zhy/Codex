"""Local SQLite case history with parameterized queries and explicit unknown outcomes."""

from dataclasses import asdict, dataclass
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
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
        if not isinstance(self.shipment_id, str) or not self.shipment_id.strip() or len(self.shipment_id) > 200:
            raise ValueError("Shipment ID is required (at most 200 characters).")
        if not isinstance(self.exception_type, str) or not self.exception_type.strip() or len(self.exception_type) > 500:
            raise ValueError("Exception type is required (at most 500 characters).")
        if self.selected_action not in ACTIONS or self.resolution_status not in RESOLUTION_STATUSES:
            raise ValueError("Unsupported action or resolution status.")
        for key in ("estimated_cost", "actual_cost", "estimated_delay", "actual_delay"):
            value = getattr(self, key)
            if value is not None and (number(value) is None or number(value) > 1_000_000_000):
                raise ValueError(f"{key} must be unknown or a finite nonnegative value at most 1,000,000,000.")
        if not isinstance(self.resolution_notes, str) or len(self.resolution_notes) > 4000:
            raise ValueError("Resolution notes must have at most 4,000 characters.")
        for key in ("origin", "destination", "transport_mode", "carrier", "analysis_date"):
            if not isinstance(getattr(self, key), str):
                raise ValueError(f"{key} must be text.")
        for key in ("assumptions_json", "priority_snapshot_json"):
            try:
                value = getattr(self, key)
                if not isinstance(value, str):
                    raise ValueError("JSON metadata must be text.")
                def reject_constant(value):
                    raise ValueError("Non-finite JSON constants are not allowed.")
                parsed = json.loads(value, parse_constant=reject_constant)
                if not isinstance(parsed, dict):
                    raise ValueError("Metadata must be a JSON object.")
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{key} must contain a valid finite JSON object.") from exc


def _key(value: str) -> str:
    return " ".join(str(value).split()).casefold()


class HistoryStore:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("""CREATE TABLE IF NOT EXISTS cases (
                case_id TEXT PRIMARY KEY, shipment_id TEXT NOT NULL, exception_type TEXT NOT NULL,
                selected_action TEXT NOT NULL, estimated_cost REAL, actual_cost REAL,
                estimated_delay REAL, actual_delay REAL, resolution_status TEXT NOT NULL,
                resolution_notes TEXT NOT NULL, origin TEXT, destination TEXT, transport_mode TEXT,
                carrier TEXT, assumptions_json TEXT NOT NULL, priority_snapshot_json TEXT NOT NULL,
                analysis_date TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1, origin_key TEXT, destination_key TEXT, mode_key TEXT,
                request_key TEXT, request_payload_hash TEXT
            )""")
            # Additive migration: preserve every existing V2 case and outcome.
            columns = {row[1] for row in connection.execute("PRAGMA table_info(cases)")}
            for column in ("request_key", "request_payload_hash"):
                if column not in columns:
                    connection.execute(f"ALTER TABLE cases ADD COLUMN {column} TEXT")
            connection.execute("CREATE INDEX IF NOT EXISTS case_shipment_idx ON cases(shipment_id)")
            connection.execute("CREATE INDEX IF NOT EXISTS case_match_idx ON cases(origin_key, destination_key, mode_key, exception_type)")
            connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS case_request_key_idx ON cases(request_key) WHERE request_key IS NOT NULL")

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def create_case(self, case: CaseInput, *, idempotency_key: str | None = None, max_records: int | None = None) -> str:
        case.validate()
        if idempotency_key is not None and (not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > 200):
            raise ValueError("Idempotency key must be nonblank text with at most 200 characters.")
        record = asdict(case)
        for key in ("estimated_cost", "actual_cost", "estimated_delay", "actual_delay"):
            if record[key] is not None:
                record[key] = float(record[key])
        record["shipment_id"] = record["shipment_id"].strip()
        record["exception_type"] = record["exception_type"].strip()
        canonical = dict(record)
        for key in ("assumptions_json", "priority_snapshot_json"):
            canonical[key] = json.loads(canonical[key])
        payload_hash = hashlib.sha256(json.dumps(canonical, sort_keys=True, allow_nan=False).encode()).hexdigest()
        record.update(case_id=uuid.uuid4().hex, created_at=datetime.now(timezone.utc).isoformat(),
                      updated_at=datetime.now(timezone.utc).isoformat(), version=1,
                      origin_key=_key(case.origin), destination_key=_key(case.destination), mode_key=_key(case.transport_mode),
                      request_key=idempotency_key, request_payload_hash=payload_hash)
        columns = list(record)
        with self._connect() as connection:
            # Quota and insertion share one write transaction across API workers.
            # Identical retries still succeed when the quota has been reached.
            if max_records is not None:
                if not isinstance(max_records, int) or isinstance(max_records, bool) or max_records < 1:
                    raise ValueError("max_records must be a positive integer.")
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute("SELECT case_id,request_payload_hash FROM cases WHERE request_key=?", (idempotency_key,)).fetchone() if idempotency_key else None
                if existing and existing[1] == payload_hash:
                    return existing[0]
                if connection.execute("SELECT COUNT(*) FROM cases").fetchone()[0] >= max_records:
                    raise ValueError("Case retention quota reached. Ask an administrator to run retention maintenance.")
            cursor = connection.execute(
                f"INSERT INTO cases ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)}) "
                "ON CONFLICT(request_key) WHERE request_key IS NOT NULL DO NOTHING", [record[key] for key in columns])
            if cursor.rowcount == 0:
                existing = connection.execute("SELECT case_id, request_payload_hash FROM cases WHERE request_key = ?", (idempotency_key,)).fetchone()
                if existing is None or existing[1] != payload_hash:
                    raise ValueError("This submission key was already used for different decision data.")
                return existing[0]
        return record["case_id"]

    def list_cases(self, shipment_id: str | None = None, resolution_status: str | None = None,
                   exception_type: str | None = None, limit: int = 200, offset: int = 0) -> pd.DataFrame:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 1000:
            raise ValueError("Limit must be an integer from 1 to 1,000.")
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise ValueError("Offset must be a nonnegative integer.")
        conditions, values = [], []
        for column, value in (("shipment_id", shipment_id), ("resolution_status", resolution_status), ("exception_type", exception_type)):
            if value:
                conditions.append(column + " = ?")
                values.append(value.strip())
        query = "SELECT * FROM cases" + (" WHERE " + " AND ".join(conditions) if conditions else "")
        with self._connect() as connection:
            return pd.read_sql_query(query + " ORDER BY created_at DESC, case_id DESC LIMIT ? OFFSET ?", connection, params=values + [limit, offset])

    def export_cases(self) -> pd.DataFrame:
        """Full authorized single-organization history, never a preview limit."""
        with self._connect() as connection:
            return pd.read_sql_query("SELECT * FROM cases ORDER BY created_at DESC, case_id DESC", connection)

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
