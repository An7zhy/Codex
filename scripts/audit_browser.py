"""Audit real uploads and a cold Streamlit restart using an isolated database.

Requires requirements-dev.txt and Chromium. Run: python -m scripts.audit_browser
Never starts a server against the default user history path.
"""

from io import BytesIO
import csv
import json
import os
from pathlib import Path
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

from playwright.sync_api import expect, sync_playwright

from scripts.audit_benchmark import make_workload
from src.demo import demo_xlsx_bytes, generate_demo_data

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "audit"


def metric(page, name):
    return page.locator('[data-testid="stMetric"]').filter(has=page.get_by_text(name, exact=True)).locator('[data-testid="stMetricValue"]')


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"
    log = (OUTPUT / "server.log").open("w")
    server = None
    evidence = {"completed": False, "browser_regressions": [], "workloads": [], "input_errors": []}
    try:
        with tempfile.TemporaryDirectory(prefix="logistics-stability-browser-") as directory:
            database = Path(directory) / "audit.sqlite3"
            environment = dict(os.environ, LOGISTICS_DB_PATH=str(database), APP_BASE_URL=base_url)
            executable = os.environ.get("BROWSER_EXECUTABLE_PATH") or shutil.which("chromium")
            if executable:
                environment["BROWSER_EXECUTABLE_PATH"] = executable
            command = [sys.executable, "-m", "streamlit", "run", "app.py", "--server.address", "127.0.0.1", "--server.port", str(port), "--server.headless", "true", "--browser.gatherUsageStats", "false"]

            def start():
                process = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT)
                deadline = time.monotonic() + 40
                while time.monotonic() < deadline and process.poll() is None:
                    try:
                        with urllib.request.urlopen(base_url + "/_stcore/health", timeout=1) as response:
                            if response.status == 200 and response.read() == b"ok":
                                return process
                    except OSError:
                        pass
                    time.sleep(0.2)
                process.terminate()
                process.wait(timeout=10)
                raise RuntimeError("Isolated Streamlit server did not become healthy; see server.log.")

            def stop(process):
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)

            server = start()
            evidence["first_server_pid"] = server.pid
            for script in ("browser_smoke.py", "browser_copilot.py", "browser_parameter_changes.py"):
                result = subprocess.run([sys.executable, str(ROOT / "tests" / script)], cwd=ROOT, env=environment, capture_output=True, text=True, timeout=180)
                (OUTPUT / (script + ".log")).write_text(result.stdout + result.stderr)
                evidence["browser_regressions"].append({"script": script, "exit_code": result.returncode})
                if result.returncode:
                    raise RuntimeError(script + " failed; inspect its saved log.")
                print("PASS:", script, flush=True)
            with sqlite3.connect(database) as connection:
                saved = connection.execute("SELECT shipment_id,resolution_status,estimated_cost,actual_cost,actual_delay FROM cases").fetchall()
                assert len(saved) == 1 and saved[0][1:] == ("Resolved", 123.0, 150.0, 12.0)
                assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            stop(server)
            server = None
            server = start()
            evidence["restarted_server_pid"] = server.pid
            assert evidence["first_server_pid"] != server.pid
            with sync_playwright() as playwright:
                options = {"headless": True}
                if executable:
                    options["executable_path"] = executable
                browser = playwright.chromium.launch(**options)
                try:
                    page = browser.new_page(viewport={"width": 1500, "height": 1100}, accept_downloads=True)
                    page_errors = []
                    page.on("pageerror", lambda error: page_errors.append(str(error)))
                    page.goto(base_url)
                    page.wait_for_load_state("networkidle")
                    page.get_by_role("tab", name="Case history", exact=True).click()
                    expect(page.get_by_role("combobox", name="Selected Resolved. Update resolution status", exact=True)).to_be_visible()
                    expect(page.get_by_label("Actual additional cost (USD, optional)", exact=True)).to_have_value("150.00")
                    expect(page.get_by_label("Actual delay (hours, optional)", exact=True)).to_have_value("12.00")
                    evidence["cold_restart_history_preserved"] = True
                    print("PASS: history preserved across an actual backend process restart", flush=True)
                    page.get_by_text("Upload a file", exact=True).click()
                    for size in (100, 500, 5000):
                        raw = make_workload(size)
                        began = time.perf_counter()
                        page.locator('input[type="file"]').set_input_files({"name": f"audit-{size}.csv", "mimeType": "text/csv", "buffer": raw.to_csv(index=False).encode()})
                        page.get_by_role("tab", name="Overview", exact=True).wait_for()
                        date = page.locator('input[aria-label="Select a date."]')
                        if date.input_value() != "2026/10/01":
                            date.fill("2026/10/01")
                            date.press("Enter")
                            date.press("Tab")
                        expect(metric(page, "Total Shipments")).to_have_text(f"{size:,}", timeout=30000)
                        expect(metric(page, "Delivered Shipments")).to_have_text(f"{size // 2:,}")
                        expect(metric(page, "On-Time Delivery Rate")).to_have_text("50.0%")
                        expect(metric(page, "Overdue Shipments")).to_have_text(f"{size // 4:,}")
                        page.get_by_role("tab", name="Priority queue", exact=True).click()
                        expect(page.get_by_text(f"{size // 4} fully scored active exceptions; 0 require additional information.", exact=True)).to_be_visible(timeout=30000)
                        expect(page.get_by_role("combobox", name=re.compile(r"Explain a priority record$"))).to_be_visible(timeout=30000)
                        page.get_by_role("tab", name="Decision Center", exact=True).click()
                        expect(page.get_by_role("button", name="Save decision to local history", exact=True)).to_be_visible(timeout=30000)
                        evidence["workloads"].append({"rows": size, "upload_to_decision_ready_seconds": round(time.perf_counter()-began, 6), "kpis_verified": True})
                        expect(page.locator('[data-testid="stException"]')).to_have_count(0)
                        print("PASS: actual CSV upload and decision readiness", size, flush=True)
                    page.get_by_role("tab", name="Report & downloads", exact=True).click()
                    for label, expected_rows in (("Processed orders CSV", 5000), ("Exceptions CSV", 2500)):
                        with page.expect_download() as event:
                            page.get_by_role("button", name=label, exact=True).click()
                        target = OUTPUT / (label.replace(" ", "-") + ".csv")
                        event.value.save_as(target)
                        with target.open(encoding="utf-8-sig", newline="") as stream:
                            assert len(list(csv.DictReader(stream))) == expected_rows
                    evidence["large_download_rows_verified"] = {"processed": 5000, "exceptions": 2500}

                    damaged = BytesIO()
                    with zipfile.ZipFile(BytesIO(demo_xlsx_bytes(generate_demo_data().head(1)))) as source, zipfile.ZipFile(damaged, "w") as target:
                        for name in source.namelist():
                            target.writestr(name, b"<broken" if name == "xl/workbook.xml" else source.read(name))
                    data = make_workload(100).to_csv(index=False).strip().splitlines()
                    data[0] += ",shipping_cost"
                    for index in range(1, len(data)):
                        data[index] += ",100"
                    ragged = make_workload(4).to_csv(index=False).strip().splitlines()
                    ragged[1] += ",unexpected-extra-field"
                    for name, content, message in (("empty.csv", b"", "The file is empty."),
                        ("missing.csv", b"shipment_id\nS1\n", "Missing required columns:"),
                        ("duplicates.csv", ("\n".join(data) + "\n").encode(), "Column names must be unique"),
                        ("ragged.csv", ("\n".join(ragged) + "\n").encode(), "columns cannot be aligned safely"),
                        ("damaged.xlsx", damaged.getvalue(), "The file could not be read.")):
                        page.locator('input[type="file"]').set_input_files({"name": name, "mimeType": "application/octet-stream", "buffer": content})
                        expect(page.get_by_text(message, exact=False)).to_be_visible(timeout=30000)
                        expect(page.locator('[data-testid="stException"]')).to_have_count(0)
                        evidence["input_errors"].append({"file": name, "message": message, "handled": True})
                    raw = make_workload(100)
                    raw.loc[0, "planned_delivery"] = "invalid-date"
                    raw.loc[1, "shipping_cost"] = -5
                    raw.loc[2, "shipment_id"] = raw.loc[3, "shipment_id"]
                    page.locator('input[type="file"]').set_input_files({"name": "bad-fields.csv", "mimeType": "text/csv", "buffer": raw.to_csv(index=False).encode()})
                    expect(metric(page, "Total Shipments")).to_have_text("99", timeout=30000)
                    expect(metric(page, "On-Time Delivery Rate")).to_have_text("49.0%")
                    expect(metric(page, "Total Shipping Cost")).to_have_text("$9,800.00")
                    page.get_by_role("tab", name="Data quality", exact=True).click()
                    expect(page.get_by_text("4 selected source rows have 4 quality findings.", exact=True)).to_be_visible()
                    evidence["bad_field_kpis_verified"] = True
                    assert not page_errors, page_errors
                    evidence["completed"] = True
                    print("PASS: actionable input errors and per-row invalid date/cost/duplicate handling", flush=True)
                finally:
                    browser.close()
            stop(server)
            server = None
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)
        log.close()
        (OUTPUT / "browser.json").write_text(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
