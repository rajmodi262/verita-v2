"""The rules incumbent: typology rules of the kind a bank's transaction monitoring runs.

Each rule targets one typology and has one or two thresholds. Thresholds are tuned on the
**train split only** — the way a monitoring team tunes rules on historical, investigated alerts —
so the hpo, calib and test splits are never seen by the incumbent:

1. every rule picks, from a fixed grid, the threshold with the best F1 *on its own* on train;
2. a fired rule contributes its train lift, ``log(precision / base rate)``, to the alert score
   (rules no better than the base rate get weight 0 and are reported as disabled);
3. the alert threshold on that score is the best-F1 point on train.

Amounts are converted to USD with the planner's fixed rates, so "just under the reporting
threshold" means the same thing in every currency. All inputs are point-in-time features (the
account windows end one minute before the payment), so no rule sees the future.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import product
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd

from verita.ml.evaluation import best_f1_threshold
from verita.ml.features import CURRENCIES
from verita.optimize.planner import USD_PER_UNIT

FloatArray = npt.NDArray[np.float64]
BoolArray = npt.NDArray[np.bool_]

REPORTING_THRESHOLD_USD = 10_000.0  # US CTR threshold; structuring sits just below it
_USD = np.array([USD_PER_UNIT[c] for c in CURRENCIES])


def amount_usd(frame: pd.DataFrame) -> FloatArray:
    amount = np.expm1(frame["log_amount_paid"].to_numpy(dtype=np.float64))
    codes = frame["currency_paid_code"].to_numpy()
    rate = np.where(codes >= 0, _USD[np.clip(codes, 0, len(_USD) - 1)], 1.0)
    return np.asarray(amount * rate, dtype=np.float64)


Predicate = Callable[[pd.DataFrame, FloatArray, tuple[float, ...]], BoolArray]


@dataclass(frozen=True)
class Rule:
    name: str
    typology: str
    description: str  # with {0}, {1} for the tuned parameters
    grid: Sequence[tuple[float, ...]]
    fires: Predicate


def _col(frame: pd.DataFrame, name: str) -> FloatArray:
    return frame[name].to_numpy(dtype=np.float64)


RULES: list[Rule] = [
    Rule(
        "structuring",
        "STRUCTURING",
        "USD amount in [{0:.0%} of 10k, 10k) and the payer already sent ≥ {1:.0f} payments in 24h",
        list(product((0.8, 0.85, 0.9, 0.95), (1, 2, 3, 5))),
        lambda f, usd, p: (
            (usd >= p[0] * REPORTING_THRESHOLD_USD)
            & (usd < REPORTING_THRESHOLD_USD)
            & (_col(f, "s_out_n_24h") >= p[1])
        ),
    ),
    Rule(
        "velocity",
        "VELOCITY",
        "payer sent ≥ {0:.0f} payments in the past hour",
        [(v,) for v in (3, 5, 8, 12, 20, 30, 50, 100, 200, 500)],
        lambda f, usd, p: _col(f, "s_out_n_1h") >= p[0],
    ),
    Rule(
        "fan_out",
        "FAN-OUT",
        "payer paid ≥ {0:.0f} distinct payees in 24h",
        [(v,) for v in (3, 5, 8, 12, 20, 30, 50, 100, 200)],
        lambda f, usd, p: _col(f, "s_payees_24h") >= p[0],
    ),
    Rule(
        "fan_in",
        "FAN-IN",
        "payee was paid by ≥ {0:.0f} distinct payers in 24h",
        [(v,) for v in (3, 5, 8, 12, 20, 30, 50, 100)],
        lambda f, usd, p: _col(f, "r_payers_24h") >= p[0],
    ),
    Rule(
        "rapid_pass_through",
        "PASS-THROUGH",
        "payer received money < {0:.0f} min ago and sends ≥ ${1:,.0f}",
        list(product((10, 30, 60, 180, 720, 1440, 4320), (0, 1_000, 5_000, 20_000, 100_000))),
        lambda f, usd, p: (
            (_col(f, "s_since_last_in_min") >= 0)
            & (_col(f, "s_since_last_in_min") < p[0])
            & (usd >= p[1])
        ),
    ),
    Rule(
        "round_tripping",
        "CYCLE",
        "the payment closes a time-ordered cycle of ≤ {0:.0f} payments back to the payer",
        [(e,) for e in (2, 3, 4, 5)],
        lambda f, usd, p: (_col(f, "cycle_found") > 0) & (_col(f, "cycle_edges") <= p[0]),
    ),
    Rule(
        "high_value",
        "HIGH-VALUE",
        "USD amount ≥ ${0:,.0f} (top of the training distribution)",
        [],  # filled from train quantiles in fit_rules
        lambda f, usd, p: usd >= p[0],
    ),
]


@dataclass
class FittedRule:
    rule: Rule
    params: tuple[float, ...]
    weight: float
    train_alerts: int
    train_caught: int

    def fires(self, frame: pd.DataFrame, usd: FloatArray) -> BoolArray:
        return self.rule.fires(frame, usd, self.params)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule.name,
            "typology": self.rule.typology,
            "description": self.rule.description.format(*self.params),
            "params": [float(p) for p in self.params],
            "weight": round(self.weight, 6),
            "enabled": self.weight > 0,
            "train_alerts": self.train_alerts,
            "train_laundering_caught": self.train_caught,
        }


@dataclass
class RuleSet:
    rules: list[FittedRule]
    threshold: float
    base_rate: float

    def score(self, frame: pd.DataFrame) -> FloatArray:
        usd = amount_usd(frame)
        total = np.zeros(len(frame))
        for r in self.rules:
            if r.weight > 0:
                total += r.weight * r.fires(frame, usd)
        return total

    def to_dict(self) -> dict[str, Any]:
        return {
            "tuned_on": "train",
            "threshold": round(self.threshold, 6),
            "train_base_rate": round(self.base_rate, 8),
            "rules": [r.to_dict() for r in self.rules],
        }


def _f1(fired: BoolArray, y: BoolArray) -> float:
    tp = int((fired & y).sum())
    denom = int(fired.sum()) + int(y.sum())
    return 2 * tp / denom if denom else 0.0


def fit_rules(train: pd.DataFrame) -> RuleSet:
    """Tune every rule and the alert threshold on ``train`` alone."""
    y = train["is_laundering"].to_numpy(dtype=bool)
    base = float(y.mean()) if len(y) else 0.0
    usd = amount_usd(train)
    fitted = []
    for rule in RULES:
        grid = rule.grid or [(float(np.quantile(usd, q)),) for q in (0.99, 0.995, 0.999)]
        best = max(grid, key=lambda p: _f1(rule.fires(train, usd, p), y))
        fired = rule.fires(train, usd, best)
        alerts, caught = int(fired.sum()), int((fired & y).sum())
        precision = caught / alerts if alerts else 0.0
        weight = float(np.log(precision / base)) if precision > base > 0 else 0.0
        fitted.append(FittedRule(rule, tuple(best), weight, alerts, caught))
    rs = RuleSet(fitted, threshold=0.0, base_rate=base)
    scores = rs.score(train)
    smallest = min((r.weight for r in fitted if r.weight > 0), default=1.0)
    rs.threshold = max(smallest, best_f1_threshold(y, scores)[0])  # at least one rule must fire
    return rs


def per_rule_hits(rs: RuleSet, frame: pd.DataFrame) -> list[dict[str, Any]]:
    """How often each rule fires on ``frame`` and how much laundering it touches (evaluation)."""
    y = frame["is_laundering"].to_numpy(dtype=bool)
    usd = amount_usd(frame)
    out = []
    for r in rs.rules:
        fired = r.fires(frame, usd)
        out.append(
            {"rule": r.rule.name, "alerts": int(fired.sum()), "laundering": int((fired & y).sum())}
        )
    return out
