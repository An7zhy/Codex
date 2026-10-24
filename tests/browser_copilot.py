"""Optional V2 browser acceptance. Use a separate, empty SQLite database.

The running app and this command must share LOGISTICS_DB_PATH, pointing outside
data/local/. This script deliberately saves and updates ONE synthetic case.
"""

import json
import os
import re
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = os.environ.get("APP_BASE_URL", "http://127.0.0.1:8502")


def main():
    configured = os.environ.get("LOGISTICS_DB_PATH")
    if not configured:
        raise RuntimeError("Set LOGISTICS_DB_PATH to an isolated test database, also used by the running server.")
    path = Path(configured).resolve()
    if path.is_relative_to(ROOT / "data" / "local"):
        raise RuntimeError("Use a separate test database outside data/local/.")
    output = ROOT / "artifacts" / "copilot-browser"
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        options = {"headless": True}
        if os.environ.get("BROWSER_EXECUTABLE_PATH"):
            options["executable_path"] = os.environ["BROWSER_EXECUTABLE_PATH"]
        browser = playwright.chromium.launch(**options)
        try:
            page = browser.new_page(viewport={"width": 1600, "height": 1200}, accept_downloads=True)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(BASE_URL)
            page.wait_for_load_state("networkidle")
            page.get_by_role("tab", name="Priority queue", exact=True).click()
            expect(page.get_by_role("heading", name="Explainable exception priority", exact=True)).to_be_visible()
            expect(page.get_by_text("Information needed before ranking", exact=True)).to_be_visible()
            expect(page.get_by_text("Priority queue CSV", exact=True)).to_be_visible()
            page.screenshot(path=str(output / "priority-queue.png"), full_page=True)
            print("PASS: complete priority queue, missing-information lane and explanations")

            page.get_by_role("tab", name="Case history", exact=True).click()
            expect(page.get_by_text("Database: " + str(path), exact=False)).to_be_visible()
            page.get_by_role("tab", name="Decision Center", exact=True).click()
            expect(page.get_by_text("Simulation only.", exact=False).first).to_be_visible()
            costs = page.get_by_label("Additional cost (USD)", exact=True)
            costs.nth(0).fill("123")
            costs.nth(0).press("Enter")
            page.get_by_label("Decision notes", exact=True).fill("Synthetic browser acceptance case; not an operational outcome.")
            page.get_by_role("button", name="Save decision to local history", exact=True).click()
            notice = page.get_by_text("Decision saved locally.", exact=False)
            expect(notice).to_be_visible()
            case_id = re.search(r"Case ID: ([a-f0-9]+)", notice.inner_text()).group(1)
            page.screenshot(path=str(output / "decision-center.png"), full_page=True)
            print("PASS: editable scenario inputs and explicit decision save")

            page.get_by_role("tab", name="Case history", exact=True).click()
            expect(page.get_by_text("Case history CSV", exact=True)).to_be_visible()
            page.get_by_role("combobox", name=re.compile(r"Case to update$")).click()
            page.get_by_role("option", name=re.compile(re.escape(case_id[:8]))).click()
            expect(page.get_by_text(f"Editing case {case_id}, version 1.", exact=True)).to_be_visible()
            page.get_by_role("combobox", name=re.compile(r"Update resolution status$")).click()
            page.get_by_role("option", name="Resolved", exact=True).click()
            page.get_by_label("Actual additional cost (USD, optional)", exact=True).fill("150")
            page.get_by_label("Actual delay (hours, optional)", exact=True).fill("12")
            page.get_by_label("Resolution notes", exact=True).fill("Fictional resolution supplied by browser test.")
            page.get_by_role("button", name="Update saved case", exact=True).click()
            expect(page.get_by_text("Case updated locally: " + case_id, exact=True)).to_be_visible()
            expect(page.get_by_role("combobox", name="Selected Resolved. Update resolution status", exact=True)).to_be_visible()
            page.reload()
            page.wait_for_load_state("networkidle")
            page.get_by_role("tab", name="Case history", exact=True).click()
            expect(page.get_by_label("Actual additional cost (USD, optional)", exact=True)).to_have_value("150.00")
            expect(page.get_by_label("Actual delay (hours, optional)", exact=True)).to_have_value("12.00")
            page.screenshot(path=str(output / "case-history.png"), full_page=True)
            print("PASS: actual outcomes update and survive a browser reload")

            page.get_by_role("tab", name="Evaluation", exact=True).click()
            page.get_by_role("button", name="Run synthetic comparison", exact=True).click()
            expect(page.get_by_text("V1 detection versus V2 triage", exact=True)).to_be_visible()
            with page.expect_download() as event:
                page.get_by_role("button", name="Evaluation JSON", exact=True).click()
            event.value.save_as(output / "evaluation.json")
            result = json.loads((output / "evaluation.json").read_text())
            assert result["summary"]["case_count"] == 9
            assert result["summary"]["comparable_pairs"] == 6
            page.screenshot(path=str(output / "evaluation.png"), full_page=True)
            expect(page.locator('[data-testid="stException"]')).to_have_count(0)
            assert not errors, errors
            print("PASS: reproducible comparison and actual evaluation JSON download")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
