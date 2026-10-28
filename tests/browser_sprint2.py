"""Real browser validation of uploaded inputs, source-aware results and retained drafts."""

import csv
from io import StringIO
import json
import os
from pathlib import Path
import sys
import time

from playwright.sync_api import expect, sync_playwright

from src.transport.templates import template_tables, workbook_bytes

BASE = os.environ["APP_BASE_URL"]
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/sprint2"
EVIDENCE = ROOT / "docs/sprint2/uploaded_flow.json"


def navigate(page, path):
    page.get_by_role("navigation", name="Platform navigation").locator(f'a[href="{path}"]').click()
    expect(page).to_have_url(BASE + path)


def login(page):
    page.goto(BASE + "/app/optimization", wait_until="networkidle")
    page.get_by_label("Account name").fill(os.environ["BROWSER_TEST_USERNAME"])
    page.get_by_label("Password", exact=True).fill(os.environ["BROWSER_TEST_PASSWORD"])
    page.get_by_role("button", name="Sign in", exact=True).click()
    expect(page.get_by_label("Optimization input mode")).to_be_visible()


def upload(page, tables, *, csv_mode=False):
    page.get_by_label("Planning file format").select_option("csv" if csv_mode else "xlsx")
    if csv_mode:
        for name, frame in tables.items():
            page.get_by_label(f"Planning {name} file").set_input_files({"name": name + ".csv", "mimeType": "text/csv", "buffer": frame.to_csv(index=False).encode()})
    else:
        page.get_by_label("Planning workbook file").set_input_files({"name":"planning.xlsx", "mimeType":"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "buffer":workbook_bytes(tables)})
    with page.expect_response(lambda r: r.url.endswith("/api/planning/imports/preview") and r.request.method == "POST") as response:
        page.get_by_role("button", name="Preview planning inputs", exact=True).click()
    assert response.value.status == 201
    item = response.value.json()
    expect(page.get_by_label("Planning input preview")).to_contain_text(item["import_id"])
    return item


def confirm_and_solve(page):
    preview = page.get_by_label("Planning input preview")
    preview.get_by_role("checkbox").check()
    page.get_by_role("button", name="Confirm planning inputs", exact=True).click()
    expect(page.get_by_role("button", name="Solve uploaded plan", exact=True)).to_be_enabled()
    with page.expect_response(lambda r: r.url.endswith("/api/planning/runs") and r.request.method == "POST", timeout=60000) as solved:
        page.get_by_role("button", name="Solve uploaded plan", exact=True).click()
    assert solved.value.status == 201, solved.value.text()
    run = solved.value.json()
    expect(page.get_by_role("heading", name="Applied allocation", exact=True)).to_be_visible()
    return run


def downloaded(page, label, destination):
    with page.expect_download() as event:
        page.get_by_role("link", name=label, exact=True).click()
    assert event.value.failure() is None
    path = OUTPUT / destination; event.value.save_as(path)
    return path.read_bytes()


def main():
    expect.set_options(timeout=30000)
    evidence = {"completed":False,"checks":[],"javascript_errors":[],"responsive_matrix":[]}
    with sync_playwright() as w:
        browser = w.chromium.launch(headless=True, executable_path=os.environ.get("BROWSER_EXECUTABLE_PATH","/usr/bin/chromium"))
        try:
            page = browser.new_page(viewport={"width":1440,"height":1000}, reduced_motion="reduce", accept_downloads=True)
            page.on("pageerror",lambda error:evidence["javascript_errors"].append(str(error)))
            if "--restart-check" in sys.argv:
                original = json.loads(EVIDENCE.read_text())
                login(page)
                item = page.request.get(BASE+f'/api/planning/imports/{original["hundred_order_import"]}').json()
                run = page.request.get(BASE+f'/api/optimization/runs/{original["hundred_order_run"]}').json()
                assert item["status"] == "confirmed" and item["confirmed_by"] == os.environ["BROWSER_TEST_USERNAME"]
                assert [row["total_shipping_cost_usd"] for row in run["summary"]] == [6000,9000,6000]
                original["restart_source_and_results_preserved"] = True
                EVIDENCE.write_text(json.dumps(original,indent=2))
                return
            assert page.request.get(BASE+"/api/planning/templates/xlsx").status == 401
            login(page)
            session_started = time.monotonic()
            page.get_by_label("Optimization input mode").select_option("uploaded")
            expect(page.get_by_role("heading",name="Uploaded transportation inputs",exact=True)).to_be_visible()
            template = downloaded(page,"100-order synthetic workbook","100-template.xlsx")
            assert len(template)>1000
            bad = template_tables(); bad["transport_options"].loc[0,"currency"]="EUR"
            invalid = upload(page,bad,csv_mode=True)
            assert invalid["status"] == "invalid"
            expect(page.get_by_label("Planning input preview")).to_contain_text("currency")
            assert page.get_by_role("button", name="Confirm planning inputs",exact=True).count()==0
            evidence["checks"].append("Four-CSV upload persists field errors; EUR is rejected with no confirmation/solve path")
            item = upload(page,template_tables(100))
            assert item["record"]["row_counts"]["shipments"] == 100
            expect(page.get_by_role("button",name="Confirm planning inputs",exact=True)).to_be_disabled()
            page.reload(wait_until="networkidle")
            expect(page.get_by_label("Planning input preview")).to_contain_text(item["import_id"])
            expect(page.get_by_label("Planning workbook file")).to_have_value("")
            started = time.perf_counter()
            run = confirm_and_solve(page)
            confirmation_and_solve_seconds = time.perf_counter() - started
            assert [row["total_shipping_cost_usd"] for row in run["summary"]]==[6000,9000,6000]
            assert all(row["status"]=="OPTIMAL" and row["assigned_orders"]==100 for row in run["summary"])
            assert run["scenario_count"]==0 and run["simulation_details"]=={}
            allocation = list(csv.DictReader(StringIO(downloaded(page,"Allocation CSV","uploaded-allocation.csv").decode("utf-8-sig"))))
            assert len(allocation)==100 and sum(float(row["cost_usd"]) for row in allocation)==6000
            assert all(row["import_id"]==item["import_id"] and row["assumed_late_probability"]=="" for row in allocation)
            exported=json.loads(downloaded(page,"Input & results JSON","uploaded-results.json"))
            assert exported["planning_import"]["files"]==item["record"]["files"]
            assert exported["source_info"]["data_kind"]=="synthetic_test"
            evidence.update(hundred_order_import=item["import_id"],hundred_order_run=run["run_id"], hundred_order_costs={r["strategy"]:r["total_shipping_cost_usd"] for r in run["summary"]}, hundred_order_statuses={r["strategy"]:r["status"] for r in run["summary"]})
            evidence.update(confirmation_and_solve_browser_seconds=confirmation_and_solve_seconds, solver_experiment_seconds=run["elapsed_seconds"])
            evidence["checks"].append("100-template-order Excel preview/confirmation/real worker solve/full CSV+JSON exports match independent 6000/9000/6000 calculation")
            page.reload(wait_until="networkidle")
            expect(page.get_by_role("heading",name="Applied allocation",exact=True)).to_be_visible()
            page.get_by_role("link",name="Explore analytics",exact=True).click()
            expect(page).to_have_url(BASE+f'/app/analytics?run_id={run["run_id"]}')
            expect(page.get_by_role("heading",name="Uploaded-input strategy comparison",exact=True)).to_be_visible()
            assert page.get_by_role("heading",name="Expected versus simulated transit",exact=True).count()==0
            expect(page.get_by_role("heading",name="Input sources and limitations",exact=True)).to_be_visible()
            evidence["checks"].append("Explore analytics pins the selected allocation run ID in the URL instead of silently switching to another latest run")
            evidence["checks"].append("Uploaded results survive refresh; Analytics shows source declarations and no invented Monte Carlo/reliability")

            navigate(page,"/app/shipments")
            page.get_by_label("Filter shipment status").select_option("In Transit")
            expect(page.locator("tbody tr").first).to_contain_text("In Transit")
            page.reload(wait_until="networkidle")
            expect(page.get_by_label("Filter shipment status")).to_have_value("In Transit")
            navigate(page,"/app/decisions")
            page.get_by_label("Shipment for decision review").select_option("SYN-0027")
            page.get_by_label("Wait and monitor: additional cost (USD)").fill("333")
            page.get_by_role("button",name="Compare scenarios",exact=True).click()
            expect(page.locator(".scenario-card").first).to_contain_text("$333.00")
            page.get_by_label("Decision notes").fill("Sprint 2 retained draft")
            page.get_by_label("Wait and monitor: additional cost (USD)").fill("444")
            navigate(page,"/app/shipments");navigate(page,"/app/decisions")
            expect(page.get_by_label("Wait and monitor: additional cost (USD)")).to_have_value("444")
            expect(page.get_by_label("Decision notes")).to_have_value("Sprint 2 retained draft")
            expect(page.locator(".scenario-card").first).to_contain_text("$333.00")
            page.reload(wait_until="networkidle")
            expect(page.get_by_label("Wait and monitor: additional cost (USD)")).to_have_value("444")
            expect(page.get_by_label("Decision notes")).to_have_value("Sprint 2 retained draft")
            with page.expect_response(lambda r:r.url.endswith("/api/cases") and r.request.method=="POST") as saved:
                page.get_by_role("button",name="Save decision",exact=True).click()
            assert saved.value.status==201 and saved.value.json()["estimated_cost"]==333
            evidence["checks"].append("Shipment filter survives refresh; decision selection/draft/notes/applied result survive navigation+reload; saving still uses333 applied not444 draft")
            page.get_by_role("link",name="Handling history",exact=True).first.click()
            page.get_by_role("button",name="Update case SYN-0027").click()
            page.get_by_label("Actual additional cost (USD)",exact=True).fill("123")
            page.get_by_label("Resolution notes",exact=True).fill("Unsaved outcome retained in this tab")
            navigate(page,"/app/shipments");navigate(page,"/app/decisions")
            page.get_by_role("link",name="Handling history",exact=True).first.click()
            expect(page.get_by_label("Actual additional cost (USD)",exact=True)).to_have_value("123")
            page.reload(wait_until="networkidle")
            expect(page.get_by_label("Resolution notes",exact=True)).to_have_value("Unsaved outcome retained in this tab")
            assert page.request.get(BASE+"/api/cases").json()[0]["actual_cost"] is None
            evidence["checks"].append("Unsaved historical outcome inputs survive route changes and refresh without silently updating SQLite")
            navigate(page,"/app/settings")
            page.get_by_label("Potential financial impact weight",exact=True).fill("77")
            navigate(page,"/app/shipments");navigate(page,"/app/settings")
            expect(page.get_by_label("Potential financial impact weight",exact=True)).to_have_value("77")
            assert page.request.get(BASE+"/api/settings").json()["priority"]["weights"]["financial"]==20
            navigate(page,"/app/optimization")
            page.get_by_label("Optimization input mode").select_option("synthetic")
            page.get_by_label("Budget allowance (%)",exact=True).fill("73")
            navigate(page,"/app/analytics");navigate(page,"/app/optimization")
            expect(page.get_by_label("Budget allowance (%)",exact=True)).to_have_value("73")
            page.get_by_label("Optimization input mode").select_option("uploaded")
            expect(page.get_by_label("Planning input preview")).to_contain_text(item["import_id"])
            evidence["checks"].append("Unsaved Settings and synthetic optimization parameters retained without changing server settings; modes restore their own context")

            infeasible=template_tables();infeasible["constraints"].loc[0,"budget"]="100"
            upload(page,infeasible)
            failed=confirm_and_solve(page)
            assert all(row["status"]=="INFEASIBLE" and row["total_shipping_cost_usd"] is None for row in failed["summary"])
            expect(page.get_by_text("No assignment satisfies all constraints.",exact=False)).to_be_visible()
            assert page.get_by_role("heading",name="Recommended batch assignments",exact=True).count()==0
            evidence["checks"].append("Infeasible shared-capacity/budget combination displays original diagnostics with no fabricated allocation or savings")

            viewer=browser.new_context()
            logged=viewer.request.post(BASE+"/api/auth/login",headers={"Origin":BASE},data={"username":"sprint2-viewer","password":os.environ["BROWSER_TEST_PASSWORD"]})
            assert logged.status==200
            assert viewer.request.get(BASE+"/api/planning/templates/xlsx?count=100").status==200
            for path in ("/api/planning/runs","/api/planning/imports/preview",f'/api/planning/imports/{item["import_id"]}/confirm'):
                assert viewer.request.post(BASE+path,headers={"Origin":BASE},data={}).status==403
            assert viewer.request.delete(BASE+f'/api/planning/imports/{item["import_id"]}',headers={"Origin":BASE}).status==403
            viewer.close();evidence["checks"].append("Anonymous template access401; authenticated viewer exports allowed but direct upload/confirm/solve/delete403")
            # Automation navigates much faster than an operator. Respect the
            # unchanged 180/min/account budget instead of disabling the boundary.
            wait_seconds = max(0, 65 - (time.monotonic() - session_started))
            if wait_seconds:
                page.wait_for_timeout(min(wait_seconds, 60) * 1000)
            for width in (360,393,768,1440):
                page.set_viewport_size({"width":width,"height":900})
                for path in ("/app","/app/shipments","/app/exceptions","/app/decisions","/app/optimization","/app/analytics","/app/settings"):
                    page.goto(BASE+path,wait_until="networkidle")
                    expect(page.locator("h1").first).to_be_visible()
                    geometry=page.evaluate("({width:innerWidth,document:document.documentElement.scrollWidth})")
                    evidence["responsive_matrix"].append({"route":path,**geometry})
                    assert geometry["document"]<=geometry["width"], (path,geometry)
            evidence["checks"].append("28 populated page/width combinations have no document overflow, including Exceptions360/393 and uploaded planning")
            page.set_viewport_size({"width":1440,"height":1000})
            page.get_by_role("button",name="Sign out",exact=True).click()
            expect(page.get_by_role("heading",name="Organization sign in")).to_be_visible()
            assert page.evaluate("Object.keys(sessionStorage).filter(k=>k.startsWith('logistics-draft:')).length")==0
            assert page.request.get(BASE+"/api/planning/imports").status==401
            evidence["checks"].append("Logout clears tab draft caches and revokes server access; actor/instance-scoped storage never supplies API authorization")
            assert not evidence["javascript_errors"]
            evidence["completed"]=True
        finally:
            browser.close()
            if "--restart-check" not in sys.argv:
                EVIDENCE.write_text(json.dumps(evidence,indent=2))
    print(json.dumps(evidence,indent=2))


if __name__=="__main__":main()
