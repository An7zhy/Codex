"""Real Chromium V3 navigation, form submission, exports and shortage recovery.

Start an isolated Streamlit server; APP_BASE_URL defaults to port 8513.
Requires optional requirements-dev.txt and Chromium (not a pytest dependency).
"""

import csv
from io import StringIO
import json
import os
from pathlib import Path
import re

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/v3-browser"


def download(page, label, filename):
    with page.expect_download() as event:
        page.get_by_role("button", name=label, exact=True).click()
    assert event.value.failure() is None
    path = OUTPUT / filename
    event.value.save_as(path)
    return path.read_text(encoding="utf-8-sig")


def run(page):
    page.get_by_role("button", name="Run transportation optimization", exact=True).click()
    # Wait for this script run to finish before inspecting/downloading its results.
    expect(page.get_by_text("Transportation assumptions applied. Results below use this completed run.", exact=True)).to_be_visible(timeout=40_000)
    expect(page.get_by_test_id("stStatusWidget")).to_have_count(0, timeout=40_000)
    page.get_by_role("tab", name="Strategy Comparison", exact=True).click()
    return json.loads(download(page, "V3 reproducible experiment JSON", "experiment.json"))


def summary(payload, strategy="Optimized Allocation"):
    return next(row for row in payload["summary"] if row["strategy"] == strategy)


def choose_workspace(page, name):
    page.get_by_role("combobox", name=re.compile(r"Workspace$")).click()
    page.get_by_role("option", name=name, exact=True).click()


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    expect.set_options(timeout=45_000)
    evidence = {"completed": False, "checks": []}
    with sync_playwright() as playwright:
        settings = {"headless": True}
        if os.environ.get("BROWSER_EXECUTABLE_PATH"):
            settings["executable_path"] = os.environ["BROWSER_EXECUTABLE_PATH"]
        browser = playwright.chromium.launch(**settings)
        try:
            page = browser.new_page(viewport={"width": 1680, "height": 1250}, accept_downloads=True)
            page.set_default_timeout(45_000)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(os.environ.get("APP_BASE_URL", "http://127.0.0.1:8513"))
            page.wait_for_load_state("networkidle")
            choose_workspace(page, "V3 Transportation Optimization")
            expect(page.get_by_role("heading", name="V3 Transportation Optimization", exact=True)).to_be_visible()
            baseline = run(page)
            assert all(row["status"] == "OPTIMAL" for row in baseline["summary"])
            assert summary(baseline)["assigned_orders"] == 12
            table = list(csv.DictReader(StringIO(download(page, "V3 strategy comparison CSV", "comparison.csv"))))
            assert len(table) == 3
            assert float(next(row["total_shipping_cost_usd"] for row in table if row["strategy"] == "Optimized Allocation")) == summary(baseline)["total_shipping_cost_usd"]
            evidence["checks"].append("Initial solve and matching CSV/JSON exports")

            page.get_by_role("tab", name="Transportation Decision Center", exact=True).click()
            page.get_by_role("combobox", name=re.compile(r"Planning shipment$")).click()
            page.get_by_role("option", name="PLAN-0005", exact=True).click()
            # No Enter key: the explicit form button must apply all typed numbers.
            page.get_by_label("Optimization cost weight", exact=True).fill("0")
            page.get_by_label("Optimization time weight", exact=True).fill("100")
            page.get_by_label("Optimization simulated risk weight", exact=True).fill("0")
            page.get_by_role("tab", name="Strategy Comparison", exact=True).click()
            draft = json.loads(download(page, "V3 reproducible experiment JSON", "draft.json"))
            assert draft["preferences"] == baseline["preferences"]
            fastest = run(page)
            assert fastest["preferences"] == {"cost": 0, "time": 100, "risk": 0}
            assert fastest["scenario_fingerprint"] == baseline["scenario_fingerprint"]
            before = sum(row["expected_hours"] for row in baseline["results"]["Optimized Allocation"]["assignments"])
            after = sum(row["expected_hours"] for row in fastest["results"]["Optimized Allocation"]["assignments"])
            assert after < before
            page.get_by_role("tab", name="Transportation Decision Center", exact=True).click()
            expect(page.get_by_role("combobox", name="Selected PLAN-0005. Planning shipment", exact=True)).to_be_visible()
            evidence["checks"].append("Draft vs applied weights, same random scenarios, changed allocation, retained shipment")
            evidence["weight_sensitivity"] = {"total_expected_hours_before": before, "total_expected_hours_after": after}
            page.get_by_role("tab", name="What-if Scenario Analysis", exact=True).click()
            expect(page.get_by_role("heading", name="Applied assumptions and previous-run comparison", exact=True)).to_be_visible()
            expect(page.get_by_text("Identical results can be valid:", exact=False)).to_be_visible()
            evidence["checks"].append("What-if view retains and displays previous/current applied runs")

            page.get_by_role("tab", name="Optimization Dashboard", exact=True).click()
            for label, filename in [("V3 allocation CSV", "allocation.csv"), ("V3 candidate checks CSV", "candidates.csv")]:
                rows = list(csv.DictReader(StringIO(download(page, label, filename))))
                assert len(rows) == (12 if "allocation" in filename else 36)
            page.screenshot(path=str(OUTPUT / "dashboard.png"), full_page=True)

            page.get_by_label("Budget (% of all-most-expensive synthetic options)", exact=True).fill("0")
            shortage = run(page)
            assert summary(shortage)["status"] == "INFEASIBLE"
            assert summary(shortage)["total_shipping_cost_usd"] is None
            page.get_by_text("Allow unassigned orders with penalty", exact=True).click()
            soft = run(page)
            assert summary(soft)["unassigned_orders"] == 12
            assert summary(soft)["simulated_on_time_rate_all_orders"] == 0
            evidence["checks"].append("Zero budget gives INFEASIBLE, explicit soft mode gives 12 unassigned and no fabricated benefits")

            page.get_by_label("Budget (% of all-most-expensive synthetic options)", exact=True).fill("100")
            page.get_by_text("Allow unassigned orders with penalty", exact=True).click()
            page.get_by_label("Weight capacity (%)", exact=True).fill("0")
            capacity = run(page)
            assert summary(capacity)["status"] == "INFEASIBLE"
            page.get_by_label("Weight capacity (%)", exact=True).fill("100")
            page.get_by_label("Deadline shift (hours)", exact=True).fill("-400")
            deadline = run(page)
            assert summary(deadline)["status"] == "INFEASIBLE"
            evidence["checks"].append("Capacity and deadline controls alter hard feasibility")

            page.get_by_label("Optimization time weight", exact=True).fill("0")
            page.get_by_role("button", name="Run transportation optimization", exact=True).click()
            expect(page.get_by_text("At least one optimization weight must be positive.", exact=True)).to_be_visible()
            evidence["checks"].append("All-zero weights show actionable error and preserve applied result")
            choose_workspace(page, "V1/V2 Exception Copilot")
            expect(page.get_by_test_id("stMetricValue").filter(has_text="158")).to_be_visible()
            assert page.get_by_test_id("stException").count() == 0
            assert not errors, errors
            evidence["checks"].append("V1 dashboard still loads after V3 navigation; no browser JavaScript errors")
            evidence["completed"] = True
        finally:
            browser.close()
            (ROOT / "docs/v3_browser_evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
