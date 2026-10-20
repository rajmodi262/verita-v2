"""Typed claim extraction (PIVOT §8.3 step 2).

A narrative sentence makes checkable claims: money amounts (with a currency), counts, dates,
durations, account numbers, bank IDs, typology names and percentages. Each parser turns text
into normalised :class:`Claim` objects — "$48.5k" becomes 48,500 US Dollar with the precision
the writer used, so the checker can be rounding-aware ("$48.5k" matches 48,512.33 but not
49,000).

The same parsers read *evidence* text (reason codes are sentences too), so a fact is always
compared in the same normal form as the claim against it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from itertools import pairwise
from typing import Literal

Kind = Literal[
    "amount", "count", "date", "date_range", "duration", "account", "bank", "typology", "percent"
]

# Data-contract currency names → the ways a writer may spell them.
CURRENCIES: dict[str, tuple[str, ...]] = {
    "US Dollar": ("US Dollar", "US Dollars", "USD", "US$", "$", "dollars"),
    "Euro": ("Euro", "Euros", "EUR", "€"),
    "UK Pound": ("UK Pound", "UK Pounds", "GBP", "£", "pounds sterling"),
    "Yuan": ("Yuan", "CNY", "RMB"),
    "Rupee": ("Rupee", "Rupees", "INR", "₹"),
    "Yen": ("Yen", "JPY", "¥"),
    "Canadian Dollar": ("Canadian Dollar", "Canadian Dollars", "CAD", "C$"),
    "Swiss Franc": ("Swiss Franc", "Swiss Francs", "CHF"),
    "Bitcoin": ("Bitcoin", "BTC", "₿"),
    "Australian Dollar": ("Australian Dollar", "Australian Dollars", "AUD", "A$"),
    "Brazil Real": ("Brazil Real", "Brazilian Real", "BRL", "R$"),
    "Mexican Peso": ("Mexican Peso", "Mexican Pesos", "MXN", "MX$"),
    "Ruble": ("Ruble", "Rubles", "RUB", "₽"),
    "Saudi Riyal": ("Saudi Riyal", "Saudi Riyals", "SAR"),
    "Shekel": ("Shekel", "Shekels", "ILS", "₪"),
}
_ALIAS = {a.lower(): name for name, aliases in CURRENCIES.items() for a in aliases}
_SYMBOLS = sorted((a for a in _ALIAS if not a.isalpha()), key=len, reverse=True)
_WORDS = sorted((a for a in _ALIAS if a.replace(" ", "").isalpha()), key=len, reverse=True)

TYPOLOGIES = (
    "FAN-OUT",
    "FAN-IN",
    "GATHER-SCATTER",
    "SCATTER-GATHER",
    "CYCLE",
    "RANDOM",
    "BIPARTITE",
    "STACK",
)
# Hyphens, spaces or nothing between the parts ("fan-out", "fan out", "fanout").
_TYPOLOGY_RE = re.compile(
    r"\b("
    + "|".join(t.replace("-", r"[\s-]?") for t in sorted(TYPOLOGIES, key=len, reverse=True))
    + r")\b",
    re.IGNORECASE,
)

_NUMBER = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
_SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "bn": 1e9, "billion": 1e9}
_SCALE_RE = r"(?:\s?(?:k|thousand|mn|m|million|bn|billion)\b)?"

_AMOUNT_SYMBOL = re.compile(
    r"(?P<cur>"
    + "|".join(re.escape(s) for s in _SYMBOLS)
    + r")\s?(?P<num>"
    + _NUMBER
    + r")(?P<scale>"
    + _SCALE_RE
    + r")",
    re.IGNORECASE,
)
_AMOUNT_WORD = re.compile(
    r"(?<![\w.])(?P<num>"
    + _NUMBER
    + r")(?P<scale>"
    + _SCALE_RE
    + r")\s(?P<cur>"
    + "|".join(re.escape(w) for w in _WORDS)
    + r")\b",
    re.IGNORECASE,
)
_AMOUNT_CODE_FIRST = re.compile(
    r"\b(?P<cur>USD|EUR|GBP|CNY|INR|JPY|CAD|CHF|BTC|AUD|BRL|MXN|RUB|SAR|ILS)\s(?P<num>"
    + _NUMBER
    + r")(?P<scale>"
    + _SCALE_RE
    + r")",
)

COUNT_NOUNS = (
    "payments",
    "payment",
    "transactions",
    "transaction",
    "transfers",
    "transfer",
    "accounts",
    "account",
    "counterparties",
    "counterparty",
    "payees",
    "payee",
    "payers",
    "payer",
    "banks",
    "bank",
    "alerts",
    "alert",
    "hops",
    "hop",
)
_COUNT_RE = re.compile(
    r"(?<![\w.,$€£¥₹₿₽₪])(?P<num>\d{1,3}(?:,\d{3})+|\d+)(?!\.\d)\s(?:(?:different|distinct|"
    r"separate|unique|incoming|outgoing|linked|related|flagged|other|more)\s)*(?P<noun>"
    + "|".join(COUNT_NOUNS)
    + r")\b",
    re.IGNORECASE,
)
_DURATION_RE = re.compile(
    r"(?<![\w.])(?P<num>\d+(?:\.\d+)?)\s?(?P<unit>minutes?|mins?|hours?|hrs?|h|days?)\b",
    re.IGNORECASE,
)
_UNIT_MINUTES = {"m": 1.0, "h": 60.0, "d": 1440.0}

_MONTHS = {
    m: i + 1
    for i, m in enumerate(
        (
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        )
    )
}
_MONTH_RE = r"(?P<month>" + "|".join(m.capitalize() for m in _MONTHS) + r"|Sept?|[A-Z][a-z]{2})"
_ISO_DATE = re.compile(r"\b(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})(?:[T ]\d{2}:\d{2}(?::\d{2})?)?")
_DMY = re.compile(r"\b(?P<d>\d{1,2})\s" + _MONTH_RE + r"\.?\s(?P<y>\d{4})\b")
_MDY = re.compile(r"\b" + _MONTH_RE + r"\.?\s(?P<d>\d{1,2}),?\s(?P<y>\d{4})\b")

# IBM AML account numbers: 9 upper-case hex characters, always with a digit (e.g. 8000EBD30).
_ACCOUNT_RE = re.compile(r"\b(?:(?P<bank>\d{1,6}):)?(?P<acct>(?=[0-9A-F]*\d)[0-9A-F]{9})\b")
_BANK_RE = re.compile(
    r"\bbanks?\s(?:ID\s|#|no\.?\s)?(?P<ids>\d{1,6}(?:(?:,\s?|\s(?:and|or)\s)\d{1,6})*)",
    re.IGNORECASE,
)
_PERCENT_RE = re.compile(r"(?<![\w.])(?P<num>\d+(?:\.\d+)?)\s?%")


@dataclass(frozen=True)
class Claim:
    kind: Kind
    value: str | float  # normalised: floats for numbers, canonical strings otherwise
    text: str  # what the sentence said
    unit: str = ""  # currency for amounts, noun for counts
    resolution: float = 0.0  # half the smallest step the writer's precision allows
    span: tuple[int, int] = (0, 0)

    def describe(self) -> str:
        unit = f" {self.unit}" if self.unit else ""
        return f"{self.kind} {self.value}{unit}"


def _num(text: str) -> tuple[float, float]:
    """Value and half-step of the last written digit ("48.5" → 48.5, 0.05)."""
    clean = text.replace(",", "")
    decimals = len(clean.split(".")[1]) if "." in clean else 0
    return float(clean), 0.5 * 10.0**-decimals


def _scale(raw: str) -> float:
    key = raw.strip().lower()
    return _SCALE.get(key, 1.0)


def currency_name(raw: str) -> str | None:
    return _ALIAS.get(raw.strip().lower())


def _amounts(text: str) -> list[Claim]:
    out: list[Claim] = []
    taken: list[tuple[int, int]] = []
    for regex in (_AMOUNT_CODE_FIRST, _AMOUNT_SYMBOL, _AMOUNT_WORD):
        for m in regex.finditer(text):
            if any(m.start() < e and s < m.end() for s, e in taken):
                continue
            cur = currency_name(m.group("cur"))
            if cur is None:
                continue
            value, half = _num(m.group("num"))
            scale = _scale(m.group("scale"))
            taken.append(m.span())
            out.append(Claim("amount", value * scale, m.group(0), cur, half * scale, m.span()))
    return out


def _counts(text: str, exclude: list[tuple[int, int]]) -> list[Claim]:
    out = []
    for m in _COUNT_RE.finditer(text):
        if any(m.start() < e and s < m.end() for s, e in exclude):
            continue
        noun = m.group("noun").lower().rstrip("s") or m.group("noun").lower()
        noun = "counterparty" if noun.startswith("counterpart") else noun
        out.append(
            Claim("count", float(m.group("num").replace(",", "")), m.group(0), noun, 0.0, m.span())
        )
    return out


def _durations(text: str) -> list[Claim]:
    out = []
    for m in _DURATION_RE.finditer(text):
        value, half = _num(m.group("num"))
        per = _UNIT_MINUTES[m.group("unit")[0].lower()]
        out.append(Claim("duration", value * per, m.group(0), "minutes", half * per, m.span()))
    return out


def _month(raw: str) -> int | None:
    key = raw.lower()
    for name, number in _MONTHS.items():
        if name.startswith(key[:3]):
            return number
    return None


def _dates(text: str) -> list[Claim]:
    out = []
    for regex in (_ISO_DATE, _DMY, _MDY):
        for m in regex.finditer(text):
            month = int(m.group("m")) if "m" in m.groupdict() and m.group("m") else None
            if month is None:
                month = _month(m.group("month"))
            if month is None:
                continue
            try:
                day = date(int(m.group("y")), month, int(m.group("d")))
            except ValueError:
                continue
            out.append(Claim("date", day.isoformat(), m.group(0), "", 0.0, m.span()))
    return out


_RANGE_OPEN = re.compile(r"(?:between|from)\s+$", re.IGNORECASE)
_RANGE_JOIN = re.compile(r"^\s+(?:and|to|through|until)\s+$", re.IGNORECASE)


def _date_ranges(text: str, dates: list[Claim]) -> list[Claim]:
    """ "between 2022-09-01 and 2022-09-08" states where a period *starts and ends*, which is
    stronger than two dates that both occur in it."""
    ordered = sorted(dates, key=lambda c: c.span)
    out = []
    for first, second in pairwise(ordered):
        if _RANGE_OPEN.search(text[: first.span[0]]) and _RANGE_JOIN.match(
            text[first.span[1] : second.span[0]]
        ):
            span = (first.span[0], second.span[1])
            value = f"{first.value}..{second.value}"
            out.append(Claim("date_range", value, text[span[0] : span[1]], "", 0.0, span))
    return out


def _accounts(text: str) -> list[Claim]:
    return [
        Claim("account", m.group("acct"), m.group(0), "", 0.0, m.span())
        for m in _ACCOUNT_RE.finditer(text)
    ]


def _banks(text: str) -> list[Claim]:
    out = []
    for m in _BANK_RE.finditer(text):
        for raw in re.findall(r"\d{1,6}", m.group("ids")):
            out.append(Claim("bank", str(int(raw)), raw, "", 0.0, m.span()))
    for m in _ACCOUNT_RE.finditer(text):
        if m.group("bank"):
            out.append(Claim("bank", str(int(m.group("bank"))), m.group("bank"), "", 0.0, m.span()))
    return out


def _typologies(text: str) -> list[Claim]:
    out = []
    for m in _TYPOLOGY_RE.finditer(text):
        canonical = re.sub(r"[\s-]?", "", m.group(1).upper())
        for t in TYPOLOGIES:
            if t.replace("-", "") == canonical:
                out.append(Claim("typology", t, m.group(0), "", 0.0, m.span()))
    return out


def _percents(text: str) -> list[Claim]:
    out = []
    for m in _PERCENT_RE.finditer(text):
        value, half = _num(m.group("num"))
        out.append(Claim("percent", value, m.group(0), "", half, m.span()))
    return out


def extract(text: str) -> list[Claim]:
    """Every checkable claim in ``text``, left to right."""
    amounts = _amounts(text)
    dates = _dates(text)
    durations = _durations(text)
    percents = _percents(text)
    numeric_spans = [c.span for c in (*amounts, *dates, *durations, *percents)]
    claims = [
        *amounts,
        *_counts(text, numeric_spans),
        *dates,
        *_date_ranges(text, dates),
        *durations,
        *_accounts(text),
        *_banks(text),
        *_typologies(text),
        *percents,
    ]
    return sorted(claims, key=lambda c: c.span)


def day_of(ts: str | datetime | date) -> str:
    if isinstance(ts, datetime):
        return ts.date().isoformat()
    if isinstance(ts, date):
        return ts.isoformat()
    return ts[:10]
