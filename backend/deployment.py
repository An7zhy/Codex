"""Deployment preflight, deliberately separate from normal local development."""

import os
from fastapi import HTTPException
from backend.access import paths


def check_storage_bound():
    if os.environ.get("LOGISTICS_REQUIRE_BOUNDED_STORAGE") != "1":
        return
    workspace, history = paths()
    if workspace.resolve().parent != history.resolve().parent:
        raise HTTPException(503, "Deployment requires both databases on its dedicated bounded data filesystem.")
    try:
        stats = os.statvfs(workspace.parent)
        # A directory name/Compose volume is not a physical storage quota.
        if stats.f_blocks * stats.f_frsize > 1024**3:
            raise HTTPException(503, "Data filesystem is not bounded to at most 1 GiB. Provision a dedicated bounded persistent filesystem before starting this deployment.")
        if stats.f_bavail * stats.f_frsize < 8 * 1024**2:
            raise HTTPException(503, "Data filesystem reserve is below 8 MiB. Stop writers and perform documented retention or recovery.")
    except OSError as exc:
        raise HTTPException(503, "Dedicated data filesystem is unavailable.") from exc
