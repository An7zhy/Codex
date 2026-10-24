"""Real-browser acceptance for the user's unchanged-results report. No DB writes."""

import csv
from io import StringIO
import json
import os
from pathlib import Path
import re

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "parameter-interactions"
BASE_URL = os.environ.get("APP_BASE_URL", "http://127.0.0.1:8502")


def download(page, label, filename):
    with page.expect_download() as event:
        page.get_by_role("button", name=label, exact=True).click()
    assert event.value.failure() is None
    event.value.save_as(OUTPUT / filename)
    return (OUTPUT / filename).read_text(encoding="utf-8-sig")


def score(rows, shipment_id):
    return float(next(row["priority_score"] for row in rows if row["shipment_id"] == shipment_id))


def select_shipment(page, shipment_id):
    control = page.get_by_role("combobox", name=re.compile(r"Shipment for decision review$"))
    control.click()
    control.fill(shipment_id)
    page.get_by_role("option", name=shipment_id, exact=True).click()
    expect(page.get_by_role("combobox", name=f"Selected {shipment_id}. Shipment for decision review", exact=True)).to_be_visible()
    expect(scenario_form(page, shipment_id)).to_be_visible()


def scenario_form(page, shipment_id):
    return page.locator('[data-testid="stForm"]').filter(has=page.get_by_text(f"Scenario inputs for {shipment_id}.", exact=True))


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    evidence = {"completed": False}
    with sync_playwright() as playwright:
        settings = {"headless": True}
        if os.environ.get("BROWSER_EXECUTABLE_PATH"):
            settings["executable_path"] = os.environ["BROWSER_EXECUTABLE_PATH"]
        browser = playwright.chromium.launch(**settings)
        try:
            page = browser.new_page(viewport={"width": 1600, "height": 1400}, accept_downloads=True)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(BASE_URL)
            page.wait_for_load_state("networkidle")
            page.get_by_role("tab", name="Priority queue", exact=True).click()
            before = list(csv.DictReader(StringIO(download(page, "Priority queue CSV", "priority-before.csv"))))
            assert abs(score(before, "SYN-0027") - 78.6667) < 0.0001
            page.get_by_role("tab", name="Decision Center", exact=True).click()
            select_shipment(page, "SYN-0159")
            scenario_form(page, "SYN-0159").get_by_label("Additional cost (USD)", exact=True).nth(0).fill("333")
            scenario_form(page, "SYN-0159").get_by_role("button", name="Recalculate scenarios", exact=True).click()
            expect(page.get_by_text("Scenario assumptions applied for shipment SYN-0159.", exact=False)).to_be_visible()
            expect(page.get_by_text("Applied comparison for SYN-0159 — Wait and monitor: USD 333.00", exact=False)).to_be_visible()
            custom = list(csv.DictReader(StringIO(download(page, "Scenario comparison CSV", "comparison-custom-before-weights.csv"))))
            assert float(custom[0]["estimated_additional_cost_usd"]) == 333

            page.get_by_role("tab", name="Priority queue", exact=True).click()
            page.get_by_text("Configure priority rules", exact=True).click()
            page.get_by_label("Financial weight", exact=True).fill("100")
            # Explicit submission must work with no Enter key or separate blur.
            page.get_by_role("button", name="Apply priority settings", exact=True).click()
            expect(page.get_by_text("Priority settings applied.", exact=False)).to_be_visible()
            expect(page.get_by_text("Applied priority result: top shipment SYN-0027, score 88.1481.", exact=True)).to_be_visible()
            after = list(csv.DictReader(StringIO(download(page, "Priority queue CSV", "priority-after.csv"))))
            assert abs(score(after, "SYN-0027") - 88.1481) < 0.0001
            ordering = lambda rows: [row["shipment_id"] for row in sorted((row for row in rows if row["priority_score"]), key=lambda row: float(row["priority_score"]), reverse=True)]
            assert ordering(before) != ordering(after)
            evidence["same_shipment_score"] = {"shipment_id": "SYN-0027", "financial_weight_before": 20, "financial_weight_after": 100,
                                                "score_before": score(before, "SYN-0027"), "score_after": score(after, "SYN-0027")}
            evidence["ranking_changed"] = True
            page.get_by_role("tab", name="Decision Center", exact=True).click()
            expect(page.get_by_role("combobox", name="Selected SYN-0159. Shipment for decision review", exact=True)).to_be_visible()
            preserved = list(csv.DictReader(StringIO(download(page, "Scenario comparison CSV", "comparison-preserved.csv"))))
            assert float(preserved[0]["estimated_additional_cost_usd"]) == 333
            evidence["selection_and_assumptions_preserved"] = True

            select_shipment(page, "SYN-0027")
            initial = list(csv.DictReader(StringIO(download(page, "Scenario comparison CSV", "comparison-before.csv"))))
            assert abs(float(initial[0]["estimated_delay_hours"]) - 72) < 0.0001
            scenario_form(page, "SYN-0027").get_by_label("Additional cost (USD)", exact=True).nth(0).fill("450")
            scenario_form(page, "SYN-0027").get_by_label("Remaining time (hours)", exact=True).nth(0).fill("48")
            scenario_form(page, "SYN-0027").get_by_role("button", name="Recalculate scenarios", exact=True).click()
            expect(page.get_by_text("Scenario assumptions applied for shipment SYN-0027.", exact=False)).to_be_visible()
            expect(page.get_by_text("Applied comparison for SYN-0027 — Wait and monitor: USD 450.00, 48.0h", exact=False)).to_be_visible()
            changed = list(csv.DictReader(StringIO(download(page, "Scenario comparison CSV", "comparison-after.csv"))))
            assert float(changed[0]["estimated_additional_cost_usd"]) == 450
            assert abs(float(changed[0]["estimated_delay_hours"]) - 24) < 0.0001
            evidence["scenario_before_after"] = {"shipment_id": "SYN-0027", "remaining_before": 96, "remaining_after": 48,
                                                   "delay_before": float(initial[0]["estimated_delay_hours"]), "delay_after": float(changed[0]["estimated_delay_hours"]), "cost_after": 450}
            scenario_form(page, "SYN-0027").get_by_label("Additional cost (USD)", exact=True).nth(0).fill("900")
            scenario_form(page, "SYN-0027").get_by_role("button", name="Recalculate scenarios", exact=True).click()
            expect(page.get_by_text("Scenario assumptions applied for shipment SYN-0027.", exact=False)).to_be_visible()
            expect(page.get_by_text("Applied comparison for SYN-0027 — Wait and monitor: USD 900.00, 48.0h", exact=False)).to_be_visible()
            price_only = list(csv.DictReader(StringIO(download(page, "Scenario comparison CSV", "comparison-price-only.csv"))))
            assert float(price_only[0]["estimated_additional_cost_usd"]) == 900
            assert abs(float(price_only[0]["estimated_delay_hours"]) - 24) < 0.0001
            evidence["cost_is_not_implicitly_a_time_model"] = True

            page.get_by_role("tab", name="Evaluation", exact=True).click()
            page.get_by_role("button", name="Run synthetic comparison", exact=True).click()
            expect(page.get_by_text("Evaluation applied weights: urgency=30, delay=25, financial=100, value=10, downstream=15", exact=True)).to_be_visible()
            current = json.loads(download(page, "Evaluation JSON", "evaluation-before.json"))
            assert current["summary"]["config"]["weights"]["financial"] == 100
            page.get_by_role("tab", name="Priority queue", exact=True).click()
            page.get_by_label("Financial weight", exact=True).fill("20")
            page.get_by_role("button", name="Apply priority settings", exact=True).click()
            expect(page.get_by_text("Priority settings applied.", exact=False)).to_be_visible()
            page.get_by_role("tab", name="Evaluation", exact=True).click()
            expect(page.get_by_text("Evaluation applied weights: urgency=30, delay=25, financial=20, value=10, downstream=15", exact=True)).to_be_visible()
            refreshed = json.loads(download(page, "Evaluation JSON", "evaluation-after.json"))
            assert refreshed["summary"]["config"]["weights"]["financial"] == 20
            evidence["evaluation_refreshed_without_rerun_button"] = True
            expect(page.locator('[data-testid="stException"]')).to_have_count(0)
            assert not errors, errors
            evidence["completed"] = True
            print("PASS: typed weights change scores/rankings; selected shipment and scenario inputs persist")
            print("PASS: typed costs/times recalculate; evaluation refreshes using applied weights")
        finally:
            browser.close()
            (OUTPUT / "evidence.json").write_text(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
