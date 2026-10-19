"""Capacity planning (PIVOT §7.4, M4.13–M4.17).

Decide which alerts to review on a day, given analysts on duty:

    maximize   Σ x_i · w_i                       (w = p: expected cases; w = p·v: expected USD)
    subject to Σ x_i · h_i ≤ analysts · minutes   (capacity)
               x_i = 1 for every alert the recall guarantee requires

``p_i`` is the calibrated probability, ``v_i`` the riskiest payment in USD (fixed conversion
table — an assumption), ``h_i`` the handling time (assumption: median × typology multiplier).
If the guaranteed alerts alone exceed capacity, the plan is infeasible and reports how many
analysts the guarantee needs.

The exact problem is a 0/1 knapsack solved with OR-Tools CP-SAT; a greedy ratio heuristic is
the baseline and its optimality gap is reported.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd

from verita.pipeline.config import CONFIG_DIR, load_yaml

FloatArray = npt.NDArray[np.float64]
GAIN_RESOLUTION = 1e9  # CP-SAT needs integers: the largest gain maps to this
OBJECTIVES = ("cases", "value")
MINUTE_RESOLUTION = 10  # the solver counts tenths of a minute
SOLVER_SECONDS = 5.0
EXACT_LIMIT = 5000  # recall simulation switches to a normal approximation above this
POOL_FACTOR = 5

# Approximate USD per unit (assumption, documented in configs/operations.yaml usage).
USD_PER_UNIT = {
    "US Dollar": 1.0,
    "Euro": 1.08,
    "UK Pound": 1.27,
    "Yuan": 0.14,
    "Rupee": 0.012,
    "Yen": 0.0068,
    "Canadian Dollar": 0.74,
    "Swiss Franc": 1.13,
    "Bitcoin": 60000.0,
    "Australian Dollar": 0.66,
    "Brazil Real": 0.18,
    "Mexican Peso": 0.055,
    "Ruble": 0.011,
    "Saudi Riyal": 0.27,
    "Shekel": 0.27,
}


@dataclass(frozen=True)
class Operations:
    median_minutes: float
    typology_multiplier: dict[str, float]
    productive_hours: float
    analyst_hourly_rate: float
    miss_cost_rate: float
    min_analysts: int
    max_analysts: int

    @classmethod
    def load(cls, path: Path | None = None) -> Operations:
        raw = load_yaml(path or CONFIG_DIR / "operations.yaml")
        handling = raw["handling_time_minutes"]
        return cls(
            median_minutes=float(handling["median"]),
            typology_multiplier={
                str(k): float(v) for k, v in handling["typology_multiplier"].items()
            },
            productive_hours=float(raw["analysts"]["productive_hours_per_day"]),
            analyst_hourly_rate=float(raw["costs"]["analyst_hourly_rate"]),
            miss_cost_rate=float(raw["costs"]["missed_laundering_cost_rate"]),
            min_analysts=int(raw["analysts"]["min"]),
            max_analysts=int(raw["analysts"]["max"]),
        )

    def minutes_for(self, typology: str) -> float:
        return self.median_minutes * self.typology_multiplier.get(
            typology, self.typology_multiplier.get("UNKNOWN", 1.0)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "median_minutes": self.median_minutes,
            "typology_multiplier": self.typology_multiplier,
            "productive_hours": self.productive_hours,
            "analyst_hourly_rate": self.analyst_hourly_rate,
            "miss_cost_rate": self.miss_cost_rate,
            "min_analysts": self.min_analysts,
            "max_analysts": self.max_analysts,
        }

    def with_overrides(self, **overrides: float | None) -> tuple[Operations, list[str]]:
        """What-if copy: replace the given assumptions (None leaves one unchanged)."""
        changed = {k: float(v) for k, v in overrides.items() if v is not None}
        unknown = set(changed) - {"median_minutes", "productive_hours", "analyst_hourly_rate"}
        if unknown:
            msg = f"cannot override {sorted(unknown)}"
            raise ValueError(msg)
        updated = replace(
            self,
            median_minutes=changed.get("median_minutes", self.median_minutes),
            productive_hours=changed.get("productive_hours", self.productive_hours),
            analyst_hourly_rate=changed.get("analyst_hourly_rate", self.analyst_hourly_rate),
        )
        return updated, sorted(changed)


def usd(amount: float, currency: str) -> float:
    return amount * USD_PER_UNIT.get(currency, 1.0)


def prepare(alerts: pd.DataFrame, ops: Operations) -> pd.DataFrame:
    """Add value (USD), handling minutes and expected value to a day's alerts."""
    out = alerts.copy()
    rate = out["top_currency"].map(USD_PER_UNIT).fillna(1.0).astype(float)
    out["value_usd"] = out["top_amount"].astype(float) * rate
    fallback = ops.typology_multiplier.get("UNKNOWN", 1.0)
    multiplier = out["typology_pred"].map(ops.typology_multiplier).fillna(fallback)
    out["minutes"] = ops.median_minutes * multiplier.astype(float)
    out["expected_value"] = out["calibrated_prob"] * out["value_usd"]
    return out


def _knapsack_cpsat(
    values: FloatArray, minutes: FloatArray, capacity: float, forced: npt.NDArray[np.bool_]
) -> npt.NDArray[np.bool_]:
    from ortools.sat.python import cp_model  # noqa: PLC0415 - heavy import

    model = cp_model.CpModel()
    x = [model.new_bool_var(f"x{i}") for i in range(len(values))]
    # Integer tenths of a minute: handling times are median × multiplier (e.g. 14.4 min), and
    # rounding each up to whole minutes would quietly shrink capacity below the greedy's.
    int_minutes = np.ceil(np.round(minutes * MINUTE_RESOLUTION, 6)).astype(int)
    budget = int(np.floor(capacity * MINUTE_RESOLUTION + 1e-6))
    model.add(sum(int(m) * v for m, v in zip(int_minutes, x, strict=True)) <= budget)
    for i in np.flatnonzero(forced):
        model.add(x[i] == 1)
    top = float(values.max()) if len(values) else 0.0
    gains = np.round(values * (GAIN_RESOLUTION / top if top > 0 else 1.0)).astype(np.int64)
    model.maximize(sum(int(g) * v for g, v in zip(gains, x, strict=True)))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = SOLVER_SECONDS
    solver.parameters.num_workers = 4
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return forced.copy()
    return np.array([bool(solver.value(v)) for v in x])


def _greedy(
    values: FloatArray, minutes: FloatArray, capacity: float, forced: npt.NDArray[np.bool_]
) -> npt.NDArray[np.bool_]:
    chosen = forced.copy()
    used = float(minutes[forced].sum())
    order = np.argsort(-(values / np.maximum(minutes, 1e-9)))
    for i in order:
        if not chosen[i] and used + minutes[i] <= capacity:
            chosen[i] = True
            used += minutes[i]
    return chosen


def expected_recall_interval(
    probs: FloatArray,
    reviewed: npt.NDArray[np.bool_],
    outside_expected: float = 0.0,
    draws: int = 2000,
    seed: int = 0,
) -> dict[str, float]:
    """Recall under the calibrated model, with a 95% simulation interval.

    Labels are Bernoulli(p). ``outside_expected`` is the expected number of positives that are
    not in the queue at all (below the alert floor): they can never be caught, so they count
    against recall. Caught and missed counts are Poisson-binomial; above ``EXACT_LIMIT`` alerts
    each is drawn from its normal approximation (mean Σp, variance Σp(1-p)) to keep memory flat.
    """
    total = float(probs.sum()) + outside_expected
    if len(probs) == 0 or total <= 0:
        return {"value": 1.0, "low": 1.0, "high": 1.0}
    point = float(probs[reviewed].sum()) / total
    rng = np.random.default_rng(seed)

    def draw(p: FloatArray) -> FloatArray:
        if len(p) <= EXACT_LIMIT:
            return np.asarray((rng.random((draws, len(p))) < p).sum(axis=1), dtype=float)
        mean, var = float(p.sum()), float((p * (1 - p)).sum())
        return np.clip(rng.normal(mean, math.sqrt(var), draws), 0, None)

    caught = draw(probs[reviewed])
    missed = draw(probs[~reviewed]) + rng.poisson(outside_expected, draws)
    positives = caught + missed
    recall = np.where(positives > 0, caught / np.maximum(positives, 1e-9), 1.0)
    low, high = np.quantile(recall, [0.025, 0.975])
    return {
        "value": round(point, 6),
        "low": round(min(float(low), point), 6),
        "high": round(max(float(high), point), 6),
    }


def candidate_pool(
    values: FloatArray, minutes: FloatArray, capacity: float, forced: npt.NDArray[np.bool_]
) -> npt.NDArray[np.bool_]:
    """Alerts handed to the exact solver: the forced ones plus the best by value per minute.

    At most capacity / min(minutes) alerts fit, so the pool keeps ``POOL_FACTOR`` times that many
    of the densest — a large day (10⁵ alerts) becomes a model CP-SAT solves in well under a
    second. Items outside the pool are still available to the greedy baseline, and the plan
    keeps whichever result is better, so restricting the pool can never make a plan worse.
    """
    if len(values) == 0:
        return forced.copy()
    fits = math.ceil(capacity / max(float(minutes.min()), 1e-9))
    size = POOL_FACTOR * fits
    pool = forced.copy()
    if size >= len(values):
        pool[:] = True
        return pool
    density = values / np.maximum(minutes, 1e-9)
    pool[np.argpartition(-density, size)[:size]] = True
    return pool


def plan_day(
    alerts: pd.DataFrame,
    analysts: int,
    threshold_mask: npt.NDArray[np.bool_],
    ops: Operations,
    solve_exact: bool = True,
    outside_expected: float = 0.0,
    objective: str = "cases",
) -> dict[str, Any]:
    """Plan one day. ``threshold_mask`` marks alerts the recall guarantee requires.

    ``objective`` is what the spare capacity maximises: ``cases`` (expected laundering alerts
    caught, Σp — the quantity recall is measured in) or ``value`` (expected USD caught, Σp·v,
    which a handful of very large payments can dominate). ``outside_expected`` is the expected
    number of positives below the alert floor (see :func:`expected_recall_interval`).
    """
    if objective not in OBJECTIVES:
        msg = f"objective must be one of {OBJECTIVES}"
        raise ValueError(msg)
    capacity = analysts * ops.productive_hours * 60
    probs = alerts["calibrated_prob"].to_numpy(dtype=float)
    values = alerts["expected_value"].to_numpy(dtype=float)
    weights = probs if objective == "cases" else values
    minutes = alerts["minutes"].to_numpy(dtype=float)
    forced = np.asarray(threshold_mask, dtype=bool)
    guarantee_minutes = float(minutes[forced].sum())
    feasible = guarantee_minutes <= capacity
    needed = (
        max(1, math.ceil(guarantee_minutes / (ops.productive_hours * 60)))
        if guarantee_minutes
        else 1
    )
    must = forced if feasible else np.zeros(len(forced), dtype=bool)
    greedy = _greedy(weights, minutes, capacity, must)
    if solve_exact:
        pool = candidate_pool(weights, minutes, capacity, must)
        chosen = np.zeros(len(weights), dtype=bool)
        chosen[pool] = _knapsack_cpsat(weights[pool], minutes[pool], capacity, must[pool])
    else:
        chosen = greedy
    solver = "cp-sat" if solve_exact else "greedy"
    if float(weights[chosen].sum()) < float(weights[greedy].sum()):
        chosen = greedy  # never return worse than the heuristic (time-limited solver)
        solver = "greedy (cp-sat hit its time limit)"
    best = float(weights[chosen].sum())
    baseline = float(weights[greedy].sum())
    review_minutes = float(minutes[chosen].sum())
    value_caught = float(values[chosen].sum())
    value_missed = float(values[~chosen].sum())
    value_total = value_caught + value_missed
    return {
        "analysts": analysts,
        "objective": objective,
        "capacity_minutes": round(capacity, 1),
        "alerts": len(alerts),
        "reviewed": int(chosen.sum()),
        "review_minutes": round(review_minutes, 1),
        "guarantee": {
            "required_alerts": int(forced.sum()),
            "required_minutes": round(guarantee_minutes, 1),
            "feasible": feasible,
            "analysts_needed": needed,
        },
        "expected_recall": expected_recall_interval(probs, chosen, outside_expected),
        "expected_cases_caught": round(float(probs[chosen].sum()), 3),
        "expected_cases_total": round(float(probs.sum()) + outside_expected, 3),
        "expected_value_caught_usd": round(value_caught, 2),
        "expected_missed_value_usd": round(value_missed, 2),
        "value_recall": round(value_caught / value_total, 6) if value_total > 0 else 1.0,
        "review_cost_usd": round(review_minutes / 60 * ops.analyst_hourly_rate, 2),
        "expected_miss_cost_usd": round(value_missed * ops.miss_cost_rate, 2),
        "objective_value": round(best, 6),
        "greedy_objective_value": round(baseline, 6),
        "solver": solver,
        "optimality_gap": round((best - baseline) / best, 6) if best > 0 else 0.0,
        "selected": chosen,
    }


def frontier(
    alerts: pd.DataFrame,
    threshold_mask: npt.NDArray[np.bool_],
    ops: Operations,
    exact: bool = True,
    outside_expected: float = 0.0,
    objective: str = "cases",
    labels: npt.NDArray[np.bool_] | None = None,
    outside_positives: int = 0,
) -> list[dict[str, Any]]:
    """Plans for every staffing level.

    With ``labels`` (replay only — never available for a live day) each point also records the
    recall the plan actually achieved, counting ``outside_positives`` below the floor as missed:
    the check that the calibrated "expected recall" is honest.
    """
    rows = []
    positives = int(labels.sum()) + outside_positives if labels is not None else 0
    for n in range(ops.min_analysts, ops.max_analysts + 1):
        plan = plan_day(alerts, n, threshold_mask, ops, exact, outside_expected, objective)
        selected = plan.pop("selected")
        if labels is not None:
            caught = int((labels & selected).sum())
            plan["realised"] = {
                "positives": positives,
                "caught": caught,
                "recall": round(caught / positives, 6) if positives else None,
            }
        rows.append(plan)
    return rows
