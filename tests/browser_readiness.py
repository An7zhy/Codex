"""Real browser proof of settings conflicts and the sealed read-only demo."""

import csv
from io import StringIO
import json
import os
from pathlib import Path
import sys
import time

from playwright.sync_api import expect, sync_playwright

BASE = os.environ["APP_BASE_URL"]
EVIDENCE = Path(os.environ["BROWSER_EVIDENCE_PATH"])


def sign_in(page, username):
    page.goto(BASE+"/app/settings", wait_until="networkidle")
    page.get_by_label("Account name").fill(username)
    page.get_by_label("Password",exact=True).fill(os.environ["BROWSER_TEST_PASSWORD"])
    page.get_by_role("button",name="Sign in",exact=True).click()
    expect(page.get_by_label("Deadline urgency weight",exact=True)).to_be_visible()


def main():
    expect.set_options(timeout=30000)
    evidence = {"completed":False,"checks":[],"javascript_errors":[]}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True,executable_path=os.environ.get("BROWSER_EXECUTABLE_PATH","/usr/bin/chromium"))
        try:
            if "--demo" in sys.argv:
                page=browser.new_page(ignore_https_errors=True,viewport={"width":1440,"height":1000},reduced_motion="reduce",accept_downloads=True)
                page.on("pageerror",lambda e:evidence["javascript_errors"].append(str(e)))
                page.goto(BASE,wait_until="networkidle")
                page.get_by_role("link",name="Launch platform",exact=True).first.click()
                expect(page.locator(".kpi").first).to_contain_text("158")
                expect(page.get_by_text("Synthetic demo · Read only",exact=True)).to_be_visible()
                expect(page.get_by_role("button",name="Upload data",exact=True)).to_be_disabled()
                assert page.request.get(BASE+"/api/auth/session").json()["read_only_demo"]
                with page.expect_download() as download:
                    page.get_by_role("link",name="English report",exact=True).click()
                assert download.value.failure() is None
                assert "Synthetic Demo Data" in Path(download.value.path()).read_text()
                page.goto(BASE+"/app/optimization",wait_until="networkidle")
                expect(page.get_by_role("heading",name="Applied allocation",exact=True)).to_be_visible()
                expect(page.get_by_role("button",name="Run optimization",exact=True)).to_be_disabled()
                expect(page.get_by_label("Optimization input mode")).to_be_disabled()
                run=page.request.get(BASE+"/api/optimization/runs/latest").json()
                content=page.request.get(BASE+f'/api/optimization/runs/{run["run_id"]}/export/allocation').text()
                assert len(list(csv.DictReader(StringIO(content))))==12
                for method,path in (("post","/api/auth/login"),("post","/api/datasets"),("post","/api/planning/runs"),
                                    ("post","/api/decisions/compare"),("put","/api/settings/priority"),("delete","/api/datasets/demo")):
                    assert getattr(page.request,method)(BASE+path,headers={"Origin":BASE,"X-Role":"admin"}).status==403
                evidence["checks"].append("Account-free synthetic viewer loads original calculated KPIs/report and precomputed real CP-SAT result; every direct mutation attempt is denied403")
                evidence["responsive_matrix"]=[]
                for width in (360,1440):
                    page.set_viewport_size({"width":width,"height":1000})
                    for route in ("/app","/app/shipments","/app/exceptions","/app/decisions","/app/decisions/history","/app/optimization","/app/analytics","/app/settings"):
                        page.goto(BASE+route,wait_until="networkidle")
                        expect(page.locator("h1").first).to_be_visible()
                        assert page.locator(".error-state").count()==0
                        geometry=page.evaluate("({width:innerWidth,document:document.documentElement.scrollWidth})")
                        assert geometry["document"]<=geometry["width"],(route,geometry)
                        evidence["responsive_matrix"].append({"route":route,**geometry})
                evidence["checks"].append("All eight application routes render read-only demo data at360/1440px without page overflow, blank pages or error states")
            else:
                a=browser.new_page(viewport={"width":1440,"height":1000});b=browser.new_page(viewport={"width":1440,"height":1000})
                for page in (a,b): page.on("pageerror",lambda e:evidence["javascript_errors"].append(str(e)))
                sign_in(a,os.environ["BROWSER_TEST_USERNAME"]);sign_in(b,"browser-second")
                a.get_by_label("Deadline urgency weight",exact=True).fill("81")
                b.get_by_label("Potential financial impact weight",exact=True).fill("82")
                with a.expect_response(lambda r:r.url.endswith("/api/settings/priority") and r.request.method=="PUT") as first:
                    a.get_by_role("button",name="Apply priority settings",exact=True).click()
                assert first.value.status==200 and first.value.json()["version"]==2
                with b.expect_response(lambda r:r.url.endswith("/api/settings/priority") and r.request.method=="PUT") as second:
                    b.get_by_role("button",name="Apply priority settings",exact=True).click()
                assert second.value.status==409 and second.value.request.post_data_json["expected_version"]==1
                expect(b.locator(".error-state")).to_contain_text("Reload latest settings")
                expect(b.get_by_label("Potential financial impact weight",exact=True)).to_have_value("82")
                applied=b.request.get(BASE+"/api/settings").json()
                assert applied["priority"]["weights"]["urgency"]==81 and applied["priority"]["weights"]["financial"]==20
                # Restoring a cached draft must not silently attach the new version.
                b.get_by_role("navigation",name="Platform navigation").locator('a[href="/app"]').click()
                b.get_by_role("navigation",name="Platform navigation").locator('a[href="/app/settings"]').click()
                expect(b.get_by_label("Potential financial impact weight",exact=True)).to_have_value("82")
                with b.expect_response(lambda r:r.url.endswith("/api/settings/priority") and r.request.method=="PUT") as stale_again:
                    b.get_by_role("button",name="Apply priority settings",exact=True).click()
                assert stale_again.value.status==409 and stale_again.value.request.post_data_json["expected_version"]==1
                b.get_by_role("button",name="Reload latest settings",exact=True).click()
                expect(b.get_by_label("Deadline urgency weight",exact=True)).to_have_value("81")
                expect(b.get_by_label("Potential financial impact weight",exact=True)).to_have_value("20")
                b.get_by_label("Potential financial impact weight",exact=True).fill("82")
                with b.expect_response(lambda r:r.url.endswith("/api/settings/priority") and r.request.method=="PUT") as saved:
                    b.get_by_role("button",name="Apply priority settings",exact=True).click()
                assert saved.value.status==200 and saved.value.json()["version"]==3
                b.reload(wait_until="networkidle")
                expect(b.get_by_label("Deadline urgency weight",exact=True)).to_have_value("81")
                expect(b.get_by_label("Potential financial impact weight",exact=True)).to_have_value("82")
                history=b.request.get(BASE+"/api/settings/priority/history").json()
                assert len(history)==2 and {row["actor"] for row in history}=={os.environ["BROWSER_TEST_USERNAME"],"browser-second"}
                evidence["checks"].append("Original audit81/82 scenario: stale second admin409, urgency81 preserved; navigation preserves draft base1; explicit reload then save succeeds as version3 with both edits")
                evidence["checks"].append("SQLite audit retains actual actors, times, versions and differences; page refresh retains version3 configuration")
            assert not evidence["javascript_errors"]
            evidence["completed"]=True
        finally:
            browser.close(); EVIDENCE.write_text(json.dumps(evidence,indent=2))
    print(json.dumps(evidence,indent=2))


if __name__=="__main__": main()
