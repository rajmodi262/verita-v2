"""Deterministic fixture in the exact IBM AML file format (PIVOT §4.1, TRACKER M1.01).

Writes a ``*_Trans.csv`` and ``*_Patterns.txt`` pair that the real pipeline ingests unchanged, so
every stage is exercised end to end before (and independently of) the real dataset. Background
traffic is unlabeled; each laundering attempt is injected with its typology and also listed in
the patterns file, exactly as the IBM generator does.

It also plants the awkward cases real data has: an exact duplicate row, self-transfers
(reinvestment), and cross-currency payments.
"""

from __future__ import annotations

import csv
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import pairwise
from pathlib import Path

import numpy as np

TIMESTAMP_FORMAT = "%Y/%m/%d %H:%M"
HEADER = [
    "Timestamp",
    "From Bank",
    "Account",
    "To Bank",
    "Account",
    "Amount Received",
    "Receiving Currency",
    "Amount Paid",
    "Payment Currency",
    "Payment Format",
    "Is Laundering",
]
CURRENCY_WEIGHTS = {
    "US Dollar": 0.55,
    "Euro": 0.15,
    "UK Pound": 0.06,
    "Yuan": 0.05,
    "Rupee": 0.05,
    "Yen": 0.04,
    "Canadian Dollar": 0.03,
    "Swiss Franc": 0.03,
    "Bitcoin": 0.04,
}
USD_RATE = {
    "US Dollar": 1.0,
    "Euro": 0.92,
    "UK Pound": 0.79,
    "Yuan": 7.2,
    "Rupee": 83.0,
    "Yen": 145.0,
    "Canadian Dollar": 1.36,
    "Swiss Franc": 0.88,
    "Bitcoin": 0.00004,
}
FORMAT_WEIGHTS = {
    "ACH": 0.30,
    "Cheque": 0.22,
    "Credit Card": 0.22,
    "Cash": 0.10,
    "Wire": 0.08,
    "Bitcoin": 0.04,
    "Reinvestment": 0.04,
}
TYPOLOGIES = (
    "FAN-OUT",
    "FAN-IN",
    "CYCLE",
    "SCATTER-GATHER",
    "GATHER-SCATTER",
    "BIPARTITE",
    "STACK",
    "RANDOM",
)

Row = tuple[datetime, str, str, str, str, float, str, float, str, str, int]
Account = tuple[str, str]
Hop = Callable[[Account, Account, float, datetime], datetime]
CROSS_CURRENCY_SHARE = 0.05


@dataclass
class FixtureSummary:
    transactions: int
    laundering_transactions: int
    patterns: int
    by_typology: dict[str, int] = field(default_factory=dict)
    duplicate_rows: int = 0
    self_transfers: int = 0
    span_days: int = 0


class _Generator:
    def __init__(self, seed: int, n_accounts: int, days: int, start: datetime) -> None:
        self.rng = np.random.default_rng(seed)
        self.start = start
        self.days = days
        banks = [f"{int(b):03d}" for b in self.rng.choice(np.arange(1, 4000), 60, replace=False)]
        self.accounts: list[Account] = []
        seen: set[str] = set()
        while len(self.accounts) < n_accounts:
            acct = f"{int(self.rng.integers(0x800000000, 0xFFFFFFFFF)):09X}"
            if acct in seen:
                continue
            seen.add(acct)
            self.accounts.append((str(self.rng.choice(banks)), acct))

    def _pick(self, weights: dict[str, float]) -> str:
        keys = list(weights)
        probs = np.array(list(weights.values()))
        return str(self.rng.choice(keys, p=probs / probs.sum()))

    def account(self) -> Account:
        return self.accounts[int(self.rng.integers(0, len(self.accounts)))]

    def _distinct(self, k: int) -> list[Account]:
        idx = self.rng.choice(len(self.accounts), size=k, replace=False)
        return [self.accounts[int(i)] for i in idx]

    def time(self, base: datetime | None = None, max_hours: float | None = None) -> datetime:
        if base is None:
            minutes = int(self.rng.integers(0, self.days * 24 * 60))
            return self.start + timedelta(minutes=minutes)
        hours = float(self.rng.uniform(0.1, max_hours or 6.0))
        return base + timedelta(minutes=round(hours * 60))

    def _amounts(self, usd: float, cross_currency: bool = False) -> tuple[float, str, float, str]:
        paid_ccy = self._pick(CURRENCY_WEIGHTS)
        recv_ccy = self._pick(CURRENCY_WEIGHTS) if cross_currency else paid_ccy
        paid = round(usd * USD_RATE[paid_ccy], 2) or 0.01
        recv = round(usd * USD_RATE[recv_ccy], 2) or 0.01
        return recv, recv_ccy, paid, paid_ccy

    def tx(
        self,
        ts: datetime,
        src: Account,
        dst: Account,
        usd: float,
        *,
        label: int,
        fmt: str | None = None,
        cross_currency: bool = False,
    ) -> Row:
        recv, recv_ccy, paid, paid_ccy = self._amounts(usd, cross_currency)
        return (
            ts,
            src[0],
            src[1],
            dst[0],
            dst[1],
            recv,
            recv_ccy,
            paid,
            paid_ccy,
            fmt or self._pick(FORMAT_WEIGHTS),
            label,
        )

    def background(self, n: int) -> list[Row]:
        rows: list[Row] = []
        for _ in range(n):
            src, dst = self.account(), self.account()
            usd = float(self.rng.lognormal(6.0, 1.6))
            rows.append(
                self.tx(
                    self.time(),
                    src,
                    dst,
                    usd,
                    label=0,
                    cross_currency=bool(self.rng.random() < CROSS_CURRENCY_SHARE),
                )
            )
        return rows

    # ── laundering typologies ────────────────────────────────────────────────
    # Each builder receives `hop(src, dst, amount, after) -> time of the new transaction`.
    def pattern(self, typology: str) -> tuple[str, list[Row]]:
        builders: dict[str, Callable[[str, Hop, datetime, float], str]] = {
            "FAN-OUT": self._fan,
            "FAN-IN": self._fan,
            "CYCLE": self._chain,
            "RANDOM": self._chain,
            "SCATTER-GATHER": self._scatter_gather,
            "GATHER-SCATTER": self._gather_scatter,
            "BIPARTITE": self._bipartite,
            "STACK": self._stack,
        }
        if typology not in builders:
            msg = f"unknown typology {typology}"
            raise ValueError(msg)
        fmt = self._pick({"ACH": 0.5, "Wire": 0.2, "Cheque": 0.2, "Bitcoin": 0.1})
        rows: list[Row] = []

        def hop(src: Account, dst: Account, amount: float, after: datetime) -> datetime:
            when = self.time(after, 8.0)
            rows.append(self.tx(when, src, dst, amount, label=1, fmt=fmt))
            return when

        start, usd = self.time(), float(self.rng.uniform(2_000, 40_000))
        description = builders[typology](typology, hop, start, usd)
        return description, rows

    def _fan(self, typology: str, hop: Hop, start: datetime, usd: float) -> str:
        k = int(self.rng.integers(3, 9))
        hub, *spokes = self._distinct(k + 1)
        for spoke in spokes:
            src, dst = (hub, spoke) if typology == "FAN-OUT" else (spoke, hub)
            hop(src, dst, usd / k, start)
        return f"Max {k}-degree {typology.title()}"

    def _chain(self, typology: str, hop: Hop, start: datetime, usd: float) -> str:
        n = int(self.rng.integers(3, 7))
        chain = self._distinct(n)
        path = [*chain, chain[0]] if typology == "CYCLE" else chain
        at, amount = start, usd
        for src, dst in pairwise(path):
            at = hop(src, dst, amount, at)
            amount *= float(self.rng.uniform(0.95, 0.99))
        return f"Max {n} hops"

    def _scatter_gather(self, typology: str, hop: Hop, start: datetime, usd: float) -> str:
        k = int(self.rng.integers(3, 7))
        a, b, *mids = self._distinct(k + 2)
        for mid in mids:
            at = hop(a, mid, usd / k, start)
            hop(mid, b, usd / k * 0.97, at)
        return f"Max {k}-degree {typology.title()}"

    def _gather_scatter(self, typology: str, hop: Hop, start: datetime, usd: float) -> str:
        k = int(self.rng.integers(3, 7))
        hub, extra, *mids = self._distinct(k + 2)
        ins, outs = mids[: k // 2 + 1], mids[k // 2 + 1 :] or [extra]
        arrived = start
        for src in ins:
            arrived = max(arrived, hop(src, hub, usd / len(ins), start))
        for dst in outs:
            hop(hub, dst, usd / len(outs) * 0.97, arrived)
        return f"Max {k}-degree {typology.title()}"

    def _bipartite(self, _typology: str, hop: Hop, start: datetime, usd: float) -> str:
        p, q = int(self.rng.integers(2, 4)), int(self.rng.integers(2, 4))
        accounts = self._distinct(p + q)
        for src in accounts[:p]:
            for dst in accounts[p:]:
                hop(src, dst, usd / (p * q), start)
        return f"{p} x {q} bipartite"

    def _stack(self, _typology: str, hop: Hop, start: datetime, usd: float) -> str:
        width = int(self.rng.integers(2, 4))
        layers = [self._distinct(width) for _ in range(3)]
        at = start
        for left, right in pairwise(layers):
            latest = at
            for src in left:
                for dst in right:
                    latest = max(latest, hop(src, dst, usd / (width * width), at))
            at = latest
        return f"Stack of 3 layers, width {width}"


def _fmt(row: Row) -> list[str]:
    ts, fb, fa, tb, ta, recv, recv_ccy, paid, paid_ccy, fmt, label = row
    return [
        ts.strftime(TIMESTAMP_FORMAT),
        fb,
        fa,
        tb,
        ta,
        f"{recv:.2f}",
        recv_ccy,
        f"{paid:.2f}",
        paid_ccy,
        fmt,
        str(label),
    ]


def generate_fixture(
    out_dir: Path,
    *,
    prefix: str = "FIXTURE",
    seed: int = 7,
    n_accounts: int = 1_500,
    n_background: int = 30_000,
    patterns_per_typology: int = 12,
    days: int = 16,
    start: datetime = datetime(2022, 9, 1),
) -> FixtureSummary:
    """Write ``<prefix>_Trans.csv`` and ``<prefix>_Patterns.txt`` into ``out_dir``."""
    gen = _Generator(seed, n_accounts, days, start)
    rows = gen.background(n_background)

    # Planted edge cases.
    self_acct = gen.account()
    self_rows = [
        gen.tx(gen.time(), self_acct, self_acct, 1_000.0, label=0, fmt="Reinvestment")
        for _ in range(5)
    ]
    rows.extend(self_rows)
    rows.append(rows[0])  # one exact duplicate

    blocks: list[tuple[str, str, list[Row]]] = []
    for typology in TYPOLOGIES:
        for _ in range(patterns_per_typology):
            description, pattern_rows = gen.pattern(typology)
            blocks.append((typology, description, pattern_rows))
            rows.extend(pattern_rows)

    rows.sort(key=lambda r: r[0])
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / f"{prefix}_Trans.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(HEADER)
        writer.writerows(_fmt(r) for r in rows)

    with (out_dir / f"{prefix}_Patterns.txt").open("w", encoding="utf-8") as handle:
        for typology, description, pattern_rows in blocks:
            handle.write(f"BEGIN LAUNDERING ATTEMPT - {typology}:  {description}\n")
            for r in sorted(pattern_rows, key=lambda r: r[0]):
                handle.write(",".join(_fmt(r)) + "\n")
            handle.write(f"END LAUNDERING ATTEMPT - {typology}\n\n")

    counts = Counter(t for t, _, _ in blocks)
    return FixtureSummary(
        transactions=len(rows),
        laundering_transactions=sum(r[-1] for r in rows),
        patterns=len(blocks),
        by_typology=dict(counts),
        duplicate_rows=1,
        self_transfers=len(self_rows),
        span_days=days,
    )
