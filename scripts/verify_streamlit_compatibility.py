"""Real-browser form regression after Streamlit security upgrade, temporary history."""

import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

from scripts.start_web import ROOT, stop_process


def main():
    output = ROOT / "artifacts/hardening"
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="streamlit-compatibility-") as directory, (output / "streamlit.log").open("w") as log:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        environment = dict(os.environ, LOGISTICS_DB_PATH=str(Path(directory) / "history.sqlite3"),
                           LOGISTICS_PILOT_MODE="0", APP_BASE_URL=base,
                           BROWSER_EXECUTABLE_PATH=os.environ.get("BROWSER_EXECUTABLE_PATH", "/usr/bin/chromium"))
        server = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "app.py", "--server.port", str(port)],
            cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT, start_new_session=os.name != "nt")
        try:
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                try:
                    with urllib.request.urlopen(base + "/_stcore/health", timeout=1) as response:
                        if response.status == 200: break
                except OSError: pass
                time.sleep(.2)
            else: raise RuntimeError("Streamlit did not become ready.")
            for name, evidence in (("browser_parameter_changes.py", "streamlit_parameters.json"), ("browser_transport.py", "streamlit_transport.json")):
                result = subprocess.run([sys.executable, str(ROOT / "tests" / name)], cwd=ROOT,
                    env=dict(environment, BROWSER_EVIDENCE_PATH=str(ROOT / "docs/hardening" / evidence)),
                    capture_output=True, text=True, timeout=300)
                (output / (name + ".log")).write_text(result.stdout + result.stderr)
                if result.returncode: raise RuntimeError(f"{name} failed; inspect artifacts/hardening/{name}.log")
                print(f"PASS: real Streamlit browser {name}", flush=True)
        finally:
            stop_process(server)


if __name__ == "__main__":
    main()
