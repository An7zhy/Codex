"""Independent synthetic UAT reference counts through authenticated HTTP imports."""
import asyncio
from io import BytesIO
import secrets

import httpx
import pandas as pd
import pytest
from backend.main import app
from backend.access import AccessStore, COOKIE
from scripts.uat_fixtures import orders, AS_OF


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGISTICS_INSTANCE_MODE","business")
    monkeypatch.setenv("LOGISTICS_WEB_DB_PATH",str(tmp_path/"web.sqlite3"))
    monkeypatch.setenv("LOGISTICS_DB_PATH",str(tmp_path/"history.sqlite3"))
    monkeypatch.setenv("LOGISTICS_ALLOWED_ORIGINS","http://test")
    store=AccessStore();store.provision("Synthetic UAT organization")
    password=secrets.token_urlsafe(24);store.set_user("uat",password,"admin");token=store.login("uat",password)
    class Client:
        def request(self,method,path,**kwargs):
            async def run():
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test",cookies={COOKIE:token},headers={"Origin":"http://test"}) as c:
                    return await c.request(method,path,**kwargs)
            return asyncio.run(run())
        def get(self,path,**kwargs):return self.request("GET",path,**kwargs)
        def upload(self,active=False):
            content=orders(all_active=active).to_csv(index=False).encode()
            args={"files":{"file":("synthetic-uat.csv",content)},"data":{"as_of":AS_OF}}
            preview=self.request("POST","/api/datasets/preview",**args);assert preview.status_code==200
            response=self.request("POST","/api/datasets",files=args["files"],data={"as_of":AS_OF,"confirmed":preview.json()["confirmation"]})
            assert response.status_code==201
            return response.json()["dataset_id"]
    return Client()


@pytest.mark.parametrize("number",range(1,9))
def test_each_of_eight_carriers_has_exactly_fifteen(client,number):
    dataset=client.upload()
    result=client.get("/api/workspace",params={"dataset_id":dataset,"carrier":f"合成承运商 {number}"}).json()
    expected=[f"UAT-{i:04d}" for i in range((number-1)*15+1,number*15+1)]
    assert result["total_rows"]==15 and result["kpis"]["total_shipments"]==15
    assert [row["shipment_id"] for row in result["shipments"]]==expected


@pytest.mark.parametrize("scope,expected",[
    ({"mode":"Air"},[i for i in range(1,121) if i%2]),
    ({"mode":"Sea"},[i for i in range(1,121) if not i%2]),
    ({"status":"In Transit"},list(range(1,8))+list(range(21,51))),
    ({"carrier":"合成承运商 2","mode":"Air","status":"In Transit"},[21,23,25,27,29]),
    ({"q":"uat-000"},list(range(1,10))),
    ({"carrier":"合成承运商 8","status":"In Transit"},[]),
])
def test_filters_are_literal_canonical_values_and_combine_with_and(client,scope,expected):
    dataset=client.upload()
    args={"dataset_id":dataset,"limit":500,**scope}
    response=client.get("/api/workspace",params=args);assert response.status_code==200
    result=response.json()
    assert result["total_rows"]==len(expected)
    assert [r["shipment_id"] for r in result["shipments"]]==[f"UAT-{i:04d}" for i in expected]
    export=client.get("/api/exports/shipments",params=args)
    assert len(pd.read_csv(BytesIO(export.content)))==len(expected)


def test_page_counts_do_not_change_full_exception_summary(client):
    dataset=client.upload()
    pages=[client.get("/api/exceptions",params={"dataset_id":dataset,"offset":offset,"limit":20}).json() for offset in (0,20,40,60)]
    assert [len(p["items"]) for p in pages]==[20,20,20,3]
    for page in pages:
        assert page["dataset_exception_count"]==63 and page["total"]==63
        assert page["summary"]=={"records":63,"active":37,"high":0,"needs_evidence":37,"review_only":26}
    assert sum(row["actionable"] for row in pages[0]["items"])==7
    assert sum(row["priority_level"]=="Review only" for row in pages[0]["items"])==13
    filtered=client.get("/api/exceptions",params={"dataset_id":dataset,"carrier":"合成承运商 1"}).json()
    assert filtered["dataset_exception_count"]==63 and filtered["total"]==15
    assert filtered["summary"]=={"records":15,"active":7,"high":0,"needs_evidence":7,"review_only":8}
    workspace=client.get("/api/workspace",params={"dataset_id":dataset}).json()
    assert workspace["issue_count"]==0 and workspace["exception_count"]==63
    k=workspace["kpis"]
    assert k["total_shipments"]==120 and k["delivered_shipments"]==83
    assert k["on_time_delivery_rate"]==57/83 and k["average_delay_hours"]==20
    assert k["overdue_shipments"]==37 and k["total_shipping_cost"]==12000 and k["cost_anomalies"]==0


def test_active_pages_exhaust_all_120_without_duplicates_and_local_search_intersects_global(client):
    dataset=client.upload(True)
    pages=[client.get("/api/exceptions",params={"dataset_id":dataset,"actionable_only":True,"limit":50,"offset":n}).json() for n in (0,50,100)]
    assert [len(p["items"]) for p in pages]==[50,50,20]
    assert all(p["total"]==120 and p["summary"]["active"]==120 for p in pages)
    assert [r["shipment_id"] for p in pages for r in p["items"]]==[f"UAT-{i:04d}" for i in range(1,121)]
    scope={"dataset_id":dataset,"actionable_only":True,"q":"UAT-000","search":"0010"}
    assert client.get("/api/exceptions",params=scope).json()["total"]==0
    scope.update(q="UAT-00",search="0010")
    result=client.get("/api/exceptions",params=scope).json()
    assert [r["shipment_id"] for r in result["items"]]==["UAT-0010"]
    assert client.get("/api/exceptions",params={"search":"x"*201}).status_code==422


def test_raw_offset_contract_and_empty_results_remain_explicit(client):
    dataset=client.upload()
    result=client.get("/api/workspace",params={"dataset_id":dataset,"carrier":"合成承运商 1","offset":1000}).json()
    assert result["offset"]==1000 and result["total_rows"]==15 and result["shipments"]==[]
    empty=client.get("/api/exceptions",params={"dataset_id":dataset,"q":"DOES-NOT-EXIST"}).json()
    assert empty["items"]==[] and empty["total"]==0 and empty["dataset_exception_count"]==63
    assert empty["summary"]==dict(records=0,active=0,high=0,needs_evidence=0,review_only=0)
