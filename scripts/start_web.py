"""Cross-platform launcher for the Python API and Next.js website.

Run from the repository root: python -m scripts.start_web
Dependencies and a production build must already exist; --dev uses Next dev.
"""

import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parents[1]


def stop_process(process):
    if process is None or process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
    else:
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait(timeout=5)


class WebServers:
    def __init__(self, *, port=3000, dev=False, environment=None, log=None):
        self.port, self.dev = port, dev
        self.environment = dict(os.environ, **(environment or {}))
        self.environment["NEXT_TELEMETRY_DISABLED"] = "1"
        self.log = log
        self.api = self.frontend = None

    def spawn(self, command, cwd=ROOT):
        return subprocess.Popen(command, cwd=cwd, env=self.environment, stdout=self.log, stderr=subprocess.STDOUT,
                                start_new_session=os.name != "nt",
                                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0)

    def wait_ready(self, url, process):
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("A server stopped during startup. Inspect the terminal or server log.")
            try:
                with urllib.request.urlopen(url, timeout=2) as response:
                    if response.status == 200:
                        return
            except (OSError, urllib.error.URLError):
                pass
            time.sleep(.2)
        raise RuntimeError("Server startup timed out. Inspect the terminal or server log.")

    def start_api(self):
        self.api = self.spawn([sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8000"])
        self.wait_ready("http://127.0.0.1:8000/api/health", self.api)

    def __enter__(self):
        npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
        if not npm:
            raise RuntimeError("Node.js/npm was not found. Install Node.js 24 LTS, reopen the terminal and retry.")
        if not self.dev and not (ROOT / "web/.next/BUILD_ID").exists():
            raise RuntimeError("Production build missing. Run npm ci and npm run build in web/ first.")
        for port in (8000, self.port):
            with socket.socket() as sock:
                if sock.connect_ex(("127.0.0.1", port)) == 0:
                    raise RuntimeError(f"Port {port} is already in use. Stop the previous server with Ctrl+C first.")
        try:
            self.start_api()
            self.frontend = self.spawn([npm, "run", "dev" if self.dev else "start", "--", "--port", str(self.port)], ROOT / "web")
            self.wait_ready(f"http://127.0.0.1:{self.port}", self.frontend)
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def restart_api(self):
        stop_process(self.api)
        self.start_api()

    def __exit__(self, *args):
        stop_process(self.frontend)
        stop_process(self.api)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dev", action="store_true")
    parser.add_argument("--port", type=int, default=3000)
    parser.add_argument("--open", action="store_true", help="Open the homepage in your browser")
    args = parser.parse_args()
    try:
        with WebServers(port=args.port, dev=args.dev) as servers:
            url = f"http://127.0.0.1:{args.port}"
            print(f"\nWebsite: {url}\nPlatform: {url}/app\nKeep this terminal open. Press Ctrl+C to stop both services.\n", flush=True)
            if args.open:
                webbrowser.open(url)
            while servers.api.poll() is None and servers.frontend.poll() is None:
                time.sleep(.5)
    except KeyboardInterrupt:
        print("\nWebsite and API stopped.")
    except RuntimeError as exc:
        print(f"Startup failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
