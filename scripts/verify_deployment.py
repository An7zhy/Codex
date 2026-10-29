"""Bounded localhost-only container/TLS/failure checks; never deploys publicly.

Requires the demo images to have been built. All created containers and networks
belong to the disposable logistics-synthetic-demo project and are stopped on exit.
"""

import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
import time
import uuid

import httpx
from scripts.start_web import ROOT

DOCS=ROOT/"docs/sprint2-5"
ARTIFACTS=ROOT/"artifacts/sprint2-5/deployment"
COMPOSE=["docker","compose","-f","deploy/compose.demo.yml"]


def run(args, *, check=True, timeout=60):
    result=subprocess.run(args,cwd=ROOT,capture_output=True,text=True,timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f"Command failed: {args[:4]}\n{result.stderr[-3000:]}")
    return result


def inspect(name):
    return json.loads(run(["docker","inspect",name]).stdout)[0]


def wait_for(fn, timeout=65):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        try:
            if fn():return
        except (OSError,httpx.HTTPError):pass
        time.sleep(1)
    raise RuntimeError("Local container acceptance timed out")


def main():
    existing=run(["docker","ps","-aq","--filter","label=com.docker.compose.project=logistics-synthetic-demo"]).stdout.strip()
    if existing:
        # Fail before entering the cleanup block; never stop a pre-existing demo.
        raise RuntimeError("The demo project already has containers. Stop only your own demo first; this verifier refuses to replace or stop existing containers.")
    ARTIFACTS.mkdir(parents=True,exist_ok=True);DOCS.mkdir(parents=True,exist_ok=True)
    evidence={"completed":False,"scope":"Disposable synthetic containers, only127.0.0.1:8443 published; local CA, not public TLS acceptance","checks":[],"resources":{}}
    names={role:f"logistics-synthetic-demo-{role}-1" for role in ("api","web","proxy","monitor")}
    temporary=[]
    try:
        run([*COMPOSE,"up","-d","--no-build"],timeout=120)
        wait_for(lambda:inspect(names["proxy"])["State"].get("Health",{}).get("Status")=="healthy")
        cert=ARTIFACTS/"local-ca.crt"
        ca_path="/data/caddy/pki/authorities/local/root.crt"
        wait_for(lambda:run(["docker","exec",names["proxy"],"test","-f",ca_path],check=False).returncode==0)
        cert.write_text(run(["docker","exec",names["proxy"],"cat",ca_path]).stdout)
        context=ssl.create_default_context(cafile=str(cert))
        with httpx.Client(base_url="https://localhost:8443",verify=context,trust_env=False,timeout=15) as client:
            response=client.get("/api/workspace")
            assert response.status_code==200 and response.json()["kpis"]["total_shipments"]==158
            assert response.headers["strict-transport-security"] and response.headers["x-frame-options"]=="DENY"
            identity=client.get("/api/auth/session").json()
            assert identity["role"]=="viewer" and identity["read_only_demo"]
            for method,path in (("POST","/api/datasets"),("POST","/api/planning/runs"),("PUT","/api/settings/priority"),("POST","/api/auth/login")):
                assert client.request(method,path,headers={"Origin":"https://localhost:8443"}).status_code==403
            evidence["checks"].append("Real TLS handshake/hostname/chain verified using extracted local CA, no verify=False; HSTS/frame headers, actual158 KPI and server write403 verified through Caddy and Next")
            for role,name in names.items():
                info=inspect(name);host=info["HostConfig"]
                assert host["ReadonlyRootfs"] and host["Memory"]>0 and host["NanoCpus"]>0 and host["PidsLimit"]>0
                assert "ALL" in host["CapDrop"] and "no-new-privileges:true" in host["SecurityOpt"]
                bindings=host.get("PortBindings") or {}
                if role=="proxy":assert bindings=={"8443/tcp":[{"HostIp":"127.0.0.1","HostPort":"8443"}]}
                else:assert not bindings
                evidence["resources"][role]={"memory_bytes":host["Memory"],"nano_cpus":host["NanoCpus"],"pids":host["PidsLimit"],"read_only_root":True,"ports":bindings,"tmpfs":host["Tmpfs"],"user":info["Config"]["User"]}
            kernel=json.loads(run(["docker","exec",names["api"],"python","-c",
                "from pathlib import Path;import json;print(json.dumps({n:Path('/sys/fs/cgroup/'+n).read_text().strip() for n in ('memory.max','cpu.max','pids.max')}))"]).stdout)
            assert kernel["memory.max"]==str(1024**3) and kernel["pids.max"]=="96"
            quota,period=map(int,kernel["cpu.max"].split());assert quota==period
            evidence["kernel_cgroup_limits"]=kernel
            assert json.loads(run(["docker","network","inspect","logistics-synthetic-demo_private"]).stdout)[0]["Internal"]
            evidence["checks"].append("Kernel cgroup memory/cpu/pids match configured limits; roots read-only, capabilities dropped, internal network and only proxy loopback port published")

            storage_code="""import errno,json,os
from pathlib import Path
root_denied=False
try:Path('/app/should-not-exist').write_text('test')
except OSError as e:root_denied=e.errno in (errno.EROFS,errno.EACCES)
assert root_denied
p=Path('/tmp/bounded-storage-probe');full=False
try:
 with p.open('wb') as f:
  for _ in range(40):f.write(b'x'*1024**2)
except OSError as e:full=e.errno==errno.ENOSPC
finally:p.unlink(missing_ok=True)
assert full
print(json.dumps({'root_write_denied':root_denied,'tmpfs_enospc':full,'tmpfs_bytes':os.statvfs('/tmp').f_blocks*os.statvfs('/tmp').f_frsize}))"""
            evidence["storage_probe"]=json.loads(run(["docker","exec",names["api"],"python","-c",storage_code]).stdout)
            assert client.get("/api/ready").status_code==200
            evidence["checks"].append("Attempted root write fails;32MiB tmpfs hits actual ENOSPC and is cleaned; API remains ready afterward")

            env=dict(os.environ,APP_BASE_URL="https://localhost:8443",BROWSER_EVIDENCE_PATH=str(DOCS/"container_demo_browser.json"))
            browser=subprocess.run([sys.executable,"tests/browser_readiness.py","--demo"],cwd=ROOT,env=env,capture_output=True,text=True,timeout=180)
            (ARTIFACTS/"browser.log").write_text(browser.stdout+browser.stderr)
            assert browser.returncode==0,"Container HTTPS browser failed; inspect artifacts/sprint2-5/deployment/browser.log"
            evidence["checks"].append("Real Chromium read-only demo flow and16 responsive route/width checks passed through container TLS proxy")

            old=inspect(names["api"])["State"]["StartedAt"]
            run(["docker","restart",names["api"]])
            wait_for(lambda:client.get("/api/ready").status_code==200)
            assert inspect(names["api"])["State"]["StartedAt"]!=old
            assert client.get("/api/auth/session").json()["instance_id"]==identity["instance_id"]
            evidence["checks"].append("Actual demo API container restart retains the sealed synthetic identity and calculated data without accounts or sessions")

            # Three failed polls produce a local log ALERT; recovered readiness emits RECOVERY.
            baseline=run(["docker","logs",names["monitor"]]).stdout
            try:
                run(["docker","stop",names["api"]])
                wait_for(lambda:'"event": "ALERT"' in run(["docker","logs",names["monitor"]]).stdout[len(baseline):],timeout=70)
            finally:run(["docker","start",names["api"]])
            wait_for(lambda:client.get("/api/ready").status_code==200)
            wait_for(lambda:'"event": "RECOVERY"' in run(["docker","logs",names["monitor"]]).stdout[len(baseline):],timeout=35)
            evidence["monitor_events"]=run(["docker","logs",names["monitor"]]).stdout.splitlines()
            evidence["checks"].append("Stopping API triggers actual ALERT after failed readiness polls; restarting it produces RECOVERY; notifications remain local logs, not an unverified email/paging integration")

        # A bounded disposable process proves the memory limit is enforced, not just YAML.
        oom="logistics-readiness-oom-"+uuid.uuid4().hex[:8];temporary.append(oom)
        result=run(["docker","run","--name",oom,"--network","none","--read-only","--memory","32m","--memory-swap","32m","--cpus","0.25","--pids-limit","16",
                    "python:3.12.14-slim","python","-c","bytearray(128*1024*1024)"],check=False)
        state=inspect(oom)["State"];assert result.returncode==137 and state["OOMKilled"]
        evidence["oom_probe"]={"exit_code":result.returncode,"oom_killed":state["OOMKilled"],"scope":"32MiB disposable container only; no API or user DB was stressed"}

        pilot="logistics-readiness-pilot-"+uuid.uuid4().hex[:8];temporary.append(pilot)
        environment={"LOGISTICS_INSTANCE_MODE":"business","LOGISTICS_WEB_DB_PATH":"/var/lib/logistics/workspace.sqlite3","LOGISTICS_DB_PATH":"/var/lib/logistics/history.sqlite3",
                     "LOGISTICS_REQUIRE_BOUNDED_STORAGE":"1","LOGISTICS_PILOT_MODE":"1","LOGISTICS_COOKIE_SECURE":"1","LOGISTICS_ALLOWED_ORIGINS":"https://localhost:8443"}
        env_args=[part for key,value in environment.items() for part in ("-e",key+"="+value)]
        code="from backend.access import AccessStore; from scripts.serve_api import main; AccessStore().provision('Synthetic bounded pilot rehearsal');main()"
        run(["docker","run","-d","--name",pilot,"--network","logistics-synthetic-demo_private","--read-only","--memory","768m","--cpus","1","--pids-limit","64",
             "--cap-drop","ALL","--security-opt","no-new-privileges:true","--tmpfs","/var/lib/logistics:size=64m,uid=10001,gid=10001","--tmpfs","/tmp:size=16m,mode=1777",
             *env_args,"logistics-synthetic-demo-monitor","python","-c",code])
        wait_for(lambda:inspect(pilot)["State"].get("Health",{}).get("Status")=="healthy")
        pilot_probe="""import json,os,urllib.request,urllib.error
from backend.deployment import check_storage_bound
check_storage_bound()
try:urllib.request.urlopen('http://127.0.0.1:8000/api/workspace')
except urllib.error.HTTPError as e:status=e.code
assert status==401
print(json.dumps({'ready':urllib.request.urlopen('http://127.0.0.1:8000/api/ready').status,'anonymous_workspace':status,'filesystem_bytes':os.statvfs('/var/lib/logistics').f_blocks*os.statvfs('/var/lib/logistics').f_frsize}))"""
        evidence["bounded_pilot_probe"]=json.loads(run(["docker","exec",pilot,"python","-c",pilot_probe]).stdout)
        unbounded="from backend.deployment import check_storage_bound;from fastapi import HTTPException;\ntry:check_storage_bound()\nexcept HTTPException as e:assert e.status_code==503;print('unbounded-storage-refused')\nelse:raise AssertionError('unbounded storage accepted')"
        assert 'unbounded-storage-refused' in run(["docker","exec","-e","LOGISTICS_WEB_DB_PATH=/app/workspace.sqlite3","-e","LOGISTICS_DB_PATH=/app/history.sqlite3",pilot,"python","-c",unbounded]).stdout
        evidence["bounded_pilot_probe"]["unbounded_filesystem_refused"]=True
        evidence["checks"].append("Full protected API starts on actual64MiB bounded disposable filesystem; ready200 and anonymous workspace401. This tmpfs rehearsal is not persistent pilot storage or production ACL validation")
        evidence["completed"]=True
    finally:
        for name in temporary:run(["docker","rm","-f",name],check=False)
        run([*COMPOSE,"down"],check=False)
        (DOCS/"deployment.json").write_text(json.dumps(evidence,indent=2))
    print(json.dumps(evidence,indent=2))


if __name__=="__main__":main()
