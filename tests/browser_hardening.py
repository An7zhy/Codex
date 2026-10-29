"""Repair-specific browser acceptance; run via scripts.verify_hardening."""

import csv
from io import StringIO
import json
import os
from pathlib import Path

import pandas as pd
from playwright.sync_api import expect, sync_playwright

from scripts.audit_readiness import sample
from src.priority import PriorityConfig

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ["APP_BASE_URL"]
DOCS = ROOT / "docs/hardening"
HEADERS = {"Origin": BASE}


def main():
    evidence = {"completed": False, "checks": [], "responsive_matrix": [], "javascript_errors": []}
    expect.set_options(timeout=30000)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=os.environ.get("BROWSER_EXECUTABLE_PATH", "/usr/bin/chromium"))
        try:
            context = browser.new_context(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce")
            page = context.new_page()
            page.on("pageerror", lambda error: evidence["javascript_errors"].append(str(error)))
            assert page.request.get(BASE + "/api/workspace").status == 401
            assert page.request.get(BASE + "/api/cases/export").status == 401
            page.goto(BASE + "/app/decisions", wait_until="networkidle")
            expect(page.get_by_role("heading", name="Organization sign in")).to_be_visible()
            assert page.locator(".kpi").count() == 0
            page.get_by_label("Account name").fill(os.environ["BROWSER_TEST_USERNAME"])
            page.get_by_label("Password", exact=True).fill(os.environ["BROWSER_TEST_PASSWORD"])
            page.get_by_role("button", name="Sign in", exact=True).click()
            expect(page.get_by_label("Shipment for decision review")).to_be_visible()
            evidence["checks"].append("Anonymous direct APIs/downloads rejected; UI sign-in creates a real server session")

            page.get_by_label("Shipment for decision review").select_option("SYN-0027")
            page.get_by_role("button", name="Compare scenarios", exact=True).click()
            expect(page.get_by_label("Selected action", exact=True)).to_be_visible()
            page.get_by_label("Selected action", exact=True).select_option("Request expedited handling")
            page.locator(".scenario-card").nth(1).get_by_role("checkbox").uncheck()
            with page.expect_response(lambda r: r.url.endswith("/api/decisions/compare")):
                page.get_by_role("button", name="Compare scenarios", exact=True).click()
            expect(page.get_by_label("Selected action", exact=True)).to_have_value("Wait and monitor")
            with page.expect_response(lambda r: r.url.endswith("/api/cases") and r.request.method == "POST") as saved:
                page.get_by_role("button", name="Save decision", exact=True).click()
            assert saved.value.status == 201
            assert saved.value.request.post_data_json["selected_action"] == "Wait and monitor"
            assert saved.value.json()["selected_action"] == "Wait and monitor"
            evidence["checks"].append("PR-09: removing selected expedite resets visible/submitted/saved action consistently")

            cfg = PriorityConfig.load().to_dict(); cfg["weights"]["financial"] = 100
            cfg["expected_version"] = page.request.get(BASE + "/api/settings").json()["version"]
            changed = page.request.put(BASE + "/api/settings/priority", data=cfg, headers=HEADERS)
            assert changed.status == 200
            with page.expect_response(lambda r: r.url.endswith("/api/cases") and r.request.method == "POST") as rejected:
                page.get_by_role("button", name="Save decision", exact=True).click()
            assert rejected.value.status == 409
            expect(page.locator(".error-state")).to_contain_text("Compare scenarios again")
            page.get_by_role("button", name="Compare scenarios", exact=True).click()
            expect(page.locator(".explanation-block").first).to_contain_text("88.1481")
            with page.expect_response(lambda r: r.url.endswith("/api/cases") and r.request.method == "POST") as saved:
                page.get_by_role("button", name="Save decision", exact=True).click()
            assert saved.value.status == 201
            assert json.loads(saved.value.json()["priority_snapshot_json"])["priority_score"] == 88.1481
            for card in page.locator(".scenario-card").all():
                card.get_by_role("checkbox").uncheck()
            page.get_by_role("button", name="Compare scenarios", exact=True).click()
            expect(page.get_by_role("button", name="Save decision", exact=True)).to_be_disabled()
            evidence["checks"].append("PR-09: changed scoring context returns 409, recomparison pins the displayed/saved score, zero available actions cannot save")
            page.screenshot(path=str(DOCS / "decision-consistency.png"))

            # Explicit mixed-currency / date / duplicate preview through the UI.
            page.get_by_role("button", name="Upload data", exact=True).click()
            dialog = page.get_by_role("dialog")
            content = pd.DataFrame([sample(shipment_id="USD", currency="USD", planned_delivery="2026-10-01"),
                sample(shipment_id="EUR", currency="EUR"), sample(shipment_id="EUR", currency="EUR", status="In Transit", actual_delivery="")]).to_csv(index=False).encode()
            dialog.locator("input[type=file]").set_input_files({"name": "mixed-contract.csv", "mimeType": "text/csv", "buffer": content})
            dialog.get_by_label("Analysis date (UTC)").fill("2026-10-02")
            dialog.get_by_role("button", name="Preview import", exact=True).click()
            expect(dialog.get_by_label("Import preview")).to_contain_text("1 USD costs")
            expect(dialog.get_by_label("Import preview")).to_contain_text("2 duplicate source rows")
            expect(dialog.get_by_role("button", name="Confirm import")).to_be_disabled()
            dialog.get_by_role("checkbox").check()
            with page.expect_response(lambda r: r.url.endswith("/api/datasets") and r.request.method == "POST") as imported:
                dialog.get_by_role("button", name="Confirm import", exact=True).click()
            assert imported.value.status == 201
            dataset = imported.value.json()["dataset_id"]
            page.goto(BASE + "/app", wait_until="networkidle")
            expect(page.locator(".kpi-grid")).to_contain_text("$100.00")
            assert page.request.get(BASE + "/api/workspace", params={"dataset_id": dataset}).json()["kpis"]["cost_eligible_shipments"] == 1
            evidence["checks"].append("PR-04/05: explicit preview and confirmation, duplicate conflict disclosure, EUR excluded from USD KPI")

            # More than 500 actionable exceptions; the low-ranked tail is findable.
            content = pd.DataFrame([sample(shipment_id=f"TAIL-{i:04d}", status="In Transit", actual_delivery="") for i in range(501)]).to_csv(index=False).encode()
            multipart = {"file": {"name": "queue.csv", "mimeType": "text/csv", "buffer": content}, "as_of": "2026-10-02"}
            preview = page.request.post(BASE + "/api/datasets/preview", multipart=multipart, headers=HEADERS)
            assert preview.status == 200
            imported = page.request.post(BASE + "/api/datasets", multipart={**multipart, "confirmed": preview.json()["confirmation"]}, headers=HEADERS)
            assert imported.status == 201
            page.reload(wait_until="networkidle")
            page.get_by_label("Active dataset").select_option(imported.json()["dataset_id"])
            page.goto(BASE + "/app/decisions", wait_until="networkidle")
            expect(page.get_by_role("button", name="Next active page")).to_be_enabled()
            page.get_by_label("Find active exception ID").fill("TAIL-0500")
            expect(page.get_by_label("Shipment for decision review")).to_have_value("TAIL-0500")
            page.get_by_role("button", name="Compare scenarios", exact=True).click()
            expect(page.get_by_label("Selected action", exact=True)).to_be_visible()
            evidence["checks"].append("PR-08: 501st active exception discoverable in Decision Center and comparable via real API")

            # Viewer account: navigation/read/export work, direct forbidden requests fail.
            viewer = browser.new_context()
            login = viewer.request.post(BASE + "/api/auth/login", headers=HEADERS,
                data={"username": "browser-viewer", "password": os.environ["BROWSER_TEST_PASSWORD"]})
            assert login.status == 200
            assert viewer.request.get(BASE + "/api/exports/report").status == 200
            assert viewer.request.put(BASE + "/api/settings/priority", data=cfg, headers=HEADERS).status == 403
            assert viewer.request.post(BASE + "/api/optimization/runs", data={}, headers=HEADERS).status == 403
            assert viewer.request.delete(BASE + "/api/datasets/" + dataset, headers=HEADERS).status == 403
            view = viewer.new_page(); view.goto(BASE + "/app/settings", wait_until="networkidle")
            expect(view.get_by_role("button", name="Apply priority settings")).to_be_disabled()
            expect(view.get_by_role("button", name="Upload data")).to_be_disabled()
            viewer.close()
            evidence["checks"].append("Viewer reads/exports within its organization but server denies settings/solve/delete, independent of disabled UI controls")

            # Genuine admin deletion, then logout revokes the cookie server-side.
            page.goto(BASE + "/app/settings", wait_until="networkidle")
            page.get_by_label("Type DELETE to confirm dataset removal").fill("DELETE")
            page.get_by_role("button", name="Delete dataset and linked cases").click()
            expect(page.get_by_label("Active dataset")).to_have_value("demo")
            assert page.request.get(BASE + "/api/workspace", params={"dataset_id": imported.json()["dataset_id"]}).status == 404
            evidence["checks"].append("Admin UI deletion removes the uploaded dataset; missing ID cannot be read afterward")

            for width in (360, 393, 768, 1440):
                page.set_viewport_size({"width": width, "height": 900})
                for route in ("/app", "/app/shipments", "/app/exceptions", "/app/decisions", "/app/optimization", "/app/analytics", "/app/settings"):
                    page.goto(BASE + route, wait_until="networkidle")
                    expect(page.locator("h1").first).to_be_visible()
                    geometry = page.evaluate("({viewport:innerWidth,document:document.documentElement.scrollWidth})")
                    evidence["responsive_matrix"].append({"route": route, **geometry, "overflow": geometry["document"] > geometry["viewport"]})
            page.set_viewport_size({"width": 1440, "height": 1000})
            page.get_by_role("button", name="Sign out", exact=True).click()
            expect(page.get_by_role("heading", name="Organization sign in")).to_be_visible()
            assert page.request.get(BASE + "/api/cases").status == 401
            evidence["checks"].append("Logout invalidates server-side session; subsequent direct API read returns 401")
            assert not evidence["javascript_errors"]
            evidence["completed"] = True
        finally:
            browser.close()
            (DOCS / "browser.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence, indent=2), flush=True)


if __name__ == "__main__":
    main()
