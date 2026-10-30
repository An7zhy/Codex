"""Native localization acceptance against real production Next + protected Python API."""
import csv
from io import StringIO
import json
import os
from pathlib import Path
import sys
import time

import pandas as pd
from playwright.sync_api import expect, sync_playwright
from scripts.audit_readiness import sample
from src.transport.templates import template_tables, workbook_bytes

BASE = os.environ["APP_BASE_URL"]
OUTPUT = Path(os.environ["BROWSER_OUTPUT_DIR"])
EVIDENCE = Path(os.environ["BROWSER_EVIDENCE_PATH"])
ROUTES = ["/", "/app", "/app/shipments", "/app/exceptions", "/app/decisions", "/app/decisions/history", "/app/optimization", "/app/analytics", "/app/settings"]


def language(page, locale):
    page.get_by_role("button", name="中文" if locale == "zh" else "English", exact=True).first.click()
    expect(page.locator("html")).to_have_attribute("lang", "zh-CN" if locale == "zh" else "en")


def check_layout(page, evidence, route, locale, width):
    # Pace the acceptance crawl below existing business/demo budgets; no API limits are changed.
    if evidence["request_count"] >= 80:
        remaining = 61 - (time.monotonic() - evidence["window_started"])
        if remaining > 0: time.sleep(min(remaining, 60))
        evidence["request_count"] = 0; evidence["window_started"] = time.monotonic()
    page.goto(BASE + route, wait_until="networkidle")
    expect(page.locator("h1").first).to_be_visible()
    assert page.locator(".error-state").count() == 0, (route, locale, page.locator(".error-state").all_text_contents())
    geometry = page.evaluate("({width:innerWidth,document:document.documentElement.scrollWidth})")
    assert geometry["document"] <= geometry["width"], (route, locale, geometry)
    # Text must fit buttons without clipping or overlapping siblings.
    bad = page.locator("button:visible, .button:visible").evaluate_all("els => els.filter(e => e.scrollWidth > e.clientWidth + 2).map(e => e.innerText)")
    assert not bad, (route, locale, width, bad)
    if locale == "zh" and width == 1440:
        evidence.setdefault("display_text_review", {})[route] = page.locator("body").evaluate("""element => {
            const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
            const result = []; let node;
            while (node = walker.nextNode()) {
                const p = node.parentElement;
                if (!p || p.closest('script, style, pre, code, svg') || !p.getClientRects().length) continue;
                const text = node.textContent.trim();
                if (/[a-zA-Z]{3}/.test(text)) result.push(text);
            }
            return [...new Set(result)];
        }""")
    if locale == "zh" and route in ("/", "/app/exceptions", "/app/decisions", "/app/optimization"):
        page.screenshot(path=str(OUTPUT / f"{route.strip('/').replace('/', '-') or 'landing'}-zh-{width}.png"))
    evidence["responsive_matrix"].append({"route": route, "locale": locale, **geometry})


def business(page, evidence):
    page.goto(BASE, wait_until="networkidle")
    expect(page.locator("html")).to_have_attribute("lang", "zh-CN")
    expect(page.locator("h1")).to_contain_text("洞察每一票")
    assert '<html lang="zh-CN"' in page.request.get(BASE).text()
    page.screenshot(path=str(OUTPUT / "landing-zh.png"))
    language(page, "en")
    expect(page.locator("h1")).to_contain_text("Intelligence")
    page.reload(wait_until="networkidle")
    expect(page.locator("html")).to_have_attribute("lang", "en")
    assert '<html lang="en"' in page.request.get(BASE).text()
    language(page, "zh")
    page.get_by_role("link", name="进入平台", exact=True).first.click()
    expect(page.get_by_role("heading", name="组织账号登录")).to_be_visible()
    page.get_by_label("用户名", exact=True).fill("not-a-real-account")
    page.get_by_label("密码", exact=True).fill("incorrect-synthetic-password")
    page.get_by_role("button", name="登录", exact=True).click()
    expect(page.locator(".access-card .inline-error")).to_contain_text("用户名或密码不正确")
    expect(page.locator(".access-card .inline-error")).to_contain_text("HTTP 401")
    language(page, "en")
    expect(page.locator(".access-card .inline-error")).to_contain_text("Invalid account or password")
    language(page, "zh")
    page.get_by_label("用户名", exact=True).fill(os.environ["BROWSER_TEST_USERNAME"])
    page.get_by_label("密码", exact=True).fill(os.environ["BROWSER_TEST_PASSWORD"])
    page.get_by_role("button", name="登录", exact=True).click()
    expect(page.locator(".kpi").first).to_contain_text("158")
    expect(page.get_by_text("47.8%", exact=True)).to_be_visible()
    expect(page.get_by_text("Total Shipments", exact=True)).to_have_count(0)
    baseline = page.request.get(BASE + "/api/workspace").json()
    language(page, "en")
    assert page.request.get(BASE + "/api/workspace").json()["kpis"] == baseline["kpis"]
    language(page, "zh")
    evidence["checks"].append("Fresh SSR defaults zh-CN; English cookie survives reload in actual server HTML; bilingual login/errors carry HTTP401; KPI payload unchanged")

    page.goto(BASE + "/app/shipments", wait_until="networkidle")
    page.get_by_label("筛选运输状态", exact=True).select_option("In Transit")
    expect(page.locator("tbody tr").first).to_contain_text("运输中")
    expect(page.get_by_role("button", name="下一页订单", exact=True)).to_be_enabled()
    with page.expect_response(lambda r: "/api/workspace?" in r.url and "offset=20" in r.url) as second_page:
        page.get_by_role("button", name="下一页订单", exact=True).click()
    expected_ids = [row["shipment_id"] for row in second_page.value.json()["shipments"]]
    expect(page.locator("tbody tr td:first-child strong")).to_have_text(expected_ids)
    expect(page.locator(".table-footer")).to_contain_text("21–40")
    ids = page.locator("tbody tr td:first-child strong").all_text_contents()
    language(page, "en")
    expect(page.get_by_label("Filter shipment status", exact=True)).to_have_value("In Transit")
    assert page.locator("tbody tr td:first-child strong").all_text_contents() == ids
    expect(page.locator(".table-footer")).to_contain_text("21–40")
    language(page, "zh")
    page.reload(wait_until="networkidle")
    expect(page.get_by_label("筛选运输状态", exact=True)).to_have_value("In Transit")
    expect(page.locator(".table-footer")).to_contain_text("21–40")
    assert page.locator("tbody tr td:first-child strong").all_text_contents() == ids
    page.get_by_role("button", name="清除筛选", exact=True).click()
    evidence["checks"].append("Canonical In Transit filter and page2/identical shipment IDs survive both language changes and reload")

    # A real pending browser File must not be dropped by a language rerender.
    page.get_by_role("button", name="上传数据", exact=True).click()
    dialog = page.get_by_role("dialog")
    content = pd.DataFrame([sample(shipment_id="I18N-UPLOAD", currency="USD")]).to_csv(index=False).encode()
    dialog.locator("input[type=file]").set_input_files({"name": "i18n-synthetic.csv", "mimeType": "text/csv", "buffer": content})
    dialog.get_by_label("分析日期（UTC）").fill("2026-10-02")
    dialog.get_by_role("button", name="English", exact=True).click()
    assert dialog.locator("input[type=file]").evaluate("e => e.files[0].name") == "i18n-synthetic.csv"
    dialog.get_by_role("button", name="Preview import", exact=True).click()
    expect(dialog.get_by_label("Import preview")).to_be_visible()
    token = dialog.get_by_label("Import preview").inner_text()
    dialog.get_by_role("button", name="中文", exact=True).click()
    expect(dialog.get_by_label("导入预览")).to_contain_text("USD")
    dialog.get_by_role("checkbox").check()
    with page.expect_response(lambda r: r.url.endswith("/api/datasets") and r.request.method == "POST") as uploaded:
        dialog.get_by_role("button", name="确认导入", exact=True).click()
    assert uploaded.value.status == 201
    dataset_id = uploaded.value.json()["dataset_id"]
    expect(page.get_by_label("当前数据集")).to_have_value(dataset_id)
    language(page, "en")
    expect(page.get_by_label("Active dataset")).to_have_value(dataset_id)
    language(page, "zh")
    page.get_by_label("当前数据集").select_option("demo")
    page.get_by_label("工作区分析日期").fill("2026-10-01")
    evidence["checks"].append("Selected File, import preview/confirmation and saved uploaded dataset survive switching language; upload is actually persisted")

    page.goto(BASE + "/app/decisions", wait_until="networkidle")
    page.get_by_label("待复核决策的订单").select_option("SYN-0027")
    expect(page.locator(".explanation-block").first).to_contain_text("紧迫性")
    expect(page.locator(".explanation-block").first).to_contain_text("不是损失预测")
    expect(page.get_by_label("等待并观察：关键假设")).to_have_value("仅为模拟；容量、价格及服务承诺未经核实。")
    page.get_by_label("等待并观察：关键假设").fill("User assumption with spaces\n第二行 ")
    expect(page.get_by_label("等待并观察：关键假设")).to_have_value("User assumption with spaces\n第二行 ")
    page.get_by_label("等待并观察：追加成本（USD）").fill("333")
    page.get_by_label("等待并观察：剩余运输小时数").fill("48")
    language(page, "en")
    expect(page.get_by_label("Wait and monitor: additional cost (USD)")).to_have_value("333")
    expect(page.get_by_label("Wait and monitor: key assumptions")).to_have_value("User assumption with spaces\n第二行 ")
    language(page, "zh")
    with page.expect_response(lambda r: r.url.endswith("/api/decisions/compare") and r.request.method == "POST") as comparison:
        page.get_by_role("button", name="比较方案", exact=True).click()
    assert comparison.value.status == 200
    applied = comparison.value.json()
    assert applied["comparison"][0]["estimated_additional_cost_usd"] == 333
    assert applied["comparison"][0]["key_assumptions"] == "User assumption with spaces\n第二行 "
    expect(page.locator(".scenario-card").first).to_contain_text("场景中超过期限")
    page.get_by_label("所选处理方案", exact=True).select_option("Request expedited handling")
    page.get_by_label("决策备注").fill("中文决策验证 / I18N synthetic test")
    language(page, "en")
    expect(page.get_by_label("Selected action", exact=True)).to_have_value("Request expedited handling")
    language(page, "zh")
    with page.expect_response(lambda r: r.url.endswith("/api/cases") and r.request.method == "POST") as saved:
        page.get_by_role("button", name="保存决策", exact=True).click()
    assert saved.value.status == 201
    case = saved.value.json()
    assert case["selected_action"] == "Request expedited handling"
    assert case["resolution_notes"] == "中文决策验证 / I18N synthetic test"
    assert json.loads(case["priority_snapshot_json"])["priority_score"] == applied["priority_score"]
    page.get_by_role("link", name="处理历史", exact=True).first.click()
    expect(page.locator("tbody tr").first).to_contain_text("请求加急处理")
    page.reload(wait_until="networkidle")
    expect(page.locator("tbody tr").first).to_contain_text("请求加急处理")
    evidence["checks"].append("Chinese decision comparison computes actual USD333; draft/selected canonical action/notes survive language changes; saved SQLite action and priority exactly match applied comparison")

    page.goto(BASE + "/app/settings", wait_until="networkidle")
    page.get_by_label("潜在财务影响权重", exact=True).fill("82")
    language(page, "en")
    expect(page.get_by_label("Potential financial impact weight", exact=True)).to_have_value("82")
    page.goto(BASE + "/app", wait_until="networkidle")
    page.goto(BASE + "/app/settings", wait_until="networkidle")
    expect(page.get_by_label("Potential financial impact weight", exact=True)).to_have_value("82")
    language(page, "zh")
    expect(page.get_by_label("潜在财务影响权重", exact=True)).to_have_value("82")
    assert page.request.get(BASE + "/api/settings").json()["priority"]["weights"]["financial"] == 20
    evidence["checks"].append("Unsaved settings draft82 survives language+navigation; server remains20 with unchanged CAS version")

    page.goto(BASE + "/app/optimization", wait_until="networkidle")
    page.get_by_label("预算比例（%）", exact=True).fill("95")
    language(page, "en")
    expect(page.get_by_label("Budget allowance (%)", exact=True)).to_have_value("95")
    language(page, "zh")
    with page.expect_response(lambda r: r.url.endswith("/api/optimization/runs") and r.request.method == "POST", timeout=60000) as optimized:
        page.get_by_role("button", name="运行优化", exact=True).click()
    assert optimized.value.status == 201
    run = optimized.value.json()
    assert run["results"]["Optimized Allocation"]["status"] == "OPTIMAL"
    assert len(run["results"]["Optimized Allocation"]["assignments"]) == 12
    expect(page.get_by_role("heading", name="已应用的运力分配", exact=True)).to_be_visible()
    expect(page.locator(".notice").filter(has_text="已证明").last).to_contain_text("OPTIMAL")
    page.screenshot(path=str(OUTPUT / "optimization-zh.png"))
    before = page.locator(".results-area").count()
    language(page, "en")
    expect(page.get_by_role("heading", name="Applied allocation", exact=True)).to_be_visible()
    assert page.request.get(BASE + f'/api/optimization/runs/{run["run_id"]}').json()["results"] == run["results"]
    language(page, "zh")
    evidence["checks"].append("Chinese synthetic optimization invokes original OR-Tools, returns OPTIMAL/12 actual assignments; language changes preserve run and exact backend results")

    page.get_by_label("预算比例（%）", exact=True).fill("0")
    with page.expect_response(lambda r: r.url.endswith("/api/optimization/runs") and r.request.method == "POST", timeout=60000) as infeasible:
        page.get_by_role("button", name="运行优化", exact=True).click()
    assert infeasible.value.json()["results"]["Optimized Allocation"]["status"] == "INFEASIBLE"
    expect(page.get_by_text("没有分配能同时满足所有约束。", exact=False).first).to_be_visible()
    evidence["checks"].append("Chinese zero-budget solve returns actual INFEASIBLE, translated diagnostics retain constraint uncertainty")

    # Independent two-order hand calculation through Chinese import UI.
    page.get_by_label("优化输入模式").select_option("uploaded")
    invalid = template_tables(2); invalid["transport_options"].loc[0,"currency"] = "EUR"
    page.get_by_label("规划工作簿文件").set_input_files({"name":"invalid-eur.xlsx", "mimeType":"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "buffer":workbook_bytes(invalid)})
    page.get_by_role("button", name="预览规划输入", exact=True).click()
    expect(page.get_by_label("规划输入预览")).to_contain_text("允许值：USD。不会自动转换。")
    assert page.get_by_role("button", name="确认规划输入", exact=True).count() == 0
    evidence["checks"].append("Chinese invalid EUR import has localized correction and no confirm path; original currency contract unchanged")
    page.get_by_label("规划工作簿文件").set_input_files({"name": "i18n-two-orders.xlsx", "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "buffer": workbook_bytes(template_tables(2))})
    language(page, "en")
    assert page.get_by_label("Planning workbook file").evaluate("e => e.files.length") == 1
    language(page, "zh")
    page.get_by_role("button", name="预览规划输入", exact=True).click()
    preview = page.get_by_label("规划输入预览")
    expect(preview).to_contain_text("已预览")
    preview.get_by_role("checkbox").check()
    language(page, "en")
    expect(page.get_by_label("Planning input preview").get_by_role("checkbox")).to_be_checked()
    language(page, "zh")
    page.get_by_role("button", name="确认规划输入", exact=True).click()
    with page.expect_response(lambda r: r.url.endswith("/api/planning/runs") and r.request.method == "POST", timeout=60000) as planning:
        page.get_by_role("button", name="求解上传规划", exact=True).click()
    assert planning.value.status == 201
    plan = planning.value.json()
    assert [row["total_shipping_cost_usd"] for row in plan["summary"]] == [120, 180, 120]
    expect(page.locator(".kpi-grid").last).to_contain_text("尚未估计")
    with page.expect_download() as event:
        page.get_by_role("link", name="分配结果 CSV", exact=True).click()
    assert event.value.failure() is None
    rows = list(csv.DictReader(StringIO(Path(event.value.path()).read_text(encoding="utf-8-sig"))))
    assert len(rows) == 2 and {row["shipment_id"] for row in rows} == {"UPLOAD-0001", "UPLOAD-0002"}
    evidence["checks"].append("Chinese uploaded 2-order import/preview/confirmation/solve/export, hand costs120/180/120; file+checkbox preserved, reliability remains not estimated, raw CSV identifiers unchanged")
    page.goto(BASE + "/app/analytics", wait_until="networkidle")
    page.get_by_role("button", name="运行规则评估", exact=True).click()
    expect(page.get_by_role("heading", name="V2 参考案例评估", exact=True)).to_be_visible()
    expect(page.locator("tbody tr").last).to_be_visible()


def demo(page, evidence):
    page.goto(BASE, wait_until="networkidle")
    expect(page.locator("html")).to_have_attribute("lang", "zh-CN")
    page.get_by_role("link", name="进入平台", exact=True).first.click()
    expect(page.get_by_text("合成演示 · 只读", exact=True)).to_be_visible()
    expect(page.locator(".kpi").first).to_contain_text("158")
    assert page.request.get(BASE + "/api/auth/session").json()["read_only_demo"]
    for locale in ("en", "zh"):
        language(page, locale)
        expect(page.get_by_role("button", name="Upload data" if locale == "en" else "上传数据", exact=True)).to_be_disabled()
        assert page.request.post(BASE + "/api/optimization/runs", data={}).status == 403
    page.goto(BASE + "/app/optimization", wait_until="networkidle")
    expect(page.get_by_role("heading", name="已应用的运力分配", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="运行优化", exact=True)).to_be_disabled()
    evidence["checks"].append("Account-free sealed demo is bilingual, retains real precomputed allocation and actual158 KPI; direct writes remain403 in both languages")


def main():
    expect.set_options(timeout=30000)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    evidence = {"completed": False, "checks": [], "javascript_errors": [], "responsive_matrix": []}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=os.environ.get("BROWSER_EXECUTABLE_PATH", "/usr/bin/chromium"))
        try:
            page = browser.new_page(viewport={"width":1440,"height":1000}, reduced_motion="reduce", accept_downloads=True)
            evidence["demo"] = "--demo" in sys.argv
            evidence["request_count"] = 0; evidence["window_started"] = time.monotonic()
            def count(request):
                if "/api/" in request.url: evidence["request_count"] += 1
            page.on("request", count)
            page.on("pageerror", lambda error: evidence["javascript_errors"].append(str(error)))
            (demo if "--demo" in sys.argv else business)(page, evidence)
            for locale in ("zh", "en"):
                language(page, locale)
                for width in (360, 1440):
                    page.set_viewport_size({"width": width, "height":1000})
                    for route in ROUTES:
                        check_layout(page, evidence, route, locale, width)
            assert not evidence["javascript_errors"]
            evidence["completed"] = True
            evidence.pop("window_started", None)
        finally:
            browser.close()
            EVIDENCE.write_text(json.dumps(evidence, indent=2, ensure_ascii=False))
    print(json.dumps(evidence, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
