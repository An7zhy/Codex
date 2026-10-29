"""Local alert/recovery events to bounded container logs; no external messaging."""

import argparse
import json
import time
from datetime import datetime, timezone
from urllib.request import urlopen


def check(urls):
    failures = []
    for url in urls:
        try:
            with urlopen(url, timeout=3) as response:
                if response.status != 200:
                    failures.append(url)
        except OSError:
            failures.append(url)
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=15)
    parser.add_argument("urls", nargs="+", help="Trusted internal liveness/readiness endpoints, never user-supplied URLs")
    args = parser.parse_args()
    failing = 0; alerted = False
    while True:
        failures = check(args.urls)
        failing = failing + 1 if failures else 0
        if failures and (failing == 3 or args.once):
            print(json.dumps({"event": "ALERT", "time": datetime.now(timezone.utc).isoformat(), "failed_endpoints": failures}), flush=True)
            alerted = True
        elif not failures and alerted:
            print(json.dumps({"event": "RECOVERY", "time": datetime.now(timezone.utc).isoformat()}), flush=True)
            alerted = False
        if args.once:
            return int(bool(failures))
        time.sleep(max(1, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
