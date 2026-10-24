"""Optional real-browser acceptance checks against a running Streamlit server.

Run `python tests/browser_smoke.py` from any working directory. Requires the
optional requirements-dev.txt and Chromium (or BROWSER_EXECUTABLE_PATH).
"""

import csv
from io import StringIO
import os
from pathlib import Path
import urllib.request

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "browser"
BASE_URL = os.environ.get("APP_BASE_URL", "http://127.0.0.1:8501").rstrip("/")


def metric(page, name: str):
    return page.locator('[data-testid="stMetric"]').filter(
        has=page.get_by_text(name, exact=True)
    ).locator('[data-testid="stMetricValue"]')


def check_no_app_error(page) -> None:
    expect(page.locator('[data-testid="stException"]')).to_have_count(0)


def download(page, label: str, target: Path) -> bytes:
    with page.expect_download() as event:
        page.get_by_role("button", name=label, exact=True).click()
    artifact = event.value
    failure = artifact.failure()
    assert failure is None, f"{label} download failed: {failure}"
    artifact.save_as(target)
    return target.read_bytes()


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(BASE_URL + "/_stcore/health", timeout=10) as response:
        assert response.read() == b"ok"
    errors = []
    with sync_playwright() as playwright:
        launch_options = {"headless": True}
        if os.environ.get("BROWSER_EXECUTABLE_PATH"):
            launch_options["executable_path"] = os.environ["BROWSER_EXECUTABLE_PATH"]
        browser = playwright.chromium.launch(**launch_options)
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1600}, accept_downloads=True)
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(BASE_URL)
            page.wait_for_load_state("networkidle")
            expect(metric(page, "Total Shipments")).to_have_text("158", timeout=30000)
            expect(page.locator(".js-plotly-plot")).to_have_count(4, timeout=30000)
            # Wait for chart rendering, not merely Streamlit's initial placeholder.
            expect(page.locator(".js-plotly-plot .main-svg").first).to_be_visible()
            page.screenshot(path=str(OUTPUT / "demo-desktop.png"), full_page=True)
            check_no_app_error(page)
            print("PASS: demo dashboard, seven metrics, four rendered Plotly charts")

            # Streamlit visually hides its native radio inputs; click the visible label.
            page.get_by_text("Upload a file", exact=True).click()
            expect(page.locator('input[type="file"]')).to_have_count(1)
            for extension in ("csv", "xlsx"):
                page.locator('input[type="file"]').set_input_files(str(ROOT / "data" / f"synthetic_shipments.{extension}"))
                page.get_by_role("tab", name="Report & downloads", exact=True).wait_for()
                date_input = page.locator('input[aria-label="Select a date."]')
                date_input.fill("2026/10/01")
                date_input.press("Enter")
                date_input.press("Tab")
                expect(metric(page, "On-Time Delivery Rate")).to_have_text("47.8%", timeout=30000)
                expect(metric(page, "Total Shipments")).to_have_text("158")
                expect(metric(page, "Overdue Shipments")).to_have_text("30")
                expect(metric(page, "Cost Anomalies")).to_have_text("4")
                page.get_by_role("tab", name="Data quality", exact=True).click()
                expect(page.get_by_text("17 selected source rows have 19 quality findings.", exact=True)).to_be_visible()
                page.get_by_role("tab", name="Exceptions", exact=True).click()
                expect(page.get_by_text("Shipment exception queue", exact=True)).to_be_visible()
                page.get_by_role("tab", name="Report & downloads", exact=True).click()
                processed = download(page, "Processed orders CSV", OUTPUT / f"processed-{extension}.csv")
                exceptions = download(page, "Exceptions CSV", OUTPUT / f"exceptions-{extension}.csv")
                report = download(page, "English report", OUTPUT / f"report-{extension}.md").decode("utf-8")
                assert f"synthetic\\_shipments.{extension}" in report
                records = list(csv.DictReader(StringIO(processed.decode("utf-8-sig"))))
                exception_records = list(csv.DictReader(StringIO(exceptions.decode("utf-8-sig"))))
                assert len(records) == 160
                assert 0 < len(exception_records) <= len(records)
                assert "| Total Shipments | 158 |" in report
                assert "539,830.75" in report
                assert "## Recommended Next Actions" in report
                check_no_app_error(page)
                print(f"PASS: real {extension.upper()} upload, KPI/quality/exception views, all three downloads")

            search = page.get_by_label("Shipment ID contains", exact=True)
            search.fill("SYN-0051")
            search.press("Enter")
            expect(metric(page, "Total Shipments")).to_have_text("1")
            page.get_by_role("tab", name="Report & downloads", exact=True).click()
            report = download(page, "English report", OUTPUT / "report-filtered.md").decode("utf-8")
            assert "| Total Shipments | 1 |" in report
            assert "SYN-0051" in report
            print("PASS: filtered report uses the selected shipment only")
            search.fill("NO-MATCH")
            search.press("Enter")
            expect(metric(page, "Total Shipments")).to_have_text("0")
            check_no_app_error(page)
            search.fill("")
            search.press("Enter")
            page.locator('input[type="file"]').set_input_files({
                "name": "wrong-schema.csv", "mimeType": "text/csv", "buffer": b"wrong\nvalue\n",
            })
            expect(page.get_by_text("Missing required columns:", exact=False)).to_be_visible()
            check_no_app_error(page)
            header = (ROOT / "data" / "synthetic_shipments.csv").read_text().splitlines()[0]
            page.locator('input[type="file"]').set_input_files({
                "name": "headers-only.csv", "mimeType": "text/csv", "buffer": (header + "\n").encode(),
            })
            expect(metric(page, "Total Shipments")).to_have_text("0")
            expect(page.get_by_text("This file contains headers but no shipment rows.", exact=False)).to_be_visible()
            check_no_app_error(page)
            print("PASS: no-match filter, missing-column upload, header-only upload")

            mobile = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True)
            mobile.on("pageerror", lambda error: errors.append(str(error)))
            mobile.goto(BASE_URL)
            mobile.wait_for_load_state("networkidle")
            expect(metric(mobile, "Total Shipments")).to_have_text("158", timeout=30000)
            expect(mobile.get_by_role("heading", name="Logistics Insight AI", exact=True)).to_be_visible()
            assert mobile.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
            mobile.screenshot(path=str(OUTPUT / "demo-mobile.png"), full_page=True)
            check_no_app_error(mobile)
            print("PASS: mobile layout without page-wide horizontal overflow")
            assert not errors, errors
        finally:
            browser.close()
    print("Browser acceptance checks passed. Artifacts: " + str(OUTPUT))


if __name__ == "__main__":
    main()
