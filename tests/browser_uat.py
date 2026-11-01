"""Chinese acceptance with120 manually specified synthetic shipments, real APIs/SQLite."""
import csv
from io import StringIO
import json
import os
from pathlib import Path
import time
from urllib.parse import parse_qs,urlparse
from playwright.sync_api import expect,sync_playwright
from scripts.uat_fixtures import orders,AS_OF

BASE=os.environ['APP_BASE_URL'];OUTPUT=Path(os.environ['BROWSER_OUTPUT_DIR']);EVIDENCE=Path(os.environ['BROWSER_EVIDENCE_PATH'])


def main():
    expect.set_options(timeout=30000)
    evidence={'completed':False,'checks':[],'javascript_errors':[],'responsive_matrix':[]}
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium')
        page=browser.new_page(viewport={'width':1440,'height':1000},reduced_motion='reduce',accept_downloads=True)
        page.on('pageerror',lambda e:evidence['javascript_errors'].append(str(e)))
        requests=[];page.on('request',lambda r:requests.append(r.url) if '/api/' in r.url else None)
        started=time.monotonic();checkpoint=0
        def pace():
            nonlocal started,checkpoint
            if len(requests)-checkpoint>70:
                remaining=61-(time.monotonic()-started)
                if remaining>0:time.sleep(min(remaining,60))
                started=time.monotonic();checkpoint=len(requests)
        def navigate(path):
            pace();page.goto(BASE+path,wait_until='networkidle')
        def filtered_ids(expected):
            expect(page.locator('tbody tr td:first-child strong')).to_have_text(expected)
        def import_ui(active=False):
            page.get_by_role('button',name='上传数据',exact=True).click();dialog=page.get_by_role('dialog')
            dialog.locator('input[type=file]').set_input_files({'name':'synthetic-uat-active.csv' if active else 'synthetic-uat-120.csv','mimeType':'text/csv','buffer':orders(all_active=active).to_csv(index=False).encode()})
            dialog.get_by_label('分析日期（UTC）').fill(AS_OF)
            dialog.get_by_role('button',name='预览导入',exact=True).click()
            expect(dialog.get_by_label('导入预览')).to_contain_text('120')
            dialog.get_by_role('checkbox').check()
            with page.expect_response(lambda r:r.url.endswith('/api/datasets') and r.request.method=='POST') as uploaded:
                dialog.get_by_role('button',name='确认导入',exact=True).click()
            assert uploaded.value.status==201
            result=uploaded.value.json()['dataset_id']
            expect(page.get_by_label('当前数据集')).to_have_value(result)
            return result
        try:
            navigate('/app/shipments')
            page.get_by_label('用户名',exact=True).fill(os.environ['BROWSER_TEST_USERNAME'])
            page.get_by_label('密码',exact=True).fill(os.environ['BROWSER_TEST_PASSWORD'])
            page.get_by_role('button',name='登录',exact=True).click()
            expect(page.get_by_label('当前数据集')).to_be_visible()
            mixed=import_ui();expect(page.locator('.secondary-stats')).to_contain_text('120')
            for carrier in range(1,9):
                pace();page.get_by_label('筛选承运商',exact=True).select_option(f'合成承运商 {carrier}')
                filtered_ids([f'UAT-{i:04d}' for i in range((carrier-1)*15+1,carrier*15+1)])
                expect(page.locator('.secondary-stats')).to_contain_text('15')
            evidence['checks'].append('Uploaded120 via Chinese preview/confirm; all8 exact carrier filters return15 correct IDs each')
            page.get_by_label('筛选承运商',exact=True).select_option('合成承运商 2')
            page.get_by_label('筛选运输方式',exact=True).select_option('Air')
            page.get_by_label('筛选运输状态',exact=True).select_option('In Transit')
            filtered_ids([f'UAT-{i:04d}' for i in (21,23,25,27,29)])
            expect(page.get_by_label('筛选运输方式').locator('option:checked')).to_have_text('空运')
            expect(page.get_by_label('筛选运输状态').locator('option:checked')).to_have_text('运输中')
            with page.expect_download() as download:page.get_by_role('link',name='导出 CSV',exact=True).click()
            rows=list(csv.DictReader(StringIO(Path(download.value.path()).read_text(encoding='utf-8-sig'))))
            assert len(rows)==5 and all(r['transport_mode']=='Air' and r['status']=='In Transit' for r in rows)
            page.get_by_label('搜索订单编号',exact=True).fill('uat-0021');filtered_ids(['UAT-0021'])
            page.get_by_label('筛选承运商',exact=True).select_option('合成承运商 8')
            expect(page.get_by_role('heading',name='没有匹配订单',exact=True)).to_be_visible()
            summary=page.get_by_label('当前生效筛选',exact=True)
            for value in ['合成承运商 8','空运','运输中','uat-0021']:expect(summary).to_contain_text(value)
            page.get_by_role('button',name='清除全部筛选',exact=True).click()
            filtered_ids([f'UAT-{i:04d}' for i in range(1,21)])
            page.get_by_role('button',name='下一页订单',exact=True).click();filtered_ids([f'UAT-{i:04d}' for i in range(21,41)])
            page.get_by_label('筛选承运商',exact=True).select_option('合成承运商 8')
            filtered_ids([f'UAT-{i:04d}' for i in range(106,121)])
            evidence['checks'].append('Canonical Air/In Transit values remain separated from Chinese labels; AND/keyword/export agree, valid empty intersection exposes all conditions and clear entry; changing a filter resets shipment offset')
            # Restore deliberately out-of-range persisted shipment page; UI must recover.
            page.evaluate("""() => {const k=Object.keys(localStorage).find(k=>k.startsWith('logistics-workspace-v2:'));const v=JSON.parse(localStorage[k]);v.filters.offset=1000;localStorage[k]=JSON.stringify(v);} """)
            page.reload(wait_until='networkidle');filtered_ids([f'UAT-{i:04d}' for i in range(106,121)])
            assert page.evaluate("JSON.parse(localStorage[Object.keys(localStorage).find(k=>k.startsWith('logistics-workspace-v2:'))]).filters.offset")==0
            page.evaluate("""() => {const k=Object.keys(localStorage).find(k=>k.startsWith('logistics-workspace-v2:'));const v=JSON.parse(localStorage[k]);v.filters.carrier='不在当前表的旧承运商';localStorage[k]=JSON.stringify(v);} """)
            page.reload(wait_until='networkidle')
            expect(page.get_by_label('筛选承运商').locator('option:checked')).to_have_text('已保存但当前不可用的筛选值：不在当前表的旧承运商')
            expect(page.get_by_label('当前生效筛选')).to_contain_text('不在当前表的旧承运商')
            expect(page.get_by_role('heading',name='没有匹配订单',exact=True)).to_be_visible()
            page.get_by_role('button',name='清除全部筛选',exact=True).click()
            navigate('/app/exceptions')
            expect(page.locator('.kpi strong')).to_have_text(['37','0','37','26'])
            counts=page.get_by_label('异常数量统计口径')
            expect(counts).to_contain_text('数据集全部异常：63 条；当前筛选异常：63 条；当前页面：20 条订单。')
            expect(counts).to_contain_text('数据质量问题：0 项')
            page.get_by_role('button',name='下一页异常',exact=True).click()
            expect(page.locator('.table-footer')).to_contain_text('第 2 页 / 共 4 页')
            expect(page.locator('.kpi strong')).to_have_text(['37','0','37','26'])
            page.get_by_label('筛选承运商',exact=True).select_option('合成承运商 1')
            expect(page.locator('.kpi strong')).to_have_text(['7','0','7','8'])
            expect(counts).to_contain_text('数据集全部异常：63 条；当前筛选异常：15 条；当前页面：15 条订单。')
            page.get_by_role('button',name='清除全部筛选',exact=True).click()
            evidence['checks'].append('Stale shipment offset1000 recovered to0; full exception cards37/0/37/26 stable on page2; filtered carrier1 cards7/0/7/8 with dataset63/filtered15/page15 explicitly distinguished from0 V1 quality findings')
            navigate('/app/decisions')
            expect(page.get_by_text('第 1 页 / 共 1 页',exact=False)).to_be_visible()
            expect(page.get_by_role('button',name='上一页待处理订单',exact=True)).to_be_disabled()
            expect(page.get_by_role('button',name='下一页待处理订单',exact=True)).to_be_disabled()
            page.get_by_label('待复核决策的订单').select_option('UAT-0001')
            page.get_by_label('等待并观察：追加成本（USD）').fill('123')
            page.get_by_label('等待并观察：剩余运输小时数').fill('12')
            with page.expect_response(lambda r:r.url.endswith('/api/decisions/compare')) as compared:
                page.get_by_role('button',name='比较方案',exact=True).click()
            assert compared.value.status==200
            result=compared.value.json();assert result['comparison'][0]['estimated_additional_cost_usd']==123
            page.get_by_label('所选处理方案',exact=True).select_option('Wait and monitor')
            page.get_by_label('决策备注').fill('中文UAT验证：合成订单，不是真实业务记录')
            with page.expect_response(lambda r:r.url.endswith('/api/cases') and r.request.method=='POST') as saved:
                page.get_by_role('button',name='保存决策',exact=True).click()
            assert saved.value.status==201 and saved.value.json()['selected_action']=='Wait and monitor'
            assert saved.value.json()['estimated_cost']==123
            navigate('/app/decisions/history')
            page.get_by_label('历史订单编号').fill('UAT-0001');page.get_by_role('button',name='应用筛选',exact=True).click()
            expect(page.locator('tbody tr')).to_have_count(1)
            page.reload(wait_until='networkidle');expect(page.locator('tbody tr').first).to_contain_text('$123.00')
            navigate('/app/decisions');expect(page.get_by_label('等待并观察：追加成本（USD）')).to_have_value('123')
            evidence['checks'].append('Chinese DecisionCenter one-page buttons correctly disabled; compare123/12, save123 action/notes in SQLite, query history/reload/back restores draft; no insertBefore/pageerror')
            large=import_ui(True)
            expect(page.get_by_label('待复核决策的订单')).to_have_value('UAT-0001')
            expect(page.get_by_text('第 1 页 / 共 3 页',exact=False)).to_be_visible()
            page.get_by_role('button',name='下一页待处理订单',exact=True).click()
            expect(page.get_by_label('待复核决策的订单')).to_have_value('UAT-0051')
            expect(page.get_by_text('第 2 页 / 共 3 页',exact=False)).to_be_visible()
            ids=page.get_by_label('待复核决策的订单').locator('option').evaluate_all('els => els.map(e=>e.value)')
            assert ids==[f'UAT-{i:04d}' for i in range(51,101)]
            page.reload(wait_until='networkidle')
            expect(page.get_by_text('第 2 页 / 共 3 页',exact=False)).to_be_visible()
            expect(page.get_by_label('待复核决策的订单')).to_have_value('UAT-0051')
            page.get_by_role('button',name='上一页待处理订单',exact=True).click()
            expect(page.get_by_label('待复核决策的订单')).to_have_value('UAT-0001')
            page.get_by_role('button',name='下一页待处理订单',exact=True).click()
            page.get_by_label('筛选承运商',exact=True).select_option('合成承运商 8')
            expect(page.get_by_text('第 1 页 / 共 1 页',exact=False)).to_be_visible()
            expect(page.get_by_label('待复核决策的订单')).to_have_value('UAT-0106')
            page.get_by_role('button',name='清除全部筛选',exact=True).click()
            page.get_by_role('button',name='下一页待处理订单',exact=True).click()
            page.get_by_label('查找待处理异常订单编号').fill('UAT-0120')
            expect(page.get_by_label('待复核决策的订单')).to_have_value('UAT-0120')
            expect(page.get_by_text('第 1 页 / 共 1 页',exact=False)).to_be_visible()
            page.get_by_label('搜索订单编号',exact=True).fill('UAT-000')
            expect(page.get_by_label('查找待处理异常订单编号')).to_have_value('')
            expect(page.get_by_label('待复核决策的订单')).to_have_value('UAT-0001')
            # Global filter change clears local search by design; set it again to test intersection.
            page.get_by_label('查找待处理异常订单编号').fill('UAT-0120')
            expect(page.get_by_role('heading',name='没有待处理运输异常',exact=True)).to_be_visible()
            page.get_by_role('button',name='清除全部筛选',exact=True).click()
            page.get_by_role('button',name='下一页待处理订单',exact=True).click()
            page.get_by_label('当前数据集').select_option(mixed)
            expect(page.get_by_text('第 1 页 / 共 1 页',exact=False)).to_be_visible()
            expect(page.get_by_label('待复核决策的订单')).to_have_value('UAT-0001')
            expect(page.get_by_label('查找待处理异常订单编号')).to_have_value('')
            assert page.get_by_role('heading',name='没有待处理运输异常',exact=True).count()==0
            evidence['checks'].append('120 active50/50/20 paging: exact page2 IDs, refresh persists same scope; previous works; carrier/search/dataset changes reset page and stale local search; original false-empty dataset-switch reproduced case now shows37 active orders')
            for locale in ('en','zh'):
                page.get_by_role('button',name='English' if locale=='en' else '中文',exact=True).first.click()
                for width in (360,1440):
                    page.set_viewport_size({'width':width,'height':1000})
                    for route in ('/app/shipments','/app/exceptions','/app/decisions','/app/decisions/history'):
                        navigate(route)
                        expect(page.locator('h1').first).to_be_visible()
                        assert not page.locator('.error-state').count()
                        geometry=page.evaluate('({width:innerWidth,document:document.documentElement.scrollWidth})')
                        assert geometry['document']<=geometry['width'],(route,locale,geometry)
                        evidence['responsive_matrix'].append({'route':route,'locale':locale,**geometry})
                        if locale=='zh' and route=='/app/exceptions':page.screenshot(path=str(OUTPUT/f'exceptions-zh-{width}.png'))
            assert not evidence['javascript_errors']
            evidence['completed']=True;evidence['dataset_ids']={'mixed':mixed,'active':large}
        finally:
            browser.close();EVIDENCE.write_text(json.dumps(evidence,indent=2,ensure_ascii=False))
