"""Explicit legacy input semantics; previews never guess a customer's SLA."""

import hashlib
import json

from src.analysis import analyze_shipments, calculate_kpis

RULES = {
    "version": "utc-snapshot-usd-v1",
    "columns": "Canonical English headers, UTF-8 comma-separated CSV or first XLSX worksheet; header order/case ignored.",
    "dates": "ISO only. Naive timestamps are UTC; offsets convert to UTC. Date-only means 00:00 UTC, NOT end of day. Convert local time / end-of-day promises explicitly before upload.",
    "duplicates": "Snapshot table, not an event feed. First occurrence wins; later duplicate IDs excluded. Review conflicts before confirming; no latest-event inference.",
    "currency": "USD only, no FX. If currency/shipping_currency/cost_currency is supplied, every supplied column must say USD on that row. Blank/non-USD costs excluded. Without currency metadata you confirm costs have already been converted to USD.",
    "numbers": "US number convention: 1,234 = 1234, decimal point is '.'. No automatic unit/FX conversion.",
    "context": "V2 needs additional delay/financial/dependency evidence; absent evidence remains insufficient information. V3 remains a separate synthetic scenario.",
}


def confirmation(content, as_of):
    return hashlib.sha256(content + json.dumps({"as_of": str(as_of), "rules": RULES}, sort_keys=True).encode()).hexdigest()


def preview(frame, content, as_of):
    result = analyze_shipments(frame, as_of)
    ids = frame.shipment_id.astype(str).str.strip()
    duplicated = ids.ne("") & ids.duplicated(keep=False)
    conflicts = frame.loc[duplicated].copy()
    date_counts = {}
    for name in ("planned_delivery", "actual_delivery", "shipped_at", "delivery_deadline"):
        if name in frame:
            text = frame[name].astype(str).str.strip()
            date_counts[name] = {"date_only": int(text.str.fullmatch(r"\d{4}-\d{2}-\d{2}").sum()),
                                 "naive_timestamp": int((text.str.contains(r"[Tt ]\d\d:", regex=True) & ~text.str.contains(r"(?:[zZ]|[+-]\d\d:\d\d)$", regex=True)).sum())}
    return {"confirmation": confirmation(content, as_of), "rules": RULES,
            "kpis": calculate_kpis(result.shipments), "issue_count": len(result.issues),
            "issues": json.loads(result.issues.head(20).to_json(orient="records")),
            "date_precision": date_counts, "duplicate_rows": int(duplicated.sum()),
            "conflict_preview": json.loads(conflicts.head(20).to_json(orient="records", date_format="iso")),
            "sample": json.loads(frame.head(5).to_json(orient="records", date_format="iso")),
            "preview_limit_notice": "Samples only; full quality findings and source rows remain available after confirmed import."}
