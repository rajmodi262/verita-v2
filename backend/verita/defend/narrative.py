"""Narrative drafting (PIVOT §8.2): Gemini → Groq → offline template, one JSON shape.

Every draft is a list of sentences ``{"section", "text", "evidence_ids"}`` plus provenance:
which provider wrote it, the model, and the SHA-256 of the prompt template. Free prose is
rejected: a provider whose output does not parse into that shape counts as a failure and the
next provider is tried. The offline template needs no key and is deterministic — CI and the
fault-injection evaluation use it, and the UI labels which mode wrote each narrative.

Only the structured evidence JSON reaches a model, wrapped in an EVIDENCE block that the
prompt declares to be data; the verifier is the backstop either way.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, Field, ValidationError

from verita.defend.evidence import split_account
from verita.defend.keypool import KeyPool, classify, pool_for
from verita.pipeline.config import REPO_ROOT

PROMPT_PATH = REPO_ROOT / "prompts" / "narrative_v1.md"
PROMPT_VERSION = "narrative_v1"
MAX_ATTEMPTS = 2
MAX_HOPS_WRITTEN = 4
MAX_REASONS_WRITTEN = 3
MAX_ALERTS_WRITTEN = 3
# A quota probe is one token; a key that cannot answer within this is reported, not waited on.
PROBE_TIMEOUT_S = 15.0


class SentenceModel(BaseModel):
    section: str = Field(pattern="^(who|what|when|where|why|how)$")
    text: str = Field(min_length=1, max_length=600)
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)


class NarrativeModel(BaseModel):
    sentences: list[SentenceModel] = Field(min_length=1, max_length=40)


class ProviderError(RuntimeError):
    """A provider failed (network, quota, or output that is not the required JSON)."""


@dataclass
class Draft:
    sentences: list[dict[str, Any]]
    mode: str  # "llm" or "offline"
    provider: str
    model: str
    prompt_hash: str
    attempts: list[dict[str, str]] = field(default_factory=list)
    seconds: float = 0.0


def prompt_template() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def prompt_hash() -> str:
    return hashlib.sha256(prompt_template().encode("utf-8")).hexdigest()


def evidence_block(evidence: Mapping[str, Mapping[str, Any]]) -> str:
    items = sorted(evidence.values(), key=lambda e: e["id"])
    body = json.dumps(items, ensure_ascii=False, sort_keys=True, indent=1)
    return f"<EVIDENCE>\n{body}\n</EVIDENCE>"


def parse_output(raw: str) -> list[dict[str, Any]]:
    """Strictly parse a provider's reply into sentences (a fenced JSON block is tolerated)."""
    text = raw.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    try:
        model = NarrativeModel.model_validate_json(text)
    except ValidationError as exc:
        msg = f"output is not the narrative JSON shape: {exc.error_count()} errors"
        raise ProviderError(msg) from exc
    return [s.model_dump() for s in model.sentences]


class Provider(Protocol):
    name: str
    model: str

    def complete(self, system: str, user: str) -> str: ...

    def probe(self) -> list[dict[str, Any]]: ...


def _as_pool(name: str, keys: KeyPool | Sequence[str] | str) -> KeyPool:
    if isinstance(keys, KeyPool):
        return keys
    return KeyPool(name, [keys] if isinstance(keys, str) else list(keys))


def _with_pool(
    pool: KeyPool,
    send: Callable[[str], httpx.Response],
    extract: Callable[[httpx.Response], str],
) -> str:
    """Send with the best available key; on quota exhaustion move to the next key at once."""
    skipped: list[str] = []
    for state in pool.available():
        response = send(state.key)
        verdict, retry_after, detail = classify(response)
        if verdict == "ok":
            text = extract(response)
            pool.mark_ok(state)
            return text
        if verdict == "exhausted":
            pool.mark_exhausted(state, retry_after, detail)
        elif verdict == "invalid":
            pool.mark_invalid(state, detail)
        else:  # transient or a bad request: another key would not help
            msg = f"{pool.provider} {detail} (key {state.fingerprint})"
            raise ProviderError(msg)
        skipped.append(f"{state.fingerprint} {detail}")
    wait = pool.next_retry_in()
    when = f"; next key free in {wait:.0f} s" if wait is not None else ""
    tried = "; ".join(skipped) or "every key is cooling down or rejected"
    msg = f"{pool.provider}: no key with quota left of {len(pool)} ({tried}){when}"
    raise ProviderError(msg)


@dataclass
class GeminiProvider:
    keys: KeyPool | Sequence[str] | str
    model: str
    timeout: float = 45.0
    name: str = "gemini"
    base_url: str = "https://generativelanguage.googleapis.com/v1beta"

    def __post_init__(self) -> None:
        self.pool = _as_pool(self.name, self.keys)

    def complete(self, system: str, user: str) -> str:
        def send(key: str) -> httpx.Response:
            return httpx.post(
                f"{self.base_url}/models/{self.model}:generateContent",
                headers={"x-goog-api-key": key},
                json={
                    "systemInstruction": {"parts": [{"text": system}]},
                    "contents": [{"role": "user", "parts": [{"text": user}]}],
                    "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
                },
                timeout=self.timeout,
            )

        def extract(response: httpx.Response) -> str:
            try:
                parts = response.json()["candidates"][0]["content"]["parts"]
                return "".join(str(p.get("text", "")) for p in parts)
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                msg = "gemini returned no text"
                raise ProviderError(msg) from exc

        return _with_pool(self.pool, send, extract)

    def probe(self) -> list[dict[str, Any]]:
        """One-token request per key: is it accepted, and does it have quota left right now?
        (The Gemini API exposes no remaining-quota figure, so this is the honest check.)"""

        def send(key: str) -> httpx.Response:
            return httpx.post(
                f"{self.base_url}/models/{self.model}:generateContent",
                headers={"x-goog-api-key": key},
                json={
                    "contents": [{"role": "user", "parts": [{"text": "ping"}]}],
                    "generationConfig": {"maxOutputTokens": 1},
                },
                timeout=PROBE_TIMEOUT_S,
            )

        return self.pool.probe(send)


@dataclass
class GroqProvider:
    keys: KeyPool | Sequence[str] | str
    model: str
    timeout: float = 45.0
    name: str = "groq"
    base_url: str = "https://api.groq.com/openai/v1"

    def __post_init__(self) -> None:
        self.pool = _as_pool(self.name, self.keys)

    def complete(self, system: str, user: str) -> str:
        def send(key: str) -> httpx.Response:
            return httpx.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": self.model,
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                },
                timeout=self.timeout,
            )

        def extract(response: httpx.Response) -> str:
            try:
                return str(response.json()["choices"][0]["message"]["content"])
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                msg = "groq returned no text"
                raise ProviderError(msg) from exc

        return _with_pool(self.pool, send, extract)

    def probe(self) -> list[dict[str, Any]]:
        """One-token request per key; Groq's rate-limit headers give the quota left."""

        def send(key: str) -> httpx.Response:
            return httpx.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": self.model,
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "ping"}],
                },
                timeout=PROBE_TIMEOUT_S,
            )

        def quota(response: httpx.Response) -> str:
            h = response.headers
            parts = []
            if "x-ratelimit-remaining-requests" in h:
                parts.append(
                    f"requests {h['x-ratelimit-remaining-requests']}/"
                    f"{h.get('x-ratelimit-limit-requests', '?')} left today"
                )
            if "x-ratelimit-remaining-tokens" in h:
                parts.append(
                    f"tokens {h['x-ratelimit-remaining-tokens']}/"
                    f"{h.get('x-ratelimit-limit-tokens', '?')} left this minute"
                )
            return "; ".join(parts)

        return self.pool.probe(send, quota)


def providers_from_settings(settings: Any) -> list[Provider]:
    """Configured providers that have at least one key, in the configured order.

    Each provider draws on the process-wide key pool for its keys, so a key found exhausted
    by one draft is skipped by the next until its retry time.
    """
    out: list[Provider] = []
    timeout = settings.llm_timeout_seconds
    for name in settings.llm_providers:
        keys = settings.llm_keys(name)
        if not keys:
            continue
        if name == "gemini":
            out.append(GeminiProvider(pool_for(name, keys), settings.gemini_model, timeout))
        elif name == "groq":
            out.append(GroqProvider(pool_for(name, keys), settings.groq_model, timeout))
    return out


def draft(
    evidence: Mapping[str, Mapping[str, Any]],
    providers: Sequence[Provider],
    mode: str = "auto",
) -> Draft:
    """Draft with the first provider that returns valid JSON; offline when none does.

    ``mode`` is ``auto`` (LLM providers, then offline), ``llm`` (providers only — raises when all
    fail) or ``offline``.
    """
    started = time.perf_counter()
    attempts: list[dict[str, str]] = []
    if mode != "offline":
        system = prompt_template()
        user = evidence_block(evidence)
        for provider in providers:
            for attempt in range(MAX_ATTEMPTS):
                try:
                    sentences = parse_output(provider.complete(system, user))
                except (ProviderError, httpx.HTTPError) as exc:
                    attempts.append(
                        {"provider": provider.name, "attempt": str(attempt + 1), "error": str(exc)}
                    )
                    continue
                return Draft(
                    sentences,
                    "llm",
                    provider.name,
                    provider.model,
                    prompt_hash(),
                    attempts,
                    round(time.perf_counter() - started, 3),
                )
        if mode == "llm":
            msg = "every LLM provider failed: " + "; ".join(a["error"] for a in attempts)
            raise ProviderError(msg)
    return Draft(
        offline_sentences(evidence),
        "offline",
        "template",
        f"offline-template-{PROMPT_VERSION}",
        prompt_hash(),
        attempts,
        round(time.perf_counter() - started, 3),
    )


# ── offline template ─────────────────────────────────────────────────────────


def money(amount: float, currency: str) -> str:
    """Two decimals, or as many as a small amount needs (0.0034 Bitcoin, not 0.00)."""
    if amount == 0 or abs(amount) >= 1:
        return f"{amount:,.2f} {currency}"
    digits = f"{abs(amount):.8f}".rstrip("0")
    return f"{'-' if amount < 0 else ''}{digits} {currency}"


def duration(minutes: float) -> str:
    if minutes >= 48 * 60:
        return f"{minutes / 1440:.1f} days"
    if minutes >= 120:  # noqa: PLR2004
        return f"{minutes / 60:.1f} hours"
    return f"{minutes:.1f} minutes"


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _banks(banks: Sequence[str]) -> str:
    if len(banks) == 1:
        return f"bank {banks[0]}"
    return "banks " + ", ".join(banks[:-1]) + f" and {banks[-1]}"


def _s(section: str, text: str, *ids: str) -> dict[str, Any]:
    return {"section": section, "text": text, "evidence_ids": list(ids)}


def _alert_sentences(
    ev: Mapping[str, Mapping[str, Any]], alert: Mapping[str, Any]
) -> list[dict[str, Any]]:
    p = alert["payload"]
    aid = p["alert_id"]
    out = [
        _s(
            "who",
            f"The subject is account {p['account']} at bank {p['bank']}, alerted on {p['date']} "
            f"with a risk score of {p['score'] * 100:.1f}%.",
            alert["id"],
        )
    ]
    path = ev.get(f"EV-PATH-{aid}")
    if path:
        pp = path["payload"]
        first = pp["amounts"][0]
        out.append(
            _s(
                "how",
                f"The dominant path moves {money(first['amount'], first['currency'])} from account "
                f"{pp['accounts'][0]} through {_count(len(pp['txn_ids']), 'payment')} in "
                f"{duration(pp['duration_minutes'])}, ending at account {pp['accounts'][-1]} on "
                f"{pp['last_ts'][:10]}.",
                path["id"],
            )
        )
        for txn_id in pp["txn_ids"][:MAX_HOPS_WRITTEN]:
            t = ev[f"EV-TXN-{txn_id}"]["payload"]
            out.append(
                _s(
                    "how",
                    f"On {t['ts'][:10]}, account {t['from_account']} at bank {t['from_bank']} "
                    f"paid {money(t['amount_paid'], t['currency_paid'])} to account "
                    f"{t['to_account']} at bank {t['to_bank']} by {t['payment_format']}.",
                    f"EV-TXN-{txn_id}",
                )
            )
    for rank in range(1, MAX_REASONS_WRITTEN + 1):
        reason = ev.get(f"EV-REASON-{aid}-{rank}")
        if reason:
            text = reason["payload"]["text"].replace(" — ", "; ").rstrip(".")
            out.append(_s("why", f"Model reason {rank}: {text}.", reason["id"]))
    motif = ev.get(f"EV-MOTIF-{aid}")
    if motif:
        typology = motif["payload"]["typology"]
        if typology == "UNATTRIBUTED":
            text = (
                "The pattern is unattributed to a known typology; the typology model's top class "
                f"has {p['typology_conf'] * 100:.1f}% confidence."
            )
        else:
            text = (
                f"The pattern is consistent with the {typology} typology "
                f"(typology model confidence {p['typology_conf'] * 100:.1f}%)."
            )
        out.append(_s("why", text, alert["id"], motif["id"]))
        for signal in motif["payload"]["signals"]:
            out.append(_s("why", f"Structural signal: the {signal}.", motif["id"]))
    return out


def offline_sentences(evidence: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Deterministic narrative from evidence alone — every number copied, every claim cited."""
    case = next(e for e in evidence.values() if e["kind"] == "case")
    c = case["payload"]
    sentences = [
        _s(
            "what",
            f"Between {c['first_day']} and {c['last_day']} the case file records "
            f"{_count(c['payments'], 'payment')} across {_count(c['accounts'], 'account')}, "
            "totalling "
            f"{money(c['total_usd'], 'US Dollar')} at fixed conversion rates.",
            case["id"],
        ),
        _s(
            "where",
            f"The money moved through {_count(len(c['banks']), 'bank')} ({_banks(c['banks'])}).",
            case["id"],
        ),
    ]
    if c["typology"] != "UNATTRIBUTED":
        sentences.append(
            _s(
                "why",
                f"The majority predicted typology across the case is {c['typology']}.",
                case["id"],
            )
        )
    else:
        sentences.append(
            _s(
                "why",
                "Across the case the activity is unattributed to a known typology.",
                case["id"],
            )
        )
    alerts = sorted(
        (e for e in evidence.values() if e["kind"] == "alert"),
        key=lambda e: e["payload"]["alert_id"],
    )
    for alert in alerts[:MAX_ALERTS_WRITTEN]:
        sentences += _alert_sentences(evidence, alert)
    order = {s: i for i, s in enumerate(("who", "what", "when", "where", "why", "how"))}
    return sorted(sentences, key=lambda s: order[s["section"]])  # stable: keeps hop order


def subject_label(account_id: str) -> str:
    bank, acct = split_account(account_id)
    return f"account {acct} at bank {bank}"
