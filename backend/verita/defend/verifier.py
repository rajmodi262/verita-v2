"""The deterministic narrative verifier (PIVOT §8.3).

A narrative is a list of sentences ``{"section", "text", "evidence_ids"}``. For each sentence:

1. **Citation** — at least one evidence ID, and every cited ID exists in this case.
2. **Claims** — every amount, count, date, duration, account, bank, typology and percentage the
   sentence states is extracted (:mod:`verita.defend.claims`).
3. **Checking** — each claim must match a fact of the *cited* evidence (not of the case at
   large: citing the wrong item is a failure). Amounts: same currency, within 0.5% or within
   the writer's rounding ("$48.5k"); counts, dates, accounts, banks, typologies: exact;
   durations and percentages: rounding-aware.

Then the narrative as a whole must **cover** the dominant path, the case total, the date range
and the typology at least once.

Verification never consults a model; the same input always yields the same report, so the
report itself can be signed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from verita.defend.claims import Claim, extract
from verita.defend.evidence import facts

VERIFIER_VERSION = "1.0.0"
SECTIONS = ("who", "what", "when", "where", "why", "how")
AMOUNT_TOLERANCE = 0.005
PERCENT_FLOOR = 0.5

_COUNT_GROUPS = {
    "payment": "payment",
    "transaction": "payment",
    "transfer": "payment",
    "hop": "payment",
    "account": "account",
    "counterparty": "account",
    "payee": "account",
    "payer": "account",
    "bank": "bank",
    "alert": "alert",
    "day": "day",
}


@dataclass
class ClaimResult:
    kind: str
    text: str
    passed: bool
    expected: str | None  # the evidence value it matched, or the closest one
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class SentenceResult:
    index: int
    section: str
    text: str
    evidence_ids: list[str]
    passed: bool
    errors: list[str] = field(default_factory=list)
    claims: list[ClaimResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out = {k: v for k, v in self.__dict__.items() if k != "claims"}
        out["claims"] = [c.to_dict() for c in self.claims]
        return out


@dataclass
class Report:
    passed: bool
    sentences: list[SentenceResult]
    coverage: dict[str, bool]
    errors: list[str]
    version: str = VERIFIER_VERSION

    @property
    def failed_sentences(self) -> list[int]:
        return [s.index for s in self.sentences if not s.passed]

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "verifier_version": self.version,
            "sentences": [s.to_dict() for s in self.sentences],
            "coverage": self.coverage,
            "errors": self.errors,
            "failed_sentences": self.failed_sentences,
        }


def _group(noun: str) -> str:
    return _COUNT_GROUPS.get(noun, noun)


def _matches(claim: Claim, fact: Claim) -> bool:  # noqa: PLR0911 - one rule per kind
    if claim.kind != fact.kind:
        return False
    if claim.kind == "amount":
        if claim.unit != fact.unit:
            return False
        c, f = float(claim.value), float(fact.value)
        return abs(c - f) <= max(AMOUNT_TOLERANCE * abs(f), claim.resolution)
    if claim.kind == "count":
        if fact.unit != "any" and _group(claim.unit) != _group(fact.unit):
            return False
        return float(claim.value) == float(fact.value)
    if claim.kind == "duration":
        c, f = float(claim.value), float(fact.value)
        return abs(c - f) <= max(claim.resolution, AMOUNT_TOLERANCE * abs(f))
    if claim.kind == "percent":
        c, f = float(claim.value), float(fact.value)
        return abs(c - f) <= max(claim.resolution, PERCENT_FLOOR)
    return str(claim.value) == str(fact.value)


def _closest(claim: Claim, pool: Sequence[Claim]) -> str | None:
    same = [f for f in pool if f.kind == claim.kind]
    if not same:
        return None
    if claim.kind in ("amount", "count", "duration", "percent"):
        best = min(same, key=lambda f: abs(float(f.value) - float(claim.value)))
        return best.describe()
    return same[0].describe()


def check_claim(claim: Claim, pool: Sequence[Claim]) -> ClaimResult:
    for fact in pool:
        if _matches(claim, fact):
            return ClaimResult(
                claim.kind, claim.text, True, fact.describe(), "matches cited evidence"
            )
    closest = _closest(claim, pool)
    detail = (
        f"no cited evidence states this {claim.kind}"
        if closest is None
        else f"cited evidence says {closest}"
    )
    return ClaimResult(claim.kind, claim.text, False, closest, detail)


def verify(
    sentences: Sequence[Mapping[str, Any]], evidence: Mapping[str, Mapping[str, Any]]
) -> Report:
    """Check every sentence against the case's evidence items (keyed by evidence ID)."""
    fact_cache: dict[str, list[Claim]] = {}

    def facts_of(ev_id: str) -> list[Claim]:
        if ev_id not in fact_cache:
            fact_cache[ev_id] = facts(dict(evidence[ev_id]))
        return fact_cache[ev_id]

    results: list[SentenceResult] = []
    for i, s in enumerate(sentences):
        text = str(s.get("text", ""))
        ids = [str(x) for x in s.get("evidence_ids", [])]
        section = str(s.get("section", ""))
        res = SentenceResult(i, section, text, ids, True)
        if section not in SECTIONS:
            res.errors.append(f"unknown section {section!r}")
        if not ids:
            res.errors.append("uncited: a sentence must cite at least one evidence ID")
        unknown = [x for x in ids if x not in evidence]
        if unknown:
            res.errors.append(f"cites evidence not in this case: {', '.join(unknown)}")
        pool = [f for x in ids if x in evidence for f in facts_of(x)]
        for claim in extract(text):
            result = check_claim(claim, pool)
            res.claims.append(result)
        res.passed = not res.errors and all(c.passed for c in res.claims)
        results.append(res)
    coverage = _coverage(results, evidence)
    errors = [
        f"coverage: the narrative never states the {k}" for k, ok in coverage.items() if not ok
    ]
    if not sentences:
        errors.insert(0, "the narrative is empty")
    passed = bool(sentences) and all(r.passed for r in results) and not errors
    return Report(passed, results, coverage, errors)


def _coverage(
    results: Sequence[SentenceResult], evidence: Mapping[str, Mapping[str, Any]]
) -> dict[str, bool]:
    """Dominant path cited; case total, both ends of the date range and typology stated."""
    case = next((e for e in evidence.values() if e["kind"] == "case"), None)
    paths = {k for k, e in evidence.items() if e["kind"] == "path"}
    passed_claims = [c for r in results if r.passed for c in r.claims if c.passed]
    stated = {(c.kind, c.expected) for c in passed_claims}
    cited = {x for r in results if r.passed for x in r.evidence_ids}
    out = {"dominant path": not paths or bool(paths & cited)}
    if case is not None:
        p = case["payload"]
        total = Claim("amount", p["total_usd"], "", "US Dollar").describe()
        out["case total"] = ("amount", total) in stated
        span = Claim("date_range", f"{p['first_day']}..{p['last_day']}", "").describe()
        first = Claim("date", p["first_day"], "").describe()
        last = Claim("date", p["last_day"], "").describe()
        out["date range"] = ("date_range", span) in stated or (
            ("date", first) in stated and ("date", last) in stated
        )
        if p["typology"] == "UNATTRIBUTED":
            # nothing to name: the narrative must say so, in a sentence that passed
            out["typology"] = any(r.passed and "unattributed" in r.text.lower() for r in results)
        else:
            out["typology"] = (
                "typology",
                Claim("typology", p["typology"], "").describe(),
            ) in stated
    return out
