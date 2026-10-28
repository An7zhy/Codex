"""One bounded solver process per organization instance, shared across API workers."""

from contextlib import contextmanager
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid

from fastapi import HTTPException

from backend.access import AccessStore, ROOT

SOLVER_WALL_SECONDS = 45


@contextmanager
def solver_slot():
    store, token = AccessStore(), uuid.uuid4().hex
    with store.connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS solver_lease (id INTEGER PRIMARY KEY CHECK(id=1), token TEXT NOT NULL, expires REAL NOT NULL)")
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM solver_lease WHERE expires<?", (time.time(),))
        if db.execute("SELECT 1 FROM solver_lease").fetchone():
            raise HTTPException(429, "Another optimization is running in this organization. Retry shortly.", headers={"Retry-After": "45"})
        db.execute("INSERT INTO solver_lease VALUES (1,?,?)", (token, time.time() + 120))
    try:
        yield
    finally:
        with store.connect() as db:
            db.execute("DELETE FROM solver_lease WHERE token=?", (token,))


def run_bounded(body):
    if body.count * body.scenario_count > 1_000_000:
        raise HTTPException(422, "Simulation budget exceeded: orders × scenarios must be at most 1,000,000.")
    store = AccessStore()
    store.rate("solver-global", 6)
    with solver_slot(), tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        command = [sys.executable, "-m", "backend.optimizer_worker"]
        try:
            result = subprocess.run(command, input=body.model_dump_json().encode(), stdout=output, stderr=errors,
                                    cwd=ROOT, env=dict(os.environ, OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1"), timeout=SOLVER_WALL_SECONDS)
        except subprocess.TimeoutExpired as exc:
            # subprocess.run kills AND waits for this worker on timeout.
            raise HTTPException(504, "Optimization exceeded the 45-second process budget; worker stopped, no run saved.") from exc
        if result.returncode:
            raise HTTPException(400, "Optimization could not complete. Check weights and scenario inputs.")
        output.seek(0)
        return json.load(output)
