"""Characterize actual baseline behavior before fixes, isolated data only."""
import json, os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from scripts.uat_fixtures import orders, AS_OF
BASE=os.environ['APP_BASE_URL']


def main():
    evidence={"completed":False,"observations":{},"javascript_errors":[]}
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium')
        try:
            page=browser.new_page()
            page.on('pageerror',lambda error:evidence['javascript_errors'].append(str(error)))
            page.goto(BASE+'/app',wait_until='networkidle')
            page.get_by_label('用户名',exact=True).fill(os.environ['BROWSER_TEST_USERNAME'])
            page.get_by_label('密码',exact=True).fill(os.environ['BROWSER_TEST_PASSWORD'])
            page.get_by_role('button',name='登录',exact=True).click()
            expect(page.locator('.kpi').first).to_contain_text('158')
            def upload(active=False):
                multipart={'file':{'name':'synthetic-uat.csv','mimeType':'text/csv','buffer':orders(all_active=active).to_csv(index=False).encode()},'as_of':AS_OF}
                preview=page.request.post(BASE+'/api/datasets/preview',multipart=multipart,headers={'Origin':BASE});assert preview.status==200
                result=page.request.post(BASE+'/api/datasets',multipart={**multipart,'confirmed':preview.json()['confirmation']},headers={'Origin':BASE});assert result.status==201
                return result.json()['dataset_id']
            mixed=upload();large=upload(True)
            page.reload(wait_until='networkidle');page.get_by_label('当前数据集').select_option(mixed)
            page.goto(BASE+'/app/exceptions',wait_until='networkidle')
            expect(page.locator('.kpi strong').first).to_have_text('7')
            q=page.request.get(BASE+'/api/exceptions',params={'dataset_id':mixed,'as_of':AS_OF,'limit':20}).json()
            assert q['total']==63 and sum(x['actionable'] for x in q['items'])==7
            evidence['observations']['exception_page']={'card_values':page.locator('.kpi strong').all_text_contents(),'queue_total':q['total'],'displayed_rows':len(q['items'])}
            page.get_by_label('当前数据集').select_option(large)
            page.goto(BASE+'/app/decisions',wait_until='networkidle')
            page.get_by_role('button',name='下一页待处理订单',exact=True).click()
            expect(page.get_by_label('待复核决策的订单')).to_have_value('UAT-0051')
            page.get_by_label('当前数据集').select_option(mixed)
            expect(page.get_by_role('heading',name='没有待处理运输异常',exact=True)).to_be_visible()
            evidence['observations']['stale_decision_page']={'actual_active_count':37,'empty_state_after_dataset_switch':True}
            evidence['completed']=True
        finally:
            browser.close();Path(os.environ['BROWSER_EVIDENCE_PATH']).write_text(json.dumps(evidence,ensure_ascii=False,indent=2))
