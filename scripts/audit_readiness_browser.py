"""Bounded UI failure-path audit with isolated databases and production Next."""

import json
import os
from pathlib import Path
import tempfile

from playwright.sync_api import expect, sync_playwright

from scripts.start_web import ROOT, WebServers


def main():
    output = ROOT / "artifacts/readiness"
    output.mkdir(parents=True, exist_ok=True)
    evidence = {"audit_of_commit": "69ca7e0", "completed": False, "observations": {}}
    expect.set_options(timeout=30000)
    with tempfile.TemporaryDirectory(prefix="readiness-ui-") as folder, (output / "ui-server.log").open("w") as log:
        environment = {"LOGISTICS_WEB_DB_PATH": str(Path(folder) / "web.sqlite3"), "LOGISTICS_DB_PATH": str(Path(folder) / "cases.sqlite3")}
        with WebServers(port=3100, environment=environment, log=log):
            with sync_playwright() as w:
                browser = w.chromium.launch(headless=True, executable_path=os.environ.get("BROWSER_EXECUTABLE_PATH", "/usr/bin/chromium"))
                try:
                    page = browser.new_page(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce")
                    page.goto("http://127.0.0.1:3100/app/decisions", wait_until="networkidle")
                    page.get_by_label("Shipment for decision review").select_option("SYN-0027")
                    page.get_by_label("Wait and monitor: additional cost (USD)").fill("333")
                    page.get_by_role("button", name="Compare scenarios", exact=True).click()
                    expect(page.locator(".scenario-card").first).to_contain_text("$333.00")
                    page.get_by_role("navigation", name="Platform navigation").locator('a[href="/app/shipments"]').click()
                    expect(page).to_have_url("http://127.0.0.1:3100/app/shipments")
                    page.get_by_role("navigation", name="Platform navigation").locator('a[href="/app/decisions"]').click()
                    expect(page.get_by_label("Wait and monitor: additional cost (USD)")).to_be_visible()
                    after = page.get_by_label("Wait and monitor: additional cost (USD)").input_value()
                    evidence["observations"]["decision_route_state"] = {"applied_cost_before": 333, "input_cost_after_route_return": after,
                        "applied_result_still_rendered": page.locator(".scenario-result").count() > 0,
                        "scope": "Unsaved scenarios are component-local; saved SQLite cases are tested separately."}

                    page.get_by_role("button", name="Compare scenarios", exact=True).click()
                    expect(page.get_by_label("Selected action", exact=True)).to_be_visible()
                    page.get_by_label("Selected action", exact=True).select_option("Request expedited handling")
                    page.locator(".scenario-card").nth(1).get_by_role("checkbox").uncheck()
                    with page.expect_response(lambda r: r.url.endswith("/api/decisions/compare") and r.request.method == "POST"):
                        page.get_by_role("button", name="Compare scenarios", exact=True).click()
                    expect(page.get_by_label("Selected action", exact=True).locator("option")).to_have_count(2)
                    visible_action = page.get_by_label("Selected action", exact=True).input_value()
                    with page.expect_response(lambda r: r.url.endswith("/api/cases") and r.request.method == "POST") as save:
                        page.get_by_role("button", name="Save decision", exact=True).click()
                    evidence["observations"]["unavailable_selected_action"] = {"visible_select_value": visible_action,
                        "submitted_action": save.value.request.post_data_json["selected_action"], "http_status": save.value.status,
                        "server_detail": save.value.json().get("detail")}

                    page.goto("http://127.0.0.1:3100/app/shipments", wait_until="networkidle")
                    page.get_by_label("Filter shipment status").select_option("In Transit")
                    expect(page.locator("tbody tr").first).to_contain_text("In Transit")
                    page.reload(wait_until="networkidle")
                    evidence["observations"]["filter_reload"] = {"before": "In Transit", "after": page.get_by_label("Filter shipment status").input_value(),
                                                               "dataset_after": page.get_by_label("Active dataset").input_value()}

                    # Save an actual run so mobile Analytics/Optimization show populated paths.
                    result = page.request.post("http://127.0.0.1:3100/api/optimization/runs", data={"count": 12, "scenario_count": 100})
                    assert result.status == 201
                    coverage = []
                    evidence["observations"]["responsive_page_matrix"] = coverage
                    for width in (360, 393, 768, 1440):
                        page.set_viewport_size({"width": width, "height": 900})
                        for route in ("/app", "/app/shipments", "/app/exceptions", "/app/decisions", "/app/optimization", "/app/analytics", "/app/settings"):
                            page.goto("http://127.0.0.1:3100" + route, wait_until="networkidle")
                            expect(page.locator("h1").first).to_be_visible()
                            if route == "/app/optimization":
                                expect(page.get_by_role("heading", name="Applied allocation", exact=True)).to_be_visible()
                            geometry = page.evaluate("({viewport:innerWidth,document:document.documentElement.scrollWidth})")
                            coverage.append({"route": route, **geometry, "h1_count": page.locator("h1").count(), "horizontal_overflow": geometry["document"] > geometry["viewport"]})
                            if geometry["document"] > geometry["viewport"]:
                                page.screenshot(path=str(output / f'overflow-{width}-{route.split("/")[-1]}.png'))
                    evidence["observations"]["responsive_page_matrix"] = coverage
                    evidence["completed"] = True
                finally:
                    browser.close()
                    destination = ROOT / "docs/audit/readiness_browser.json"
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence, indent=2), flush=True)


if __name__ == "__main__":
    main()
