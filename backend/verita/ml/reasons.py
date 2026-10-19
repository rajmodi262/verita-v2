"""Plain-English reason codes for SHAP contributions (PIVOT §6.5, M2.21).

Each feature has a sentence template that states the fact in the data, not an opinion. The SHAP
sign then says whether that fact raised or lowered the score.
"""

from __future__ import annotations

from collections.abc import Callable

from verita.ml.features import ALL_FEATURES, CURRENCIES, PAYMENT_FORMATS

WINDOW_WORDS = {"1h": "hour", "24h": "24 hours", "7d": "7 days"}
FX_TOLERANCE = 1e-6


def _count(n: float, noun: str) -> str:
    k = round(n)
    return f"{k} {noun}{'' if k == 1 else 's'}"


def _minutes(m: float) -> str:
    if m < 0:
        return "never before"
    if m < 60:  # noqa: PLR2004
        return f"{round(m)} min earlier"
    if m < 48 * 60:
        return f"{m / 60:.1f} h earlier"
    return f"{m / 1440:.1f} days earlier"


def _code(values: list[str], v: float) -> str:
    i = round(v)
    return values[i] if 0 <= i < len(values) else "unknown"


Template = Callable[[float], str]
TEMPLATES: dict[str, Template] = {
    "log_amount_paid": lambda v: (
        f"Amount paid is about {pow(2.718281828, v) - 1:,.0f} in its currency"
    ),
    "log_amount_received": lambda v: f"Amount received is about {pow(2.718281828, v) - 1:,.0f}",
    "log_fx_ratio": lambda v: (
        "Paid and received amounts differ by currency conversion"
        if abs(v) > FX_TOLERANCE
        else "Paid and received amounts match"
    ),
    "cross_currency": lambda v: (
        "Payment converts between currencies" if v else "Payment stays in one currency"
    ),
    "currency_paid_code": lambda v: f"Paid in {_code(CURRENCIES, v)}",
    "currency_received_code": lambda v: f"Received in {_code(CURRENCIES, v)}",
    "payment_format_code": lambda v: f"Sent by {_code(PAYMENT_FORMATS, v)}",
    "hour": lambda v: f"Made at {round(v):02d}:00",
    "weekday": lambda v: (
        f"Made on a {['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][round(v) - 1]}"
    ),
    "round_amount": lambda v: "Amount is a round number" if v else "Amount is not round",
    "self_transfer": lambda v: "Account pays itself" if v else "Payment goes to another account",
    "cross_bank": lambda v: "Payment crosses banks" if v else "Payment stays within one bank",
    "cycle_found": lambda v: (
        "Payment closes a loop that returns money to where it started"
        if v
        else "Payment does not close a loop"
    ),
    "cycle_edges": lambda v: f"Loop length is {_count(v, 'transfer')}" if v else "No loop",
}


def _activity(who: str, verb: str, noun: str, words: str) -> Template:
    def render(v: float) -> str:
        return f"{who} {verb} {_count(v, noun)} in the previous {words}"

    return render


def _recency(who: str, fact: str, never: str) -> Template:
    def render(v: float) -> str:
        return f"{who} {fact} {_minutes(v)}" if v >= 0 else f"{who} {never}"

    return render


for _side, _who in (("s", "Sender"), ("r", "Receiver")):
    for _w, _words in WINDOW_WORDS.items():
        TEMPLATES[f"{_side}_out_n_{_w}"] = _activity(_who, "made", "payment", _words)
        TEMPLATES[f"{_side}_in_n_{_w}"] = _activity(_who, "received", "payment", _words)
        TEMPLATES[f"{_side}_payees_{_w}"] = _activity(_who, "paid", "different account", _words)
        TEMPLATES[f"{_side}_payers_{_w}"] = _activity(
            _who, "was paid by", "different account", _words
        )
    TEMPLATES[f"{_side}_age_min"] = _recency(_who, "first appeared", "has no earlier activity")
    TEMPLATES[f"{_side}_since_last_in_min"] = _recency(
        _who, "last received money", "had not received money before"
    )
    TEMPLATES[f"{_side}_since_last_out_min"] = _recency(
        _who, "last sent money", "had not sent money before"
    )

missing = set(ALL_FEATURES) - set(TEMPLATES)
if missing:  # pragma: no cover - guarded by a test
    msg = f"reason templates missing for {sorted(missing)}"
    raise RuntimeError(msg)


def reason_text(feature: str, value: float, shap: float) -> str:
    fact = TEMPLATES[feature](value)
    effect = "raises" if shap > 0 else "lowers"
    return f"{fact} — {effect} the risk score"


def top_reasons(
    features: list[str], values: list[float], shaps: list[float], k: int = 5
) -> list[dict[str, float | str | int]]:
    """The k largest absolute contributions, as structured reasons."""
    order = sorted(range(len(features)), key=lambda i: -abs(shaps[i]))[:k]
    return [
        {
            "rank": rank + 1,
            "feature": features[i],
            "value": float(values[i]),
            "shap": float(shaps[i]),
            "text": reason_text(features[i], values[i], shaps[i]),
        }
        for rank, i in enumerate(order)
    ]
