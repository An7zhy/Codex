"""Run original browser assertions and new CAS/demo flows on disposable instances."""

import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
from unittest.mock import patch

from backend.access import AccessStore
from scripts.prepare_demo import prepare
from scripts.start_web import ROOT, WebServers


def main():
    docs=ROOT/"docs/sprint2-5"; artifacts=ROOT/"artifacts/sprint2-5"
    docs.mkdir(parents=True,exist_ok=True);artifacts.mkdir(parents=True,exist_ok=True)
    for label,filename in (("premium","browser_premium.py"),("hardening","browser_hardening.py"),("uploaded","browser_sprint2.py"),("settings_cas","browser_readiness.py"),("demo","browser_readiness.py")):
        with tempfile.TemporaryDirectory(prefix="logistics-sprint2-5-") as folder:
            password=secrets.token_urlsafe(24);output=artifacts/label;output.mkdir(parents=True,exist_ok=True)
            environment=dict(LOGISTICS_INSTANCE_MODE="business",LOGISTICS_WEB_DB_PATH=str(Path(folder)/"workspace.sqlite3"),LOGISTICS_DB_PATH=str(Path(folder)/"history.sqlite3"),
                LOGISTICS_ALLOWED_ORIGINS="http://127.0.0.1:3100",LOGISTICS_COOKIE_SECURE="0",LOGISTICS_PILOT_MODE="0",LOGISTICS_REQUIRE_BOUNDED_STORAGE="0",
                APP_BASE_URL="http://127.0.0.1:3100",PYTHONPATH=str(ROOT),BROWSER_TEST_USERNAME="browser-admin",BROWSER_TEST_PASSWORD=password,
                BROWSER_OUTPUT_DIR=str(output),BROWSER_SCREENSHOT_DIR=str(output),BROWSER_EVIDENCE_PATH=str(docs/f"{label}_browser.json"))
            if label=="demo":
                seed=Path(folder)/"demo";prepare(seed)
                environment.update(LOGISTICS_INSTANCE_MODE="demo",LOGISTICS_DEMO_ROOT=str(seed),LOGISTICS_WEB_DB_PATH=str(seed/"workspace.sqlite3"),LOGISTICS_DB_PATH=str(seed/"history.sqlite3"))
            else:
                with patch.dict(os.environ,environment):
                    access=AccessStore();access.provision("Synthetic Sprint 2.5 browser organization")
                    for user,role in (("browser-admin","admin"),("browser-second","admin"),("browser-viewer","viewer"),("sprint2-viewer","viewer")):
                        access.set_user(user,password,role)
            try:
                with (output/"servers.log").open("w") as log,WebServers(port=3100,environment=environment,log=log) as servers:
                    code=("import importlib.util; from pathlib import Path; "+f"s=importlib.util.spec_from_file_location('flow','tests/{filename}'); "+"m=importlib.util.module_from_spec(s);s.loader.exec_module(m); ")
                    if label=="hardening":code+=f"m.DOCS=Path('{output.relative_to(ROOT)}'); "
                    if label=="uploaded":code+=f"m.OUTPUT=Path('{output.relative_to(ROOT)}');m.EVIDENCE=Path('docs/sprint2-5/uploaded_browser.json'); "
                    code+="m.main()"
                    command=[sys.executable,"-c",code]+(["--demo"] if label=="demo" else [])
                    result=subprocess.run(command,cwd=ROOT,env=dict(os.environ,**environment),capture_output=True,text=True,timeout=600)
                    (output/"browser.log").write_text(result.stdout+result.stderr)
                    if label=="hardening" and (output/"browser.json").exists():(docs/"hardening_browser.json").write_bytes((output/"browser.json").read_bytes())
                    if result.returncode:raise RuntimeError(f"{label} failed; inspect {output}/browser.log")
                    if label=="uploaded":
                        pid=servers.api.pid;servers.restart_api();assert pid!=servers.api.pid
                        follow=subprocess.run([*command,"--restart-check"],cwd=ROOT,env=dict(os.environ,**environment),capture_output=True,text=True,timeout=120)
                        assert follow.returncode==0,follow.stderr
                        file=docs/"uploaded_browser.json";value=json.loads(file.read_text());value["actual_api_process_restart"]=True;file.write_text(json.dumps(value,indent=2))
                    print(f"PASS: {label}",flush=True)
            finally:
                if label=="demo":seed.chmod(0o755)


if __name__=="__main__":main()
