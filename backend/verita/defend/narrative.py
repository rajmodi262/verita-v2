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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, Field, ValidationError

from verita.defend.evidence import split_account
from verita.pipeline.config import REPO_ROOT

PROMPT_PATH = REPO_ROOT / "prompts" / "narrative_v1.md"
PROMPT_VERSION = "narrative_v1"
MAX_ATTEMPTS = 2
MAX_HOPS_WRITTEN = 4
MAX_REASONS_WRITTEN = 3
MAX_ALERTS_WRITTEN = 3


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


@dataclass
class GeminiProvider:
    api_key: str
    model: str
    timeout: float = 45.0
    name: str = "gemini"
    base_url: str = "https://generativelanguage.googleapis.com/v1beta"

    def complete(self, system: str, user: str) -> str:
        response = httpx.post(
            f"{self.base_url}/models/{self.model}:generateContent",
            headers={"x-goog-api-key": self.api_key},
            json={
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
            },
            timeout=self.timeout,
        )
        if response.status_code != 200:  # noqa: PLR2004
            msg = f"gemini HTTP {response.status_code}"
            raise ProviderError(msg)
        try:
            parts = response.json()["candidates"][0]["content"]["parts"]
            return "".join(str(p.get("text", "")) for p in parts)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            msg = "gemini returned no text"
            raise ProviderError(msg) from exc


@dataclass
class GroqProvider:
    api_key: str
    model: str
    timeout: float = 45.0
    name: str = "groq"
    base_url: str = "https://api.groq.com/openai/v1"

    def complete(self, system: str, user: str) -> str:
        response = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
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
        if response.status_code != 200:  # noqa: PLR2004
            msg = f"groq HTTP {response.status_code}"
            raise ProviderError(msg)
        try:
            return str(response.json()["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            msg = "groq returned no text"
            raise ProviderError(msg) from exc


def providers_from_settings(settings: Any) -> list[Provider]:
    """Configured providers that have a key, in the configured order."""
    out: list[Provider] = []
    for name in settings.llm_providers:
        if name == "gemini" and settings.gemini_api_key is not None:
            key = settings.gemini_api_key.get_secret_value()
            out.append(GeminiProvider(key, settings.gemini_model, settings.llm_timeout_seconds))
        elif name == "groq" and settings.groq_api_key is not None:
            key = settings.groq_api_key.get_secret_value()
            out.append(GroqProvider(key, settings.groq_model, settings.llm_timeout_seconds))
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
