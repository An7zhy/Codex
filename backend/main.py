"""FastAPI adapter: original V1–V3 calculations, local persistent workspaces."""

from dataclasses import asdict
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile, Request
from fastapi.responses import JSONResponse, Response
from fastapi.exceptions import RequestValidationError
import pandas as pd

from backend.schemas import (DecisionRequest, OptimizationRequest, PrioritySettings,
                             SaveCaseRequest, UpdateCaseRequest)
from backend.store import WorkspaceStore
from backend.access import AccessStore, COOKIE
from backend.boundary import SecurityBoundary
from backend.import_contract import preview, confirmation
from pydantic import BaseModel, Field, ConfigDict
from src.analysis import analyze_shipments, calculate_kpis, carrier_performance, exception_shipments
from src.decisions import ActionAssumption, compare_actions, default_assumptions
from src.demo import demo_xlsx_bytes, generate_demo_data
from src.evaluation import run_evaluation
from src.exports import csv_bytes
from src.history import CaseInput, HistoryStore
from src.ingestion import MAX_FILE_BYTES, load_shipments
from src.priority import PriorityConfig, active_exception, delivery_deadline, prioritize_shipments
from src.reporting import RuleBasedReportGenerator
from src.schema import KPI_DEFINITIONS

ROOT = Path(__file__).resolve().parents[1]
app = FastAPI(title="Logistics Insight AI", version="1.1.0", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SecurityBoundary)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


@app.post("/api/auth/login")
def login(body: LoginRequest, response: Response, request: Request):
    store = AccessStore()
    token = store.login(body.username, body.password)
    # Re-login rotates and revokes the previous session in this browser.
    store.logout(request.cookies.get(COOKIE))
    response.set_cookie(COOKIE, token, max_age=8 * 3600, httponly=True,
                        secure=os.environ.get("LOGISTICS_COOKIE_SECURE", "0") == "1", samesite="strict", path="/api")
    store.event(body.username, "LOGIN", "/api/auth/login", 200)
    return store.authenticate(token)


@app.get("/api/auth/session")
def session(request: Request):
    return request.state.principal


@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    AccessStore().logout(request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE, path="/api")
    return {"signed_out": True}


@app.get("/api/ready")
def ready():
    AccessStore().check_binding()
    for store in (workspace_store(), history_store()):
        path = store.path
        with sqlite3.connect(path, timeout=2) as db:
            db.execute("SELECT 1").fetchone()
    return {"status": "ready"}


def workspace_store():
    return WorkspaceStore(os.environ.get("LOGISTICS_WEB_DB_PATH", str(ROOT / "data/local/web_workspace.sqlite3")))


def history_store():
    return HistoryStore(os.environ.get("LOGISTICS_DB_PATH", str(ROOT / "data/local/exception_history.sqlite3")))


def records(frame):
    return json.loads(frame.to_json(orient="records", date_format="iso"))


@app.exception_handler(ValueError)
async def invalid_input(request, exc):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(RequestValidationError)
async def invalid_request(request, exc):
    # Pydantic's default errors include raw inputs (including bad passwords).
    return JSONResponse(status_code=422, content={"detail": [
        {"loc": list(item["loc"]), "type": item["type"], "msg": item["msg"]} for item in exc.errors()
    ]})


@app.exception_handler(LookupError)
async def missing_record(request, exc):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(sqlite3.Error)
async def database_error(request, exc):
    return JSONResponse(status_code=503, content={"detail": "Local storage is unavailable. Check the data directory and retry."})


class Scope:
    def __init__(self, dataset_id: str = "demo", as_of: date | None = None, carrier: str = "",
                 mode: str = "", status: str = "", q: str = Query(default="", max_length=200),
                 offset: int = Query(default=0, ge=0), limit: int = Query(default=50, ge=1, le=500)):
        self.store = workspace_store()
        self.metadata, raw = self.store.dataset(dataset_id)
        self.result = analyze_shipments(raw, as_of or self.metadata["as_of"])
        self.full = self.result.shipments
        self.frame = self.full
        self.filters = {"carrier": carrier, "transport_mode": mode, "status": status, "shipment_id": q}
        for column, value in self.filters.items():
            if value:
                self.frame = self.frame.loc[self.frame[column].str.contains(value, case=False, regex=False, na=False)] if column == "shipment_id" else self.frame.loc[self.frame[column].eq(value)]
        self.issues = self.result.issues.loc[self.result.issues.source_row.isin(self.frame.source_row)]
        self.config = PriorityConfig(**self.store.setting("priority", PriorityConfig.load().to_dict()))
        self.priorities = prioritize_shipments(self.frame, self.result.cutoff, self.config)
        self.offset, self.limit = offset, limit


Scoped = Annotated[Scope, Depends()]


@app.get("/api/health")
def health():
    return {"status": "ok", "product": "Logistics Insight AI", "mode": "Local engineering prototype"}


@app.get("/api/datasets")
def datasets():
    return workspace_store().datasets()


@app.delete("/api/datasets/{dataset_id}")
def delete_dataset(dataset_id: str):
    if dataset_id == "demo":
        raise HTTPException(400, "The synthetic demo cannot be deleted.")
    store = workspace_store()
    store.dataset(dataset_id)  # 404 for a missing ID, before any deletion.
    history = history_store()
    with store.connect() as db:
        db.execute("ATTACH DATABASE ? AS history", (str(history.path),))
        db.execute("DELETE FROM history.cases WHERE json_valid(priority_snapshot_json) AND json_extract(priority_snapshot_json,'$.dataset.dataset_id')=?", (dataset_id,))
        db.execute("DELETE FROM web_datasets WHERE dataset_id=?", (dataset_id,))
    return {"deleted": dataset_id, "linked_web_cases_deleted": True, "notice": "Backups are separate; apply the documented backup expiration policy."}


async def uploaded_frame(request, file):
    form = await request.form()
    if len([value for _, value in form.multi_items() if hasattr(value, "filename")]) != 1:
        raise HTTPException(400, "Exactly one file part is allowed per request.")
    content = await file.read(MAX_FILE_BYTES + 1)
    frame = load_shipments(content, file.filename or "upload.csv")
    return content, frame


@app.post("/api/datasets/preview")
async def preview_dataset(request: Request, file: Annotated[UploadFile, File()], as_of: Annotated[date, Form()]):
    content, frame = await uploaded_frame(request, file)
    return preview(frame, content, as_of)


@app.post("/api/datasets", status_code=201)
async def upload_dataset(request: Request, file: Annotated[UploadFile, File()], as_of: Annotated[date | None, Form()] = None,
                         confirmed: Annotated[str, Form()] = ""):
    content, frame = await uploaded_frame(request, file)
    day = str(as_of or datetime.now(timezone.utc).date())
    if not confirmed or confirmed != confirmation(content, day):
        raise HTTPException(409, "Preview this exact file/date and confirm the UTC, currency and duplicate rules before importing.")
    store = workspace_store()
    dataset_id = store.save_dataset(frame, Path(file.filename or "Uploaded file").name, False,
                                    day)
    metadata, _ = store.dataset(dataset_id)
    return metadata


@app.get("/api/workspace")
def workspace(scope: Scoped):
    frame, included = scope.frame, scope.frame.loc[scope.frame.included_in_analysis]
    priorities = scope.priorities.copy()
    priorities["actionable"] = [active_exception(row) for row in priorities.to_dict("records")]
    queue = priorities.loc[priorities.is_exception].sort_values("priority_score", ascending=False, na_position="last")
    statuses = included.status.value_counts().rename_axis("status").reset_index(name="count")
    costs = included.loc[included.valid_cost].groupby("transport_mode").shipping_cost.agg(["mean", "count"]).reset_index()
    routes = included.groupby(["origin", "destination"]).size().reset_index(name="shipments").sort_values("shipments", ascending=False)
    return {"dataset": scope.metadata, "as_of": str(scope.result.as_of), "cutoff": scope.result.cutoff.isoformat(),
            "kpis": calculate_kpis(frame), "definitions": KPI_DEFINITIONS,
            "filters": {column: sorted(scope.full[column].unique().tolist()) for column in ("carrier", "transport_mode", "status")},
            "shipments": records(priorities.iloc[scope.offset:scope.offset + scope.limit]),
            "total_rows": len(frame), "offset": scope.offset, "limit": scope.limit,
            "exceptions": records(queue.head(500)), "exception_count": len(queue), "exception_preview_limit": 500,
            "issues": records(scope.issues.head(500)), "issue_count": len(scope.issues),
            "charts": {"statuses": records(statuses), "carriers": records(carrier_performance(frame)),
                       "costs": records(costs), "routes": records(routes.head(10)),
                       "delays": records(included.loc[included.is_delayed].nlargest(10, "delay_hours")[["shipment_id", "carrier", "delay_hours"]])},
            "priority_config": scope.config.to_dict(), "scope": scope.filters}


@app.get("/api/exceptions")
def exception_queue(scope: Scoped, actionable_only: bool = False):
    queue = scope.priorities.loc[scope.priorities.is_exception].copy()
    queue["actionable"] = [active_exception(row) for row in queue.to_dict("records")]
    if actionable_only:
        queue = queue.loc[queue.actionable]
    queue = queue.sort_values(["priority_score", "source_row"], ascending=[False, True], na_position="last")
    return {"items": records(queue.iloc[scope.offset:scope.offset + scope.limit]), "total": len(queue),
            "offset": scope.offset, "limit": scope.limit}


@app.get("/api/exports/{kind}")
def export(kind: Literal["shipments", "exceptions", "priority", "report", "quality"], scope: Scoped):
    if kind == "report":
        source = ("Synthetic Demo Data — " if scope.metadata["synthetic"] else "User-provided, unverified provenance — ") + scope.metadata["name"]
        text = RuleBasedReportGenerator().generate(scope.frame, scope.issues, scope.result.as_of, source,
                                                  json.dumps(scope.filters))
        return Response(text, media_type="text/markdown", headers={"Content-Disposition": 'attachment; filename="logistics_report.md"'})
    frame = {"shipments": scope.frame, "exceptions": exception_shipments(scope.frame),
             "priority": scope.priorities, "quality": scope.issues}[kind]
    return Response(csv_bytes(frame), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{kind}.csv"'})


@app.get("/api/demo/{kind}")
def demo_download(kind: Literal["csv", "xlsx"]):
    data = generate_demo_data()
    return Response(csv_bytes(data) if kind == "csv" else demo_xlsx_bytes(data),
                    media_type="text/csv" if kind == "csv" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="synthetic_shipments.{kind}"'})


@app.get("/api/settings")
def settings():
    return {"priority": workspace_store().setting("priority", PriorityConfig.load().to_dict()),
            "capabilities": {"analysis": "Existing deterministic V1 rules", "triage": "Existing explainable V2 rules",
                             "optimizer": "Existing Google OR-Tools CP-SAT V3 model", "storage": "Local SQLite",
                             "live_tracking": False, "paid_api_required": False}}


@app.put("/api/settings/priority")
def update_priority(body: PrioritySettings):
    config = PriorityConfig(**body.model_dump())
    workspace_store().save_setting("priority", config.to_dict())
    return config.to_dict()


def decision_comparison(body):
    store = workspace_store()
    metadata, raw = store.dataset(body.dataset_id)
    analysis = analyze_shipments(raw, body.as_of)
    config = store.setting("priority", PriorityConfig.load().to_dict())
    priorities = prioritize_shipments(analysis.shipments, analysis.cutoff, PriorityConfig(**config))
    rows = priorities.loc[priorities.shipment_id.eq(body.shipment_id) & priorities.included_in_analysis]
    if rows.empty:
        raise LookupError("Shipment not found in this dataset.")
    row = rows.iloc[0]
    if not active_exception(row):
        raise ValueError("Decision scenarios require an active In Transit exception with no actual delivery.")
    deadline, source = delivery_deadline(row)
    comparison = compare_actions(analysis.cutoff, deadline, [ActionAssumption(**item.model_dump()) for item in body.assumptions])
    token = hashlib.sha256(json.dumps({"dataset": metadata, "config": config,
        "as_of": str(body.as_of), "shipment": body.shipment_id,
        "assumptions": [item.model_dump() for item in body.assumptions]}, sort_keys=True).encode()).hexdigest()
    return row, comparison, analysis, metadata, deadline, source, token


@app.get("/api/decisions/defaults")
def decision_defaults():
    return [asdict(item) for item in default_assumptions()]


@app.post("/api/decisions/compare")
def compare_decisions(body: DecisionRequest):
    row, comparison, analysis, metadata, deadline, source, token = decision_comparison(body)
    similar = history_store().similar_cases(row.origin, row.destination, row.transport_mode,
                                            row.exception_types.split("; ")[0], row.shipment_id)
    return {"shipment_id": row.shipment_id, "comparison": records(comparison), "comparison_token": token,
            "priority_score": None if pd.isna(row.priority_score) else float(row.priority_score),
            "priority_level": row.priority_level, "explanation": row.explanation,
            "missing_information": row.missing_information,
            "cutoff": analysis.cutoff.isoformat(), "deadline": deadline.isoformat() if deadline is not None else None,
            "deadline_source": source, "similar_cases": records(similar),
            "provenance": "Editable simulation assumptions, not prices or carrier commitments."}


@app.post("/api/cases", status_code=201)
def create_case(body: SaveCaseRequest, request: Request):
    row, comparison, analysis, metadata, deadline, _, token = decision_comparison(body)
    if body.comparison_token != token:
        raise HTTPException(409, "The dataset or scoring configuration changed. Compare scenarios again before saving.")
    if body.exception_type not in row.exception_types.split("; "):
        raise ValueError("Exception type must be an observed exception for this shipment.")
    selected = comparison.loc[comparison.action.eq(body.selected_action) & comparison.assumed_available]
    if selected.empty:
        raise ValueError("Choose an available action from the applied comparison.")
    chosen = selected.iloc[0]
    snapshot = {"priority_score": None if pd.isna(row.priority_score) else float(row.priority_score),
                "priority_level": row.priority_level, "details": json.loads(row.priority_details_json), "dataset": metadata,
                "comparison_token": token, "actor": request.state.principal["username"]}
    case = CaseInput(row.shipment_id, body.exception_type, body.selected_action,
                     estimated_cost=float(chosen.estimated_additional_cost_usd),
                     estimated_delay=None if pd.isna(chosen.estimated_delay_hours) else float(chosen.estimated_delay_hours),
                     resolution_notes=body.resolution_notes, origin=row.origin, destination=row.destination,
                     transport_mode=row.transport_mode, carrier=row.carrier, analysis_date=str(analysis.as_of),
                     assumptions_json=json.dumps({"comparison": records(comparison), "cutoff": analysis.cutoff.isoformat(),
                                                   "deadline": deadline.isoformat() if deadline is not None else None}, allow_nan=False),
                     priority_snapshot_json=json.dumps(snapshot, allow_nan=False))
    fingerprint = hashlib.sha256(json.dumps(asdict(case), sort_keys=True, allow_nan=False).encode()).hexdigest()
    store = history_store()
    try:
        case_id = store.create_case(case, idempotency_key="web:" + fingerprint, max_records=10000)
    except ValueError as exc:
        if str(exc).startswith("Case retention quota"):
            raise HTTPException(507, str(exc)) from exc
        raise
    return store.get_case(case_id)


@app.get("/api/cases")
def cases(shipment_id: str = "", resolution_status: str = "", exception_type: str = "", limit: int = Query(default=200, ge=1, le=1000), offset: int = Query(default=0, ge=0)):
    return records(history_store().list_cases(shipment_id or None, resolution_status or None, exception_type or None, limit, offset))


@app.get("/api/cases/export")
def cases_export():
    return Response(csv_bytes(history_store().export_cases()), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="case_history.csv"'})


@app.patch("/api/cases/{case_id}")
def update_case(case_id: str, body: UpdateCaseRequest):
    store = history_store()
    try:
        store.update_case(case_id, **body.model_dump())
    except ValueError as exc:
        if "changed in another session" in str(exc):
            raise HTTPException(409, str(exc)) from exc
        raise
    return store.get_case(case_id)


@app.get("/api/evaluation")
def evaluation():
    config = PriorityConfig(**workspace_store().setting("priority", PriorityConfig.load().to_dict()))
    return json.loads(run_evaluation(config).json_bytes())


@app.post("/api/optimization/runs", status_code=201)
def optimization(body: OptimizationRequest):
    from backend.runtime import run_bounded
    payload = run_bounded(body)
    store = workspace_store()
    run_id = store.save_run(json.dumps(payload, allow_nan=False))
    return store.run(run_id)


@app.get("/api/optimization/runs/latest")
def latest_optimization():
    return workspace_store().run()


@app.delete("/api/optimization/runs/{run_id}")
def delete_optimization(run_id: str):
    store = workspace_store()
    store.run(run_id)
    with store.connect() as db:
        db.execute("DELETE FROM web_runs WHERE run_id=?", (run_id,))
    return {"deleted": run_id}


@app.get("/api/optimization/runs/{run_id}")
def optimization_run(run_id: str):
    return workspace_store().run(run_id)


@app.get("/api/optimization/runs/{run_id}/export/{kind}")
def optimization_export(run_id: str, kind: Literal["json", "comparison", "allocation", "candidates"]):
    run = workspace_store().run(run_id)
    if kind == "json":
        # The original V3 CLI ignores additional web metadata and recomputes inputs.
        return Response(json.dumps(run, indent=2, allow_nan=False), media_type="application/json",
                        headers={"Content-Disposition": 'attachment; filename="v3_experiment.json"'})
    table = run["summary"] if kind == "comparison" else run["candidate_checks"] if kind == "candidates" else run["results"]["Optimized Allocation"]["assignments"]
    return Response(csv_bytes(pd.DataFrame(table)), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="v3_{kind}.csv"'})
