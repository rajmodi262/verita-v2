"""Fault injection for the verifier's adversarial evaluation (PIVOT §8.4).

Each fault takes a clean narrative and plants exactly one error of a known type in one sentence,
the way a hallucinating writer would:

``amount_small``         an amount off by 3% (past the 0.5% tolerance, close enough to look right)
``amount_large``         an amount off by 80%
``wrong_date``           a date shifted by three days
``swapped_account``      an account replaced by another real account absent from the cited evidence
``invented_counterparty`` a new sentence naming an account the evidence never mentions
``wrong_typology``       the typology replaced by a different one
``wrong_count``          a count off by two
``uncited_sentence``     a sentence's citations removed
``irrelevant_citation``  citations replaced by a real item that supports none of the claims

A fault that has no target in a narrative (e.g. no date to shift) yields no variant, so each
type's denominator is the number of narratives it could be planted in.
"""

from __future__ import annotations

import copy
import random
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from verita.defend.claims import TYPOLOGIES, Claim, extract
from verita.defend.evidence import facts
from verita.defend.verifier import check_claim

FAULTS = (
    "amount_small",
    "amount_large",
    "wrong_date",
    "swapped_account",
    "invented_counterparty",
    "wrong_typology",
    "wrong_count",
    "uncited_sentence",
    "irrelevant_citation",
)

Sentences = list[dict[str, Any]]


@dataclass
class Variant:
    fault: str
    sentence: int  # index of the sentence that carries the fault
    sentences: Sentences
    description: str


def _with_number(raw: str, value: float) -> str:
    """Re-spell ``value`` with the thousands separators and decimals ``raw`` used."""
    decimals = len(raw.split(".")[1]) if "." in raw else 0
    grouped = "," in raw
    return f"{value:,.{decimals}f}" if grouped else f"{value:.{decimals}f}"


def _replace_span(text: str, span: tuple[int, int], new: str) -> str:
    return text[: span[0]] + new + text[span[1] :]


def _claims(sentences: Sentences, kind: str) -> list[tuple[int, Claim]]:
    return [(i, c) for i, s in enumerate(sentences) for c in extract(s["text"]) if c.kind == kind]


def _scale_amount(
    sentences: Sentences, rng: random.Random, factor: float
) -> tuple[int, str] | None:
    targets = [(i, c) for i, c in _claims(sentences, "amount") if float(c.value) > 0]
    if not targets:
        return None
    i, claim = rng.choice(targets)
    text = sentences[i]["text"]
    number = re.search(r"\d[\d,]*(?:\.\d+)?", claim.text)
    if number is None:
        return None
    start = claim.span[0] + number.start()
    end = claim.span[0] + number.end()
    raw = number.group(0)
    value = float(raw.replace(",", ""))
    new = _with_number(raw, value * factor)
    if new == raw:  # too small to show at the written precision: add digits
        new = f"{value * factor:.8f}".rstrip("0")
    if float(new.replace(",", "")) == value:  # zero stays zero: no fault can be planted here
        return None
    sentences[i]["text"] = _replace_span(text, (start, end), new)
    return i, f"{raw} → {new}"


def _wrong_date(
    sentences: Sentences, rng: random.Random, _: Mapping[str, Any]
) -> tuple[int, str] | None:
    targets = [
        (i, c) for i, c in _claims(sentences, "date") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", c.text)
    ]
    if not targets:
        return None
    i, claim = rng.choice(targets)
    new = (date.fromisoformat(claim.text) + timedelta(days=3)).isoformat()
    sentences[i]["text"] = _replace_span(sentences[i]["text"], claim.span, new)
    return i, f"{claim.text} → {new}"


def _swapped_account(
    sentences: Sentences, rng: random.Random, ctx: Mapping[str, Any]
) -> tuple[int, str] | None:
    targets = _claims(sentences, "account")
    foreign = list(ctx["foreign_accounts"])
    if not targets or not foreign:
        return None
    i, claim = rng.choice(targets)
    new = rng.choice(foreign)
    start = claim.span[1] - len(str(claim.value))
    sentences[i]["text"] = _replace_span(sentences[i]["text"], (start, claim.span[1]), new)
    return i, f"{claim.value} → {new}"


def _invented_counterparty(
    sentences: Sentences, rng: random.Random, ctx: Mapping[str, Any]
) -> tuple[int, str] | None:
    hops = [i for i, s in enumerate(sentences) if s["section"] == "how" and " paid " in s["text"]]
    foreign = list(ctx["foreign_accounts"])
    if not hops or not foreign:
        return None
    src = rng.choice(hops)
    new = rng.choice(foreign)
    sentence = {
        "section": "how",
        "text": f"The funds were then forwarded to account {new}.",
        "evidence_ids": list(sentences[src]["evidence_ids"]),
    }
    sentences.insert(src + 1, sentence)
    return src + 1, f"added a payment to account {new}"


def _wrong_typology(
    sentences: Sentences, rng: random.Random, _: Mapping[str, Any]
) -> tuple[int, str] | None:
    targets = _claims(sentences, "typology")
    if not targets:
        return None
    i, claim = rng.choice(targets)
    new = rng.choice([t for t in TYPOLOGIES if t != claim.value])
    sentences[i]["text"] = _replace_span(sentences[i]["text"], claim.span, new)
    return i, f"{claim.value} → {new}"


def _wrong_count(
    sentences: Sentences, rng: random.Random, _: Mapping[str, Any]
) -> tuple[int, str] | None:
    targets = _claims(sentences, "count")
    if not targets:
        return None
    i, claim = rng.choice(targets)
    number = re.match(r"\d[\d,]*", claim.text)
    if number is None:
        return None
    new = str(int(number.group(0).replace(",", "")) + 2)
    span = (claim.span[0], claim.span[0] + number.end())
    sentences[i]["text"] = _replace_span(sentences[i]["text"], span, new)
    return i, f"{number.group(0)} → {new}"


def _uncited(
    sentences: Sentences, rng: random.Random, _: Mapping[str, Any]
) -> tuple[int, str] | None:
    i = rng.randrange(len(sentences))
    sentences[i]["evidence_ids"] = []
    return i, "citations removed"


def _irrelevant(
    sentences: Sentences, rng: random.Random, ctx: Mapping[str, Any]
) -> tuple[int, str] | None:
    """Cite a real item that establishes none of the sentence's claims."""
    evidence: Mapping[str, Mapping[str, Any]] = ctx["evidence"]
    candidates = [i for i, s in enumerate(sentences) if extract(s["text"])]
    if not candidates:
        return None
    i = rng.choice(candidates)
    cited = set(sentences[i]["evidence_ids"])
    claims = extract(sentences[i]["text"])

    def supports_nothing(ev_id: str) -> bool:
        item_facts = facts(dict(evidence[ev_id]))
        return not any(check_claim(c, item_facts).passed for c in claims)

    pool = [k for k in sorted(evidence) if k not in cited and supports_nothing(k)]
    if not pool:
        return None
    new = rng.choice(pool)
    sentences[i]["evidence_ids"] = [new]
    return i, f"cites {new} instead of {', '.join(sorted(cited))}"


_INJECTORS: dict[
    str, Callable[[Sentences, random.Random, Mapping[str, Any]], tuple[int, str] | None]
] = {
    "amount_small": lambda s, r, _: _scale_amount(s, r, 1.03),
    "amount_large": lambda s, r, _: _scale_amount(s, r, 1.8),
    "wrong_date": _wrong_date,
    "swapped_account": _swapped_account,
    "invented_counterparty": _invented_counterparty,
    "wrong_typology": _wrong_typology,
    "wrong_count": _wrong_count,
    "uncited_sentence": _uncited,
    "irrelevant_citation": _irrelevant,
}


def inject(
    sentences: Sequence[Mapping[str, Any]],
    fault: str,
    seed: int,
    evidence: Mapping[str, Mapping[str, Any]],
    foreign_accounts: Sequence[str],
) -> Variant | None:
    """One variant with exactly one ``fault``, or None when the narrative offers no target."""
    copy_ = [dict(copy.deepcopy(dict(s))) for s in sentences]
    rng = random.Random(f"{seed}:{fault}")  # noqa: S311  # nosec B311 - reproducible, not crypto
    ctx = {"evidence": evidence, "foreign_accounts": foreign_accounts}
    planted = _INJECTORS[fault](copy_, rng, ctx)
    if planted is None:
        return None
    index, description = planted
    return Variant(fault, index, copy_, description)
