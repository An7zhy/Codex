"""Isolated real browser validation; existing English assertions are unchanged.

Run after `cd web && npm run build`. Never reads the user's databases or accounts.
"""
import argparse
import hashlib
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

FLOWS = {
    "i18n-business": ("browser_i18n.py", False, False),
    "i18n-demo": ("browser_i18n.py", True, False),
    "premium": ("browser_premium.py", False, True),
    "hardening": ("browser_hardening.py", False, True),
    "uploaded": ("browser_sprint2.py", False, True),
    "settings-cas": ("browser_readiness.py", False, True),
    "legacy-demo": ("browser_readiness.py", True, True),
}

# Explicit test language precondition, applied before any navigation, including Browser.new_page.
ENGLISH_CONTEXT = '''
from playwright._impl._browser import Browser
_original_context = Browser.new_context
async def _english_context(self, *args, **kwargs):
    context = await _original_context(self, *args, **kwargs)
    await context.add_cookies([{"name":"logistics-language", "value":"en", "url":os.environ["APP_BASE_URL"]}])
    return context
Browser.new_context = _english_context
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flows", default=",".join(FLOWS))
    args = parser.parse_args()
    docs = ROOT / "docs/i18n"; docs.mkdir(parents=True, exist_ok=True)
    for label in args.flows.split(","):
        filename, demo, english = FLOWS[label]
        with tempfile.TemporaryDirectory(prefix="logistics-i18n-") as folder:
            password = secrets.token_urlsafe(24)
            output = ROOT / "artifacts/i18n" / label; output.mkdir(parents=True, exist_ok=True)
            evidence = docs / f"{label}.json"
            environment = dict(LOGISTICS_INSTANCE_MODE="business", LOGISTICS_WEB_DB_PATH=str(Path(folder)/"workspace.sqlite3"),
                LOGISTICS_DB_PATH=str(Path(folder)/"history.sqlite3"), LOGISTICS_ALLOWED_ORIGINS="http://127.0.0.1:3100",
                LOGISTICS_COOKIE_SECURE="0", LOGISTICS_PILOT_MODE="0", LOGISTICS_REQUIRE_BOUNDED_STORAGE="0",
                APP_BASE_URL="http://127.0.0.1:3100", PYTHONPATH=str(ROOT), BROWSER_TEST_USERNAME="browser-admin",
                BROWSER_TEST_PASSWORD=password, BROWSER_OUTPUT_DIR=str(output), BROWSER_SCREENSHOT_DIR=str(output), BROWSER_EVIDENCE_PATH=str(evidence))
            if demo:
                seed=Path(folder)/"demo"; prepare(seed)
                environment.update(LOGISTICS_INSTANCE_MODE="demo", LOGISTICS_DEMO_ROOT=str(seed),
                                   LOGISTICS_WEB_DB_PATH=str(seed/"workspace.sqlite3"), LOGISTICS_DB_PATH=str(seed/"history.sqlite3"))
            else:
                with patch.dict(os.environ, environment):
                    access=AccessStore();access.provision("Synthetic i18n test organization")
                    for user, role in (("browser-admin","admin"),("browser-second","admin"),("browser-viewer","viewer"),("sprint2-viewer","viewer")):
                        access.set_user(user, password, role)
            code="import os, importlib.util; from pathlib import Path;\n" + (ENGLISH_CONTEXT if english else "")
            code+=f"s=importlib.util.spec_from_file_location('flow','tests/{filename}'); m=importlib.util.module_from_spec(s);s.loader.exec_module(m);\n"
            if label == "hardening": code+=f"m.DOCS=Path({str(output)!r});\n"
            if label == "uploaded": code+=f"m.OUTPUT=Path({str(output)!r});m.EVIDENCE=Path({str(evidence)!r});\n"
            code+="m.main()"
            command=[sys.executable,"-c",code]+(["--demo"] if demo else [])
            try:
                with (output/"servers.log").open("w") as log, WebServers(port=3100, environment=environment, log=log) as servers:
                    result=subprocess.run(command,cwd=ROOT,env=dict(os.environ,**environment),capture_output=True,text=True,timeout=900)
                    (output/"browser.log").write_text(result.stdout+result.stderr)
                    if label=="hardening" and (output/"browser.json").exists(): evidence.write_bytes((output/"browser.json").read_bytes())
                    if result.returncode:
                        print((result.stdout+result.stderr)[-6500:], flush=True)
                        raise RuntimeError(f"{label} failed; inspect {output}/browser.log")
                    if label=="uploaded":
                        pid=servers.api.pid; servers.restart_api(); assert pid != servers.api.pid
                        follow=subprocess.run([*command,"--restart-check"],cwd=ROOT,env=dict(os.environ,**environment),capture_output=True,text=True,timeout=120)
                        assert follow.returncode==0, follow.stderr
                        data=json.loads(evidence.read_text());data["actual_api_process_restart"]=True;evidence.write_text(json.dumps(data,indent=2))
                    data=json.loads(evidence.read_text())
                    source_hash=hashlib.sha256()
                    for file in sorted((ROOT/"web/src").rglob("*")):
                        if file.is_file(): source_hash.update(str(file.relative_to(ROOT)).encode()+b"\0"+file.read_bytes())
                    data["verification"]={"build_id":(ROOT/"web/.next/BUILD_ID").read_text().strip(),
                        "frontend_source_sha256":source_hash.hexdigest(),
                        "original_test_file_sha256":hashlib.sha256((ROOT/"tests"/filename).read_bytes()).hexdigest(),
                        "language_precondition":"en" if english else "fresh browser defaults zh", "temporary_database":True}
                    evidence.write_text(json.dumps(data,indent=2,ensure_ascii=False))
                    print(f"PASS: {label}",flush=True)
            finally:
                if demo: seed.chmod(0o755)


if __name__=="__main__": main()
