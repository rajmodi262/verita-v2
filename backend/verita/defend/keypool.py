"""API-key pools for the LLM providers: priority order, instant failover, quota cooldowns.

Each provider holds its keys in the configured order. A request uses the first key that is not
cooling down; when that key's quota is exhausted (HTTP 429, or Gemini's RESOURCE_EXHAUSTED) the
same request moves straight to the next key — no sleep, no retry of the exhausted key. The
exhausted key sits out until the time the provider asked for (``Retry-After`` / Gemini's
``RetryInfo``), or a default cooldown, and is then tried again first, since it has the highest
priority. A rejected key (401/403, or Gemini's API_KEY_INVALID) is taken out of rotation for the
life of the process. When every key of a provider is out, the provider fails and drafting falls
through to the next provider, and finally to the offline template.

Keys never appear in logs, errors, status output or ``repr``: they are identified by a short
SHA-256 fingerprint. Pools are process-wide, so a cooldown learned by one request holds for the
next; the API and the worker each keep their own.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx

# Per-minute quotas reset within a minute; when the provider names no retry time, re-try after
# this. Per-day quotas get a longer pause before the key is probed again.
DEFAULT_COOLDOWN_S = 60.0
DAILY_COOLDOWN_S = 3600.0


def fingerprint(key: str) -> str:
    """A stable, non-reversible label for a key: ``sha256:`` + 8 hex characters."""
    return "sha256:" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]


@dataclass
class KeyState:
    key: str = field(repr=False)
    priority: int
    fingerprint: str
    status: str = "unused"  # unused | ok | exhausted | invalid
    cooldown_until: float = 0.0
    detail: str = ""
    uses: int = 0


class KeyPool:
    """Thread-safe priority list of keys for one provider."""

    def __init__(
        self, provider: str, keys: Sequence[str], clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.provider = provider
        self._clock = clock
        self._lock = threading.Lock()
        self._keys = [KeyState(k, i + 1, fingerprint(k)) for i, k in enumerate(keys)]

    def __len__(self) -> int:
        return len(self._keys)

    def available(self) -> list[KeyState]:
        """Keys that may be tried now, best first."""
        now = self._clock()
        with self._lock:
            return [k for k in self._keys if k.status != "invalid" and k.cooldown_until <= now]

    def next_retry_in(self) -> float | None:
        """Seconds until the soonest cooling-down key is usable again (None: none will be)."""
        now = self._clock()
        with self._lock:
            waits = [k.cooldown_until - now for k in self._keys if k.status == "exhausted"]
        return max(0.0, min(waits)) if waits else None

    def mark_ok(self, state: KeyState, detail: str = "") -> None:
        with self._lock:
            state.status, state.cooldown_until, state.detail = "ok", 0.0, detail
            state.uses += 1

    def mark_exhausted(self, state: KeyState, retry_after: float | None, detail: str) -> None:
        with self._lock:
            state.status = "exhausted"
            state.cooldown_until = self._clock() + (
                retry_after if retry_after is not None else DEFAULT_COOLDOWN_S
            )
            state.detail = detail

    def mark_invalid(self, state: KeyState, detail: str) -> None:
        with self._lock:
            state.status, state.detail = "invalid", detail

    def probe(
        self,
        send: Callable[[str], httpx.Response],
        quota: Callable[[httpx.Response], str] = lambda _r: "",
    ) -> list[dict[str, Any]]:
        """Check every key (rejected ones included) with SEND and record what each returned.

        Transport failures are recorded as ``error`` without changing the key's state.
        """
        for state in list(self._keys):
            try:
                response = send(state.key)
            except httpx.HTTPError as exc:
                with self._lock:
                    state.detail = f"probe failed: {type(exc).__name__}"
                continue
            verdict, retry_after, detail = classify(response)
            if verdict == "ok":
                with self._lock:
                    state.status, state.cooldown_until = "ok", 0.0
                    state.detail = quota(response)
            elif verdict == "exhausted":
                self.mark_exhausted(state, retry_after, detail)
            elif verdict == "invalid":
                self.mark_invalid(state, detail)
            else:
                with self._lock:
                    state.detail = f"probe: {detail}"
        return self.status()

    def status(self) -> list[dict[str, Any]]:
        now = self._clock()
        with self._lock:
            return [
                {
                    "provider": self.provider,
                    "priority": k.priority,
                    "key": k.fingerprint,
                    "status": k.status,
                    "retry_in_s": round(max(0.0, k.cooldown_until - now), 1)
                    if k.status == "exhausted"
                    else None,
                    "uses": k.uses,
                    "detail": k.detail,
                }
                for k in self._keys
            ]


_POOLS: dict[tuple[str, tuple[str, ...]], KeyPool] = {}
_POOLS_LOCK = threading.Lock()


def pool_for(provider: str, keys: Sequence[str]) -> KeyPool:
    """The process-wide pool for this provider and key list (state survives between requests)."""
    ident = (provider, tuple(fingerprint(k) for k in keys))
    with _POOLS_LOCK:
        pool = _POOLS.get(ident)
        if pool is None:
            pool = _POOLS[ident] = KeyPool(provider, keys)
        return pool


def reset_pools() -> None:
    """Forget all learned key state (tests)."""
    with _POOLS_LOCK:
        _POOLS.clear()


# ── classifying provider responses ───────────────────────────────────────────


def _seconds(text: str) -> float | None:
    try:
        return float(text.strip().removesuffix("s"))
    except (AttributeError, ValueError):
        return None


def _error_body(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    error = body.get("error") if isinstance(body, dict) else None
    return error if isinstance(error, dict) else {}


def classify(response: httpx.Response) -> tuple[str, float | None, str]:
    """``(verdict, retry_after_s, detail)`` with verdict ``ok``, ``exhausted``, ``invalid`` or
    ``error`` (a transient or request problem that another key would not fix)."""
    code = response.status_code
    if code == 200:  # noqa: PLR2004
        return "ok", None, ""
    error = _error_body(response)
    status = str(error.get("status", ""))
    raw_details = error.get("details")
    details: list[Any] = raw_details if isinstance(raw_details, list) else []
    reasons = {str(d.get("reason", "")) for d in details if isinstance(d, dict)}
    quota_ids = [
        str(v.get("quotaId", ""))
        for d in details
        if isinstance(d, dict)
        for v in (d.get("violations") or [])
        if isinstance(v, dict)
    ]
    retry = _seconds(response.headers.get("retry-after", ""))
    for d in details:
        if isinstance(d, dict) and str(d.get("@type", "")).endswith("RetryInfo"):
            retry = _seconds(str(d.get("retryDelay", ""))) or retry
    if code == 429 or status == "RESOURCE_EXHAUSTED":  # noqa: PLR2004
        daily = any("PerDay" in q for q in quota_ids)
        if daily and retry is None:
            retry = DAILY_COOLDOWN_S
        scope = "daily quota" if daily else "rate limit"
        return "exhausted", retry, f"HTTP {code}: {scope} reached"
    if code in (401, 403) or "API_KEY_INVALID" in reasons:
        message = str(error.get("message", ""))
        why = "project denied access" if "denied access" in message else "key rejected"
        return "invalid", None, f"HTTP {code}: {why}"
    if code == 404:  # noqa: PLR2004 - the model exists for some projects and not this key's
        return "invalid", None, "HTTP 404: model not available to this key"
    return "error", None, f"HTTP {code}"
