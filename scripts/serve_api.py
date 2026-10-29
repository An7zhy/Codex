"""Container entrypoint: fail closed before listening, one bounded API worker."""

import os
import sys
from backend.demo_policy import demo_enabled, validate_demo
from backend.deployment import check_storage_bound
from backend.access import AccessStore


def main():
    if demo_enabled():
        validate_demo()
    else:
        check_storage_bound()
        AccessStore().check_binding()
    os.execv(sys.executable, [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000",
                            "--workers", "1", "--limit-concurrency", "16", "--backlog", "64", "--timeout-keep-alive", "5", "--no-proxy-headers"])


if __name__ == "__main__":
    main()
