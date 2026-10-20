"""Request ID, access logging and security headers (pure ASGI — no BaseHTTPMiddleware)."""

from __future__ import annotations

import re
import time
import uuid

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from verita.core.logging import get_logger, request_id_var

log = get_logger("verita.access")

_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}
API_CSP = "default-src 'none'; frame-ancestors 'none'"


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp, docs_prefix: str = "/api/docs") -> None:
        self.app = app
        self.docs_prefix = docs_prefix

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        inbound = dict(scope.get("headers") or []).get(b"x-request-id", b"").decode("latin-1")
        request_id = inbound if _SAFE_REQUEST_ID.match(inbound) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status_holder = {"status": 500}
        path: str = scope.get("path", "")
        is_docs = path.startswith(self.docs_prefix)

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                for name, value in SECURITY_HEADERS.items():
                    headers.setdefault(name, value)
                if not is_docs:
                    headers.setdefault("Content-Security-Policy", API_CSP)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            log.info(
                "request",
                method=scope.get("method"),
                path=path,
                status=status_holder["status"],
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            request_id_var.reset(token)
