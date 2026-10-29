"""Authenticate and cap complete ASGI bodies BEFORE multipart parsing."""

import asyncio
import os
import sqlite3
import time
import uuid

from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

from backend.access import AccessStore, COOKIE, ROLES, required_role
from backend.demo_policy import demo_enabled, validate_demo, allow_demo_read, DemoBudget

MAX_BODY = 20 * 1024 * 1024
SAFE = {"GET", "HEAD", "OPTIONS"}


def origins():
    return set(os.environ.get("LOGISTICS_ALLOWED_ORIGINS", "http://127.0.0.1:3000,http://localhost:3000").split(","))


class SecurityBoundary:
    def __init__(self, app):
        self.app = app
        self.demo_budget = DemoBudget()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope)
        path, method = request.url.path, request.method
        if not path.startswith("/api"):
            return await self.app(scope, receive, send)
        request_id = uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        actor, store = "anonymous", None
        status = 500
        async def secured_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message["headers"] = [*message["headers"], (b"cache-control", b"no-store, private"),
                                      (b"x-content-type-options", b"nosniff"), (b"x-request-id", request_id.encode())]
            await send(message)
        try:
            if os.environ.get("LOGISTICS_PILOT_MODE") == "1" and path != "/api/health":
                if os.environ.get("LOGISTICS_COOKIE_SECURE") != "1" or any(not item.startswith("https://") for item in origins()):
                    raise HTTPException(503, "Pilot mode requires Secure cookies and explicit HTTPS website origins.")
            if demo_enabled():
                if method != "GET":
                    raise HTTPException(403, "Read-only synthetic demo: uploads, comparisons, solving, account login and all writes are disabled on the server.")
                allow_demo_read(path, scope.get("query_string", b""))
                # Liveness remains available for restart checks; ready validates sealed data.
                if path == "/api/health":
                    return await self.app(scope, receive, secured_send)
                with self.demo_budget.slot():
                    scope["state"]["principal"] = validate_demo()
                    started = time.monotonic()
                    while True:
                        remaining = 5 - (time.monotonic() - started)
                        if remaining <= 0:
                            raise HTTPException(408, "Demo request timed out.")
                        event = await asyncio.wait_for(receive(), remaining)
                        if event["type"] == "http.disconnect":
                            return
                        if event.get("body"):
                            raise HTTPException(413, "Synthetic demo GET requests cannot contain a body.")
                        if not event.get("more_body", False):
                            break
                    async def empty_receive():
                        return {"type": "http.request", "body": b""}
                    return await self.app(scope, empty_receive, secured_send)
            public = (method == "GET" and path in {"/api/health", "/api/ready"}) or (method == "POST" and path == "/api/auth/login")
            if not public:
                if not request.cookies.get(COOKIE):
                    raise HTTPException(401, "Sign in to access this organization workspace.")
                store = AccessStore()
                principal = store.authenticate(request.cookies.get(COOKIE))
                scope["state"]["principal"] = principal
                actor = principal["username"]
                if ROLES[principal["role"]] < ROLES[required_role(method, path)]:
                    raise HTTPException(403, "Your role cannot perform this operation.")
                store.rate("requests:" + actor, 180)
            if method not in SAFE:
                if request.headers.get("origin") not in origins() or request.headers.get("sec-fetch-site") == "cross-site":
                    raise HTTPException(403, "Write origin rejected. Use the configured organization website.")
                if store and path in {"/api/datasets", "/api/datasets/preview", "/api/planning/imports/preview"}:
                    store.rate("uploads:" + actor, 10)
            # No trust in Content-Length: also count chunked bodies as received.
            limit = MAX_BODY if path.startswith("/api/datasets") or path == "/api/planning/imports/preview" else 256 * 1024
            declared = request.headers.get("content-length")
            if declared and (not declared.isdecimal() or int(declared) > limit):
                raise HTTPException(413, "Total request body exceeds the allowed budget.")
            chunks, size, started = [], 0, time.monotonic()
            while True:
                remaining = 20 - (time.monotonic() - started)
                if remaining <= 0:
                    raise HTTPException(408, "Request body timed out.")
                event = await asyncio.wait_for(receive(), remaining)
                if event["type"] == "http.disconnect":
                    return
                chunk = event.get("body", b"")
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, "Total request body exceeds the allowed budget.")
                chunks.append(chunk)
                if not event.get("more_body", False):
                    break
            body = b"".join(chunks)
            delivered = False
            async def bounded_receive():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": body}
                return await receive()
            await self.app(scope, bounded_receive, secured_send)
        except asyncio.TimeoutError:
            await JSONResponse({"detail": "Request body timed out."}, status_code=408)(scope, receive, secured_send)
        except HTTPException as exc:
            await JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)(scope, receive, secured_send)
        except (sqlite3.Error, OSError):
            await JSONResponse({"detail": "Local storage is unavailable. Ask the administrator to check readiness."}, status_code=503)(scope, receive, secured_send)
        finally:
            if store and method not in SAFE:
                try:
                    store.event(actor, method, path + " request:" + request_id, status)
                except sqlite3.Error:
                    # The operation already failed/finished; do not replace its response.
                    pass
