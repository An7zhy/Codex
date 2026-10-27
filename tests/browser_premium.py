"""Production-browser acceptance. Use scripts.audit_premium_web for isolated servers."""

import csv
from io import StringIO
import json
import os
from pathlib import Path
import re

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/premium-browser"
SCREENSHOTS = ROOT / "docs/images/premium"
BASE = os.environ.get("APP_BASE_URL", "http://127.0.0.1:3000")


def download(page, name, filename):
    with page.expect_download() as event:
        page.get_by_role("link", name=name, exact=True).click()
    assert event.value.failure() is None
    destination = OUTPUT / filename
    event.value.save_as(destination)
    return destination.read_text(encoding="utf-8-sig")


def navigate(page, label, path):
    page.get_by_role("navigation", name="Platform navigation", exact=True).locator(f'a[href="{path}"]').click()
    expect(page).to_have_url(BASE + path)
    expect(page.locator("h1")).to_be_visible()


def solve(page):
    with page.expect_response(lambda response: response.url.endswith("/api/optimization/runs") and response.request.method == "POST", timeout=60_000) as event:
        page.get_by_role("button", name="Run optimization", exact=True).click()
    response = event.value
    assert response.status == 201, response.text()
    run = response.json()
    expect(page.get_by_role("link", name="Replayable JSON", exact=True)).to_have_attribute(
        "href", f'/api/optimization/runs/{run["run_id"]}/export/json')
    return run


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    expect.set_options(timeout=30_000)
    evidence = {"completed": False, "checks": [], "browser": "Chromium", "server_mode": "Next.js production build + FastAPI"}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=os.environ.get("BROWSER_EXECUTABLE_PATH", "/usr/bin/chromium"))
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce", accept_downloads=True)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(BASE, wait_until="networkidle")
            expect(page.locator("h1")).to_contain_text("Intelligence")
            assert page.locator(".hero-copy").evaluate("element => getComputedStyle(element).opacity") == "1"
            assert page.locator(".lens-art").evaluate("element => getComputedStyle(element).animationName") == "none"
            page.screenshot(path=str(SCREENSHOTS / "landing-desktop.png"))
            primary = page.locator(".hero-actions .button-primary")
            expect(primary).to_have_css("background-color", "rgb(50, 104, 217)")
            expect(primary).to_have_css("color", "rgb(255, 255, 255)")
            page.keyboard.press("Tab")
            expect(page.get_by_role("link", name="Skip to content", exact=True)).to_be_focused()
            page.get_by_role("link", name="Launch platform", exact=True).first.click()
            expect(page).to_have_url(BASE + "/app")
            expect(page.get_by_text("47.8%", exact=True)).to_be_visible()
            expect(page.locator(".kpi").first).to_contain_text("158")
            page.screenshot(path=str(SCREENSHOTS / "overview-desktop.png"))
            report = download(page, "English report", "operations-report.md")
            assert "Executive Summary" in report and "Synthetic Demo Data" in report
            evidence["checks"].append("Original landing, working launch, calculated default KPIs, English report and reduced-motion fallback")
            evidence["checks"].append("Keyboard skip link and primary white-on-blue button colors (5.10:1 calculated contrast)")

            for label, path in [("Shipments", "/app/shipments"), ("Exceptions", "/app/exceptions"),
                                ("Decision Center", "/app/decisions"), ("Optimization", "/app/optimization"),
                                ("Analytics", "/app/analytics"), ("Settings", "/app/settings"), ("Overview", "/app")]:
                navigate(page, label, path)
            evidence["checks"].append("Every sidebar item changes to a distinct App Router URL")

            navigate(page, "Shipments", "/app/shipments")
            expect(page.get_by_role("heading", name="Shipment register", exact=True)).to_be_visible()
            page.get_by_label("Filter shipment status").select_option("In Transit")
            expect(page.locator("tbody tr").first).to_contain_text("In Transit")
            filtered = list(csv.DictReader(StringIO(download(page, "Export CSV", "filtered.csv"))))
            assert filtered and all(row["status"] == "In Transit" for row in filtered)
            page.get_by_role("button", name="Clear filters", exact=True).click()
            page.get_by_label("Search shipment ID").fill("DOES-NOT-EXIST")
            expect(page.get_by_text("No matching shipments", exact=True)).to_be_visible()
            page.get_by_role("button", name="Clear filters", exact=True).click()
            expect(page.get_by_role("button", name="Next shipment page")).to_be_enabled()
            page.get_by_role("button", name="Next shipment page").click()
            expect(page.locator(".table-footer")).to_contain_text("21–40")
            page.get_by_role("button", name="Inspect data quality", exact=True).click()
            expect(page.get_by_role("heading", name="Data quality findings", exact=True)).to_be_visible()
            assert len(list(csv.DictReader(StringIO(download(page, "Export findings", "quality.csv"))))) > 0
            evidence["checks"].append("Server filters, scoped exports, empty state, pagination and original field-quality findings")

            navigate(page, "Settings", "/app/settings")
            page.get_by_label("Potential financial impact weight", exact=True).fill("100")
            page.get_by_role("button", name="Apply priority settings", exact=True).click()
            expect(page.get_by_role("status")).to_contain_text("Priority settings saved")
            navigate(page, "Exceptions", "/app/exceptions")
            rationale = page.get_by_label("Exception rationale shipment")
            rationale.select_option(rationale.locator("option").filter(has_text="SYN-0027").get_attribute("value"))
            expect(page.locator(".explanation-block")).to_contain_text("88.1481")
            navigate(page, "Overview", "/app")
            expect(page.get_by_text("47.8%", exact=True)).to_be_visible()
            evidence["checks"].append("Saved financial weight 20→100 changes SYN-0027 score to 88.1481 without changing V1 KPIs")

            navigate(page, "Decision Center", "/app/decisions")
            page.get_by_label("Shipment for decision review").select_option("SYN-0027")
            page.get_by_label("Wait and monitor: additional cost (USD)").fill("450")
            page.get_by_label("Wait and monitor: remaining hours").fill("48")
            page.get_by_role("button", name="Compare scenarios", exact=True).click()
            expect(page.locator(".scenario-card").first).to_contain_text("24.0h late")
            page.get_by_label("Wait and monitor: additional cost (USD)").fill("900")
            expect(page.get_by_text("Draft edits are not applied.", exact=False)).to_be_visible()
            expect(page.locator(".scenario-card").first).to_contain_text("$450.00")
            page.get_by_label("Decision notes").fill("Premium web browser acceptance")
            page.get_by_role("button", name="Save decision", exact=True).click()
            expect(page.get_by_role("status")).to_contain_text("Decision saved")
            page.get_by_role("button", name="Save decision", exact=True).click()
            page.get_by_role("link", name="Handling history", exact=True).first.click()
            expect(page).to_have_url(BASE + "/app/decisions/history")
            expect(page.locator("tbody tr")).to_have_count(1)
            expect(page.locator("tbody tr").first).to_contain_text("$450.00")
            page.get_by_role("button", name="Update case SYN-0027").click()
            page.get_by_label("Resolution status", exact=True).select_option("Resolved")
            page.get_by_label("Actual additional cost (USD)", exact=True).fill("470")
            page.get_by_label("Actual delay (hours)", exact=True).fill("20")
            page.get_by_label("Resolution notes", exact=True).fill("Browser verified outcome")
            page.get_by_role("button", name="Save outcome", exact=True).click()
            expect(page.get_by_role("status")).to_contain_text("outcome updated")
            page.reload(wait_until="networkidle")
            expect(page.locator("tbody tr").first).to_contain_text("Resolved")
            expect(page.locator("tbody tr").first).to_contain_text("$470.00")
            page.screenshot(path=str(SCREENSHOTS / "history-desktop.png"))
            evidence["checks"].append("V2 cost/time arithmetic, draft vs applied saving, idempotent saves and edited outcomes survive reload")

            navigate(page, "Optimization", "/app/optimization")
            solve(page)
            expect(page.get_by_role("heading", name="Applied allocation", exact=True)).to_be_visible(timeout=60_000)
            original = json.loads(download(page, "Replayable JSON", "v3-default.json"))
            assert all(row["status"] == "OPTIMAL" for row in original["summary"])
            assert len(original["results"]["Optimized Allocation"]["assignments"]) == 12
            assert len(list(csv.DictReader(StringIO(download(page, "Allocation CSV", "allocation.csv"))))) == 12
            page.get_by_label("Planning shipment", exact=True).select_option("PLAN-0001")
            expect(page.get_by_text("Expected arrival exceeds hard deadline", exact=True)).to_be_visible()
            page.get_by_role("heading", name="Applied allocation", exact=True).scroll_into_view_if_needed()
            page.screenshot(path=str(SCREENSHOTS / "optimization-desktop.png"))

            page.get_by_label("Budget allowance (%)", exact=True).fill("0")
            solve(page)
            expect(page.locator(".toast")).to_contain_text("INFEASIBLE", timeout=60_000)
            failed = json.loads(download(page, "Replayable JSON", "v3-infeasible.json"))
            assert all(row["total_shipping_cost_usd"] is None for row in failed["summary"])
            page.get_by_label("Allow unassigned orders with an explicit penalty", exact=True).check()
            solve(page)
            expect(page.get_by_text("No orders assigned", exact=True)).to_be_visible(timeout=60_000)
            soft = json.loads(download(page, "Replayable JSON", "v3-soft.json"))
            assert all(row["unassigned_orders"] == 12 for row in soft["summary"])
            page.get_by_label("Allow unassigned orders with an explicit penalty", exact=True).uncheck()
            page.get_by_label("Budget allowance (%)", exact=True).fill("100")
            page.get_by_label("Synthetic planning orders", exact=True).select_option("100")
            solve(page)
            expect(page.locator(".toast")).to_contain_text("Allocation evaluated", timeout=60_000)
            large = json.loads(download(page, "Replayable JSON", "v3-100.json"))
            assert all(row["status"] in ("OPTIMAL", "FEASIBLE") and row["assigned_orders"] == 100 for row in large["summary"])
            evidence["checks"].append("V3 hard eligibility, real OR-Tools allocation, infeasible/soft modes, exports and actual 100-order browser solve")
            evidence["hundred_order_statuses"] = {row["strategy"]: row["status"] for row in large["summary"]}

            navigate(page, "Analytics", "/app/analytics")
            expect(page.get_by_role("heading", name="Expected versus simulated transit", exact=True)).to_be_visible()
            expect(page.get_by_text("PLAN-0001", exact=True)).to_be_visible()
            page.get_by_role("button", name="Run rule evaluation", exact=True).click()
            expect(page.get_by_role("columnheader", name="Reference case", exact=True)).to_be_visible()
            page.screenshot(path=str(SCREENSHOTS / "analytics-desktop.png"))
            evidence["checks"].append("Analytics uses saved V3 Monte Carlo results and original V2 reference evaluation")

            # Actual CSV and Excel uploads, followed by persisted dataset selection.
            for filename in ("synthetic_shipments.csv", "synthetic_shipments.xlsx"):
                page.get_by_role("button", name="Upload data", exact=True).click()
                dialog = page.get_by_role("dialog")
                dialog.locator('input[type=file]').set_input_files(str(ROOT / "data" / filename))
                dialog.get_by_label("Analysis date (UTC)").fill("2026-10-01")
                with page.expect_response(lambda response: response.url.endswith("/api/datasets") and response.request.method == "POST") as uploaded:
                    dialog.get_by_role("button", name="Upload and analyze", exact=True).click()
                dataset_id = uploaded.value.json()["dataset_id"]
                expect(dialog).not_to_be_visible()
                navigate(page, "Overview", "/app")
                expect(page.get_by_text("47.8%", exact=True)).to_be_visible()
                page.reload(wait_until="networkidle")
                expect(page.get_by_label("Active dataset")).to_have_value(dataset_id)
                expect(page.locator(".kpi").first).to_contain_text("158")
            page.get_by_role("button", name="Upload data", exact=True).click()
            dialog = page.get_by_role("dialog")
            dialog.locator('input[type=file]').set_input_files({"name": "bad.csv", "mimeType": "text/csv", "buffer": b"wrong,columns\n1,2\n"})
            dialog.get_by_role("button", name="Upload and analyze", exact=True).click()
            expect(dialog.get_by_role("alert")).to_contain_text("Missing required columns")
            dialog.get_by_role("button", name="Close upload").click()
            page.get_by_label("Active dataset").select_option("demo")
            evidence["checks"].append("Real CSV/Excel uploads, source labeling, selection persistence and actionable malformed-file error")

            # Restore defaults so the screenshots and cold-restart check use a known configuration.
            navigate(page, "Settings", "/app/settings")
            page.get_by_label("Potential financial impact weight", exact=True).fill("20")
            page.get_by_role("button", name="Apply priority settings", exact=True).click()
            expect(page.get_by_role("status")).to_contain_text("Priority settings saved")
            evidence["javascript_errors"] = errors
            assert not errors, errors

            mobile = browser.new_page(viewport={"width": 393, "height": 852}, reduced_motion="reduce", is_mobile=True, has_touch=True)
            mobile.on("pageerror", lambda error: errors.append(str(error)))
            mobile.goto(BASE, wait_until="networkidle")
            assert mobile.evaluate("document.documentElement.scrollWidth <= innerWidth")
            mobile.screenshot(path=str(SCREENSHOTS / "landing-mobile.png"))
            mobile.get_by_role("link", name="Launch platform", exact=True).first.click()
            expect(mobile).to_have_url(BASE + "/app")
            expect(mobile.get_by_role("heading", name="Operational overview", exact=True)).to_be_visible()
            expect(mobile.locator(".kpi").first).to_contain_text("158")
            expect(mobile.locator(".kpi-grid")).to_contain_text("47.8%")
            assert mobile.evaluate("document.documentElement.scrollWidth <= innerWidth")
            mobile.screenshot(path=str(SCREENSHOTS / "overview-mobile.png"))
            mobile.get_by_role("button", name="Open navigation", exact=True).click()
            drawer = mobile.get_by_role("dialog")
            drawer.get_by_role("link", name="Shipments", exact=True).click()
            expect(mobile).to_have_url(BASE + "/app/shipments")
            expect(drawer).not_to_be_visible()
            assert mobile.evaluate("document.documentElement.scrollWidth <= innerWidth")
            evidence["checks"].append("393px mobile landing/platform, accessible navigation drawer and no document-level horizontal overflow")

            # Loading and API-error states are exercised without taking the real API down.
            isolated = browser.new_page(viewport={"width": 1200, "height": 850})
            isolated.on("pageerror", lambda error: errors.append(str(error)))
            isolated.route("**/api/workspace?*", lambda route: route.fulfill(status=503, content_type="application/json", body='{"detail":"Test API temporarily unavailable"}'))
            isolated.goto(BASE + "/app", wait_until="networkidle")
            expect(isolated.locator(".error-state")).to_contain_text("Test API temporarily unavailable")
            expect(isolated.get_by_role("button", name="Try again", exact=True)).to_be_visible()
            evidence["checks"].append("API failure shows an actionable error state rather than invented or stale KPIs")
            loading_page = browser.new_page()
            loading_page.on("pageerror", lambda error: errors.append(str(error)))
            paused = []
            loading_page.route("**/api/workspace?*", lambda route: paused.append(route))
            loading_page.goto(BASE + "/app", wait_until="domcontentloaded")
            expect(loading_page.get_by_label("Loading calculated results")).to_be_visible()
            for _ in range(60):
                if paused:
                    break
                loading_page.wait_for_timeout(50)
            assert paused, "The actual workspace request was not intercepted."
            for route in paused:
                route.continue_()
            expect(loading_page.get_by_text("47.8%", exact=True)).to_be_visible()
            evidence["checks"].append("A delayed real workspace request shows a loading skeleton, then calculated KPIs")
            stale = browser.new_page()
            stale.on("pageerror", lambda error: errors.append(str(error)))
            stale.add_init_script("localStorage.setItem('logistics-workspace-v1',JSON.stringify({datasetId:'missing-after-folder-update',asOf:'2026-10-01'}))")
            stale.goto(BASE + "/app", wait_until="networkidle")
            expect(stale.locator(".error-state")).to_contain_text("Dataset not found")
            stale.get_by_role("button", name="Use Synthetic Demo Data", exact=True).click()
            expect(stale.locator(".kpi-grid")).to_contain_text("47.8%")
            evidence["checks"].append("A remembered dataset missing after a folder/database update can be explicitly reset to the demo")
            assert not errors, errors
            evidence["completed"] = True
        finally:
            browser.close()
            (ROOT / "docs/premium_browser_evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence, indent=2), flush=True)


if __name__ == "__main__":
    main()
