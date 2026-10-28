"""Authenticated uploaded-input workflow; security boundary applies to this router."""

import csv
import hashlib
import json
from pathlib import Path
from typing import Literal
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile

import pandas as pd
from defusedxml.common import DefusedXmlException
from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from starlette.datastructures import UploadFile

from backend.access import paths
from backend.runtime import run_bounded
from backend.store import WorkspaceStore
from src.exports import csv_bytes
from src.ingestion import MAX_FILE_BYTES
from src.transport.engine import candidate_table
from src.transport.input_contract import HEADERS, LIMITS, POLICY, FIELD_NOTES, SCHEMA_VERSION, read_tables, validate_tables
from src.transport.models import Candidate, Constraints, Order, PlanningData, Preferences, Service
from src.transport.templates import template_tables, workbook_bytes

router = APIRouter(prefix="/api/planning")


def store():
    return WorkspaceStore(paths()[0])


class Confirmation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    confirmation: str = Field(min_length=64, max_length=64)
    acknowledged: StrictBool


class SolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    import_id: str = Field(pattern=r"^[a-f0-9]{32}$")


@router.get("/contract")
def contract():
    return {"schema": SCHEMA_VERSION, "headers": HEADERS, "limits": LIMITS, "policy": POLICY,
            "fields": {table: {name: FIELD_NOTES[name] for name in names} for table, names in HEADERS.items()}}


@router.get("/templates/{kind}")
def template(kind: Literal["xlsx", "shipments", "transport_options", "capacity", "constraints"], count: int = Query(default=2, ge=0, le=100)):
    tables = template_tables(count)
    return Response(workbook_bytes(tables) if kind == "xlsx" else csv_bytes(tables[kind]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if kind == "xlsx" else "text/csv",
        headers={"Content-Disposition": f'attachment; filename="planning_{kind}_{count}.{"xlsx" if kind == "xlsx" else "csv"}"',
                 "X-Data-Provenance": "Synthetic editable template; not real carrier data"})


@router.get("/imports")
def imports():
    return store().planning_imports()


@router.post("/imports/preview", status_code=201)
async def preview(request: Request):
    # Keep the SAME 20 MiB whole-body, receive-time and upload-rate guard as V1.
    async with request.form(max_files=4, max_fields=0, max_part_size=MAX_FILE_BYTES) as form:
        parts = list(form.multi_items())
        if not parts or len(parts) != len(set(key for key, _ in parts)) or any(not isinstance(value, UploadFile) for _, value in parts):
            raise HTTPException(400, "Supply one workbook or four distinct named CSV file parts; no other fields.")
        files = {key: (Path(value.filename or "upload").name, await value.read(MAX_FILE_BYTES + 1)) for key, value in parts}
    manifest = [{"part": key, "filename": name, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
                for key, (name, content) in files.items()]
    tables = {}
    try:
        tables = read_tables(files)
        validation = validate_tables(tables)
    except (ValueError, csv.Error, BadZipFile, OSError, KeyError, ParseError, DefusedXmlException) as exc:
        validation = dict(valid=False, error_count=1, errors=[dict(table="files", row=0, field="format", message=str(exc))], warnings=[], payload=None)
    candidate_preview = {}
    if validation["valid"]:
        payload = validation["payload"]
        data = PlanningData(tuple(Order(**row) for row in payload["data"]["orders"]), tuple(Service(**row) for row in payload["data"]["services"]), tuple(Candidate(**row) for row in payload["data"]["candidates"]))
        checks = candidate_table(data, Constraints(**payload["constraints"]), Preferences(**payload["preferences"]))
        candidate_preview = {"individually_eligible": int(checks.eligible.sum()), "candidate_count": len(checks),
            "excluded_sample": json.loads(checks.loc[~checks.eligible, ["shipment_id", "service_id", "rejection_reasons"]].head(20).to_json(orient="records")),
            "notice": "Individual checks only. Shared capacity/budget feasibility requires the solver."}
    record = dict(schema=SCHEMA_VERSION, files=manifest, policy=POLICY, validation=validation, candidate_preview=candidate_preview,
                  tables={name: json.loads(frame.to_json(orient="records", date_format="iso")) for name, frame in tables.items()},
                  row_counts={name: len(frame) for name, frame in tables.items()})
    return store().save_import(record, request.state.principal["username"])


@router.get("/imports/{import_id}")
def imported(import_id: str):
    return store().planning_import(import_id)


@router.post("/imports/{import_id}/confirm")
def confirm(import_id: str, body: Confirmation, request: Request):
    if not body.acknowledged:
        raise HTTPException(400, "Review and acknowledge the input and reliability policy before confirming.")
    return store().confirm_import(import_id, body.confirmation, request.state.principal["username"])


@router.get("/imports/{import_id}/export/{kind}")
def export_import(import_id: str, kind: Literal["json", "shipments", "transport_options", "capacity", "constraints"]):
    item = store().planning_import(import_id)
    if kind == "json":
        return Response(json.dumps(item, indent=2, allow_nan=False), media_type="application/json",
                        headers={"Content-Disposition": 'attachment; filename="planning_import_audit.json"'})
    frame = pd.DataFrame(item["record"]["tables"].get(kind, []), columns=HEADERS[kind])
    return Response(csv_bytes(frame), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{kind}.csv"'})


@router.delete("/imports/{import_id}")
def delete_import(import_id: str):
    storage = store(); storage.planning_import(import_id)
    with storage.connect() as db:
        db.execute("DELETE FROM web_runs WHERE json_extract(payload_json,'$.planning_import.import_id')=?", (import_id,))
        db.execute("DELETE FROM planning_imports WHERE import_id=?", (import_id,))
    return {"deleted": import_id, "linked_runs_deleted": True}


@router.post("/runs", status_code=201)
def solve(body: SolveRequest, request: Request):
    storage = store()
    item = storage.planning_import(body.import_id)
    if item["status"] != "confirmed":
        raise HTTPException(409, "Confirm a valid planning import before solving.")
    payload = {**item["record"]["validation"]["payload"], "input_tables": item["record"]["tables"]}
    result = run_bounded(body, uploaded_payload=payload)
    result["planning_import"] = {key: item[key] for key in ("import_id", "created_at", "created_by", "confirmed_at", "confirmed_by", "confirmation")}
    result["planning_import"]["files"] = item["record"]["files"]
    result["solved_by"] = request.state.principal["username"]
    result["source_info"]["input_warnings"] = item["record"]["validation"]["warnings"]
    result["input_tables"] = item["record"]["tables"]
    for row in result["summary"]:
        row["import_id"] = body.import_id
    for rows in [result["candidate_checks"], *[entry["assignments"] for entry in result["results"].values()]]:
        for row in rows:
            row["import_id"] = body.import_id
    run_id = storage.save_run(json.dumps(result, allow_nan=False), planning_import_id=body.import_id)
    return storage.run(run_id)
