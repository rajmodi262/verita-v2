"""Key pools: priority order, instant failover on exhausted quota, cooldowns, no key leaks."""

from __future__ import annotations

import time

import httpx
import pytest

from verita.core.config import Settings
from verita.defend import keypool
from verita.defend import narrative as narr
from verita.defend.keypool import KeyPool, classify, fingerprint

GOOD = '{"sentences": [{"section": "what", "text": "x", "evidence_ids": []}]}'
KEYS = ["key-one-secret", "key-two-secret", "key-three-secret"]


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def gemini_ok() -> httpx.Response:
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": GOOD}]}}]})


def gemini_exhausted(retry: str | None = "17s", daily: bool = False) -> httpx.Response:
    details: list[dict] = [
        {
            "@type": "type.googleapis.com/google.rpc.QuotaFailure",
            "violations": [
                {"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}
                if daily
                else {"quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}
            ],
        }
    ]
    if retry:
        details.append({"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": retry})
    return httpx.Response(
        429, json={"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "details": details}}
    )


@pytest.fixture
def server(monkeypatch):
    """Fake provider: answers per key from `answers`, records the order keys were used in."""
    answers: dict[str, httpx.Response] = {}
    used: list[str] = []

    def fake_post(url, headers, json, timeout):
        key = headers.get("x-goog-api-key") or headers["Authorization"].removeprefix("Bearer ")
        used.append(key)
        return answers[key]

    monkeypatch.setattr(narr.httpx, "post", fake_post)

    def no_sleep(_seconds):
        raise AssertionError("failover must not wait")

    monkeypatch.setattr(time, "sleep", no_sleep)
    return answers, used


# ── classifying responses ────────────────────────────────────────────────────


def test_classify_reads_quota_retry_and_rejection():
    assert classify(gemini_ok())[0] == "ok"
    assert classify(gemini_exhausted("17s")) == ("exhausted", 17.0, "HTTP 429: rate limit reached")
    verdict, retry, detail = classify(gemini_exhausted(None, daily=True))
    assert (verdict, retry) == ("exhausted", keypool.DAILY_COOLDOWN_S)
    assert "daily quota" in detail
    groq = httpx.Response(429, headers={"retry-after": "2.5"}, json={"error": {}})
    assert classify(groq)[:2] == ("exhausted", 2.5)
    assert classify(httpx.Response(429, text="not json"))[:2] == ("exhausted", None)
    invalid = httpx.Response(
        400,
        json={"error": {"status": "INVALID_ARGUMENT", "details": [{"reason": "API_KEY_INVALID"}]}},
    )
    assert classify(invalid)[0] == "invalid"
    assert classify(httpx.Response(401, json={}))[0] == "invalid"
    assert classify(httpx.Response(403, json={"error": {"status": "PERMISSION_DENIED"}}))[0] == (
        "invalid"
    )
    denied = httpx.Response(
        403, json={"error": {"message": "Your project has been denied access.", "status": "X"}}
    )
    assert classify(denied) == ("invalid", None, "HTTP 403: project denied access")
    assert classify(httpx.Response(404, json={}))[2] == "HTTP 404: model not available to this key"
    assert classify(httpx.Response(500, json={}))[0] == "error"
    assert classify(httpx.Response(400, json={"error": "flat string"}))[0] == "error"


# ── failover ─────────────────────────────────────────────────────────────────


def test_exhausted_key_fails_over_within_the_same_call(server):
    answers, used = server
    answers.update({KEYS[0]: gemini_exhausted("30s"), KEYS[1]: gemini_ok(), KEYS[2]: gemini_ok()})
    clock = Clock()
    provider = narr.GeminiProvider(KeyPool("gemini", KEYS, clock), "gemini-x")

    assert provider.complete("s", "u") == GOOD
    assert used == [KEYS[0], KEYS[1]]  # one call: tried key 1, moved straight to key 2

    used.clear()
    assert provider.complete("s", "u") == GOOD
    assert used == [KEYS[1]]  # key 1 is cooling down: not even tried

    clock.now += 31  # past key 1's retry time: highest priority again
    answers[KEYS[0]] = gemini_ok()
    used.clear()
    assert provider.complete("s", "u") == GOOD
    assert used == [KEYS[0]]


def test_rejected_key_leaves_rotation_for_good(server):
    answers, used = server
    answers.update({KEYS[0]: httpx.Response(401, json={}), KEYS[1]: gemini_ok()})
    clock = Clock()
    provider = narr.GeminiProvider(KeyPool("gemini", KEYS[:2], clock), "gemini-x")
    provider.complete("s", "u")
    clock.now += 10**6
    used.clear()
    provider.complete("s", "u")
    assert used == [KEYS[1]]


def test_every_key_exhausted_says_when_one_frees_up(server):
    answers, _ = server
    answers.update({KEYS[0]: gemini_exhausted("40s"), KEYS[1]: gemini_exhausted("12s")})
    provider = narr.GeminiProvider(KeyPool("gemini", KEYS[:2], Clock()), "gemini-x")
    with pytest.raises(narr.ProviderError, match=r"no key with quota left of 2.*free in 12 s"):
        provider.complete("s", "u")
    with pytest.raises(narr.ProviderError, match="cooling down or rejected"):
        provider.complete("s", "u")  # nothing available: fails at once, sends nothing


def test_transient_error_does_not_burn_the_other_keys(server):
    answers, used = server
    answers.update({KEYS[0]: httpx.Response(503, json={}), KEYS[1]: gemini_ok()})
    pool = KeyPool("gemini", KEYS[:2], Clock())
    with pytest.raises(narr.ProviderError, match="HTTP 503"):
        narr.GeminiProvider(pool, "gemini-x").complete("s", "u")
    assert used == [KEYS[0]]
    assert pool.status()[0]["status"] == "unused"  # not marked: the key itself is fine


def test_draft_falls_through_to_groq_then_offline(server, evidence):
    answers, used = server
    groq_key = "groq-key-secret"
    answers.update(
        {
            KEYS[0]: gemini_exhausted(),
            KEYS[1]: gemini_exhausted(),
            groq_key: httpx.Response(200, json={"choices": [{"message": {"content": GOOD}}]}),
        }
    )
    gemini = narr.GeminiProvider(KeyPool("gemini", KEYS[:2], Clock()), "gemini-x")
    groq = narr.GroqProvider(KeyPool("groq", [groq_key], Clock()), "llama")
    result = narr.draft(evidence, [gemini, groq])
    assert (result.mode, result.provider) == ("llm", "groq")
    assert used[:3] == [KEYS[0], KEYS[1], groq_key]

    answers[groq_key] = httpx.Response(429, headers={"retry-after": "5"}, json={})
    groq2 = narr.GroqProvider(KeyPool("groq", [groq_key], Clock()), "llama")
    assert narr.draft(evidence, [gemini, groq2]).mode == "offline"


# ── secrecy, probing, settings ───────────────────────────────────────────────


def test_keys_never_appear_in_errors_status_or_repr(server):
    answers, _ = server
    answers.update({k: gemini_exhausted() for k in KEYS})
    pool = KeyPool("gemini", KEYS, Clock())
    with pytest.raises(narr.ProviderError) as err:
        narr.GeminiProvider(pool, "gemini-x").complete("s", "u")
    shown = [str(err.value), repr(pool.status()), repr(pool.available()), repr(pool._keys)]
    for key in KEYS:
        assert all(key not in text for text in shown)
    assert fingerprint(KEYS[0]) in str(err.value)
    assert fingerprint(KEYS[0]).startswith("sha256:") and len(fingerprint(KEYS[0])) == 15


def test_probe_checks_every_key_and_primes_the_pool(server):
    answers, used = server
    answers.update(
        {
            KEYS[0]: gemini_exhausted("50s"),
            KEYS[1]: httpx.Response(
                400, json={"error": {"details": [{"reason": "API_KEY_INVALID"}]}}
            ),
            KEYS[2]: gemini_ok(),
        }
    )
    pool = KeyPool("gemini", KEYS, Clock())
    rows = narr.GeminiProvider(pool, "gemini-x").probe()
    assert [r["status"] for r in rows] == ["exhausted", "invalid", "ok"]
    assert rows[0]["retry_in_s"] == 50.0
    assert used == KEYS
    assert [k.fingerprint for k in pool.available()] == [fingerprint(KEYS[2])]


def test_probe_records_transport_failures_without_condemning_the_key(monkeypatch):
    def boom(url, headers, json, timeout):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(narr.httpx, "post", boom)
    rows = narr.GeminiProvider(KeyPool("gemini", KEYS[:1], Clock()), "g").probe()
    assert rows[0]["status"] == "unused" and "ConnectError" in rows[0]["detail"]


def test_groq_probe_reports_remaining_quota(server):
    answers, _ = server
    answers["g"] = httpx.Response(
        200,
        headers={
            "x-ratelimit-remaining-requests": "14399",
            "x-ratelimit-limit-requests": "14400",
            "x-ratelimit-remaining-tokens": "5999",
            "x-ratelimit-limit-tokens": "6000",
        },
        json={"choices": [{"message": {"content": "p"}}]},
    )
    (row,) = narr.GroqProvider(KeyPool("groq", ["g"], Clock()), "llama").probe()
    assert row["status"] == "ok"
    assert row["detail"] == "requests 14399/14400 left today; tokens 5999/6000 left this minute"


def test_settings_split_keys_in_priority_order_and_fall_back_to_the_single_key():
    s = Settings(_env_file=None, gemini_api_keys=" a , b,,a ", gemini_api_key="legacy")
    assert s.llm_keys("gemini") == ["a", "b"]  # the pool wins; duplicates dropped
    s = Settings(_env_file=None, gemini_api_keys="", groq_api_key="legacy")
    assert s.llm_keys("gemini") == [] and s.llm_keys("groq") == ["legacy"]
    assert "a" not in repr(Settings(_env_file=None, gemini_api_keys="a").gemini_api_keys)


def test_pools_are_shared_per_process_so_cooldowns_persist():
    keypool.reset_pools()
    s = Settings(_env_file=None, llm_providers=["gemini"], gemini_api_keys="a,b")
    first = narr.providers_from_settings(s)[0]
    second = narr.providers_from_settings(s)[0]
    assert first.pool is second.pool
    other = Settings(_env_file=None, llm_providers=["gemini"], gemini_api_keys="c")
    assert narr.providers_from_settings(other)[0].pool is not first.pool
    keypool.reset_pools()


# ── the batch LLM evaluation waits out short limits; interactive drafts never do ─────────


class CoolingProvider:
    """Fails like a pool whose only key is briefly rate-limited, then succeeds."""

    name, model = "gemini", "gemini-x"

    def __init__(self, failures: int, retry_s: float) -> None:
        self.pool = KeyPool("gemini", ["k"])
        self.failures, self.retry_s, self.calls = failures, retry_s, 0

    def complete(self, system, user):
        self.calls += 1
        if self.calls <= self.failures:
            self.pool.mark_exhausted(self.pool._keys[0], self.retry_s, "HTTP 429: rate limit")
            raise narr.ProviderError("gemini: no key with quota left of 1")
        return GOOD


def test_llm_eval_waits_for_a_short_reset_then_scores_the_draft(monkeypatch, evidence):
    from verita.defend import evaluation

    slept: list[float] = []
    monkeypatch.setattr(evaluation.time, "sleep", slept.append)
    provider = CoolingProvider(failures=narr.MAX_ATTEMPTS, retry_s=20.0)
    out = evaluation._llm_eval([(None, evidence)], [provider])
    assert (out["drafts"], out["provider_failures"]) == (1, 0)
    assert len(slept) == 1 and 19 < slept[0] <= 21
    assert out["drafted_by"] == {"gemini/gemini-x": 1}


def test_llm_eval_does_not_wait_out_a_daily_quota_and_says_why(monkeypatch, evidence):
    from verita.defend import evaluation

    monkeypatch.setattr(evaluation.time, "sleep", lambda _s: pytest.fail("must not wait"))
    long_reset = CoolingProvider(failures=99, retry_s=evaluation.LLM_MAX_WAIT_S + 1)
    out = evaluation._llm_eval([(None, evidence)], [long_reset])
    assert out["provider_failures"] == 1 and out["failure_reasons"] == {"gemini: quota": 1}
    assert out["seconds_waiting_for_quota"] == 0


def test_failure_reasons_are_categorised_per_provider():
    from verita.defend.evaluation import _category, _failure_reason

    assert _category("gemini: no key with quota left of 3") == "quota"
    assert _category("The read operation timed out") == "timeout"
    assert _category("groq HTTP 413 (key sha256:1)") == "request too large"
    assert _category("gemini HTTP 503 (key sha256:1)") == "provider unavailable"
    assert _category("output is not the narrative JSON shape: 2 errors") == (
        "output not the required JSON"
    )
    assert _category("weird") == "other"
    attempts = [
        {"provider": "gemini", "attempt": "1", "error": "gemini: no key with quota left of 4"},
        {"provider": "groq", "attempt": "1", "error": "The read operation timed out"},
        {"provider": "groq", "attempt": "2", "error": "groq HTTP 413 (key sha256:1)"},
    ]
    assert _failure_reason(attempts) == "gemini: quota; groq: request too large"


def test_groq_caps_reserved_output_so_requests_fit_the_minute_limit(monkeypatch):
    sent: list[dict] = []

    def capture(url, headers, json, timeout):
        sent.append(json)
        return httpx.Response(200, json={"choices": [{"message": {"content": GOOD}}]})

    monkeypatch.setattr(narr.httpx, "post", capture)
    narr.GroqProvider(KeyPool("groq", ["g"], Clock()), "gpt-oss").complete("s", "u")
    narr.GroqProvider(KeyPool("groq", ["g"], Clock()), "qwen", reasoning_effort=None).complete(
        "s", "u"
    )
    assert sent[0]["max_completion_tokens"] == 2000 and sent[0]["reasoning_effort"] == "low"
    assert "reasoning_effort" not in sent[1]


def test_evidence_block_is_compact_json():
    block = narr.evidence_block({"E1": {"id": "E1", "kind": "case", "payload": {"a": 1}}})
    assert block == '<EVIDENCE>\n[{"id":"E1","kind":"case","payload":{"a":1}}]\n</EVIDENCE>'
