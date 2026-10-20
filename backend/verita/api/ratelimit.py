"""Rate limiting (M9.01): sliding windows per client IP and per session, pure ASGI.

Three budgets, checked before the request reaches a route:

* every API request: ``rate_limit_per_ip`` per minute per client IP;
* ``POST /auth/login``: ``rate_limit_login_per_ip`` per minute per IP (on top of the per-account
  lockout, so a password spray across many usernames is slowed too);
* mutations (POST/PUT/DELETE) with a session cookie: ``rate_limit_mutations_per_session`` per
  minute per session.

Over budget → ``429`` problem+json with ``Retry-After``. State is in process memory, which is
right for the single-instance demo deploy; several instances would share a Redis counter instead
(see docs/RUNBOOK.md). Key memory is bounded: the oldest keys are evicted past ``MAX_KEYS``.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections import OrderedDict, deque
from dataclasses import dataclass

from starlette.types import ASGIApp, Receive, Scope, Send

from verita.core.logging import get_logger

log = get_logger("verita.ratelimit")
WINDOW_SECONDS = 60.0
MAX_KEYS = 50_000
SESSION_COOKIE = b"verita_session"


@dataclass(frozen=True)
class Limits:
    per_ip: int
    login_per_ip: int
    mutations_per_session: int


class SlidingWindow:
    def __init__(self, limit: int, window: float = WINDOW_SECONDS) -> None:
        self.limit = limit
        self.window = window
        self.hits: OrderedDict[str, deque[float]] = OrderedDict()

    def check(self, key: str, now: float) -> float | None:
        """Record a hit; return seconds to wait if over the limit, else None."""
        q = self.hits.get(key)
        if q is None:
            q = deque()
            self.hits[key] = q
            if len(self.hits) > MAX_KEYS:
                self.hits.popitem(last=False)
        else:
            self.hits.move_to_end(key)
        while q and now - q[0] >= self.window:
            q.popleft()
        if len(q) >= self.limit:
            return max(self.window - (now - q[0]), 0.0)
        q.append(now)
        return None


def _client_ip(scope: Scope) -> str:
    client = scope.get("client")
    return str(client[0]) if client else "unknown"


def _session(scope: Scope) -> str | None:
    for name, value in scope.get("headers") or []:
        if name == b"cookie":
            for part in value.split(b";"):
                key, _, val = part.strip().partition(b"=")
                if key == SESSION_COOKIE and val:
                    return hashlib.sha256(val).hexdigest()  # never keep the raw token
    return None


class RateLimitMiddleware:
    def __init__(self, app: ASGIApp, limits: Limits, prefix: str = "/api/") -> None:
        self.app = app
        self.prefix = prefix
        self.ip = SlidingWindow(limits.per_ip)
        self.login = SlidingWindow(limits.login_per_ip)
        self.mutations = SlidingWindow(limits.mutations_per_session)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path: str = scope.get("path", "")
        if (
            scope["type"] != "http"
            or not path.startswith(self.prefix)
            or path.endswith("/health/live")
        ):
            await self.app(scope, receive, send)
            return
        now = time.monotonic()
        method = scope.get("method", "GET")
        ip = _client_ip(scope)
        wait = self.ip.check(ip, now)
        if wait is None and method == "POST" and path.endswith("/auth/login"):
            wait = self.login.check(ip, now)
        if wait is None and method in ("POST", "PUT", "DELETE"):
            session = _session(scope)
            if session is not None:
                wait = self.mutations.check(session, now)
        if wait is None:
            await self.app(scope, receive, send)
            return
        retry = max(1, math.ceil(wait))
        log.warning("rate_limited", path=path, method=method, retry_after=retry)
        body = json.dumps(
            {
                "type": "https://verita.dev/problems/rate-limited",
                "title": "Too many requests",
                "status": 429,
                "detail": f"Try again in {retry} s.",
            }
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 429,
                "headers": [
                    (b"content-type", b"application/problem+json"),
                    (b"retry-after", str(retry).encode()),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
