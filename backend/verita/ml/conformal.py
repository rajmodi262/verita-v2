"""Calibration and the recall guarantee (PIVOT §7.1–7.2, M4.01–M4.09).

The unit is the **alert** (account-day), scored by its riskiest payment.

Calibration
    Isotonic regression fitted on the ``calib`` split maps model scores to probabilities.

Split-conformal recall guarantee
    Let s_1..s_n be the scores of the n calibration *positives*. With k = ⌊α(n+1)⌋ and the
    threshold t = s_(k) (the k-th smallest; −∞ if k = 0), a new positive exchangeable with the
    calibration positives satisfies P(score ≥ t) ≥ 1 − α. Reviewing every alert scoring ≥ t
    therefore catches at least a (1 − α) share of laundering alerts *in expectation*.

Mondrian variant
    One threshold per group, where the group is known at decision time (the predicted
    typology). Groups with fewer than ``MIN_GROUP`` calibration positives use the pooled one.

Adaptive Conformal Inference (Gibbs & Candès, 2021)
    Time series are not exchangeable, so the static guarantee can drift. ACI updates the
    working miss-rate α_t online from realised misses: α_{t+1} = α_t + γ (α − err_t), using
    only labels revealed after a delay. Both are replayed hour by hour on the test split.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd
from sklearn.isotonic import IsotonicRegression

from verita.ml.evaluation import wilson

FloatArray = npt.NDArray[np.float64]
MIN_GROUP = 50
DEFAULT_ALPHA = 0.05  # the guarantee the planner opens with: 95% recall


# ── calibration ──────────────────────────────────────────────────────────────


def fit_isotonic(scores: FloatArray, labels: npt.NDArray[np.bool_]) -> IsotonicRegression:
    model = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip", increasing=True)
    model.fit(scores, labels.astype(float))
    return model


def expected_calibration_error(
    probs: FloatArray, labels: npt.NDArray[np.bool_], bins: int = 15
) -> float:
    """ECE with equal-mass bins (equal-width bins are almost empty at fraud base rates)."""
    if len(probs) == 0:
        return 0.0
    order = np.argsort(probs)
    chunks = np.array_split(order, bins)
    total = len(probs)
    err = 0.0
    for idx in chunks:
        if len(idx):
            err += len(idx) / total * abs(float(probs[idx].mean()) - float(labels[idx].mean()))
    return err


def reliability(
    probs: FloatArray, labels: npt.NDArray[np.bool_], bins: int = 15
) -> list[dict[str, float]]:
    order = np.argsort(probs)
    out = []
    for idx in np.array_split(order, bins):
        if len(idx):
            positives = int(labels[idx].sum())
            ci = wilson(positives, len(idx))
            out.append(
                {
                    "mean_predicted": round(float(probs[idx].mean()), 6),
                    "observed_rate": round(ci.value, 6),
                    "low": round(ci.low, 6),
                    "high": round(ci.high, 6),
                    "n": len(idx),
                }
            )
    return out


def brier(probs: FloatArray, labels: npt.NDArray[np.bool_]) -> float:
    return float(np.mean((probs - labels.astype(float)) ** 2)) if len(probs) else 0.0


# ── conformal thresholds ─────────────────────────────────────────────────────


def conformal_threshold(positive_scores: FloatArray, alpha: float) -> float:
    """Largest threshold with P(new positive ≥ t) ≥ 1 − α under exchangeability."""
    if not 0 < alpha < 1:
        msg = "alpha must be in (0, 1)"
        raise ValueError(msg)
    n = len(positive_scores)
    if n == 0:
        return -math.inf
    k = math.floor(alpha * (n + 1))
    if k < 1:
        return -math.inf  # too few positives to exclude any: review everything
    return float(np.sort(positive_scores)[k - 1])


@dataclass
class Thresholds:
    alpha: float
    pooled: float
    by_group: dict[str, float] = field(default_factory=dict)
    group_sizes: dict[str, int] = field(default_factory=dict)
    fallback_groups: list[str] = field(default_factory=list)

    def for_group(self, group: str) -> float:
        return self.by_group.get(group, self.pooled)

    def to_dict(self) -> dict[str, Any]:
        def safe(v: float) -> float | None:
            return None if math.isinf(v) else round(v, 8)

        return {
            "alpha": self.alpha,
            "pooled": safe(self.pooled),
            "by_group": {k: safe(v) for k, v in self.by_group.items()},
            "group_sizes": self.group_sizes,
            "fallback_groups": self.fallback_groups,
        }


def fit_thresholds(
    scores: FloatArray,
    labels: npt.NDArray[np.bool_],
    groups: npt.NDArray[Any],
    alpha: float,
    min_group: int = MIN_GROUP,
) -> Thresholds:
    pos = labels.astype(bool)
    pooled = conformal_threshold(scores[pos], alpha)
    out = Thresholds(alpha=alpha, pooled=pooled)
    for group in sorted({str(g) for g in groups}):
        mask = pos & (groups == group)
        n = int(mask.sum())
        out.group_sizes[group] = n
        if n >= min_group:
            out.by_group[group] = conformal_threshold(scores[mask], alpha)
        else:
            out.fallback_groups.append(group)
    return out


def apply_thresholds(
    scores: FloatArray, groups: npt.NDArray[Any], th: Thresholds, mode: str
) -> npt.NDArray[np.bool_]:
    if mode == "pooled":
        return np.asarray(scores >= th.pooled)
    cut = pd.Series(groups).astype(str).map(th.by_group).fillna(th.pooled).to_numpy(float)
    return np.asarray(scores >= cut)


# ── replay: static vs adaptive ───────────────────────────────────────────────


@dataclass
class ReplayResult:
    alpha: float
    mode: str
    by_day: list[dict[str, Any]]
    overall: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "alpha": self.alpha,
            "mode": self.mode,
            "by_day": self.by_day,
            "overall": self.overall,
        }


def _recall_summary(caught: int, total: int, reviewed: int, alerts: int) -> dict[str, Any]:
    ci = wilson(caught, total)
    return {
        "positives": total,
        "caught": caught,
        "recall": ci.to_dict(),
        "reviewed": reviewed,
        "alerts": alerts,
        "review_share": round(reviewed / alerts, 6) if alerts else 0.0,
    }


def replay_static(test: pd.DataFrame, th: Thresholds, mode: str) -> ReplayResult:
    """Fixed calibration thresholds applied to every test day."""
    review = apply_thresholds(test["score"].to_numpy(), test["group"].to_numpy(), th, mode)
    frame = test.assign(review=review)
    by_day = []
    for day, part in frame.groupby("day", sort=True):
        pos = part["label"].to_numpy(dtype=bool)
        by_day.append(
            {
                "day": str(day),
                **_recall_summary(
                    int((pos & part["review"].to_numpy()).sum()),
                    int(pos.sum()),
                    int(part["review"].sum()),
                    len(part),
                ),
            }
        )
    pos = frame["label"].to_numpy(dtype=bool)
    overall = _recall_summary(
        int((pos & review).sum()), int(pos.sum()), int(review.sum()), len(frame)
    )
    overall["target_recall"] = 1 - th.alpha
    return ReplayResult(th.alpha, f"static_{mode}", by_day, overall)


def replay_aci(
    calib_pos_scores: FloatArray,
    test: pd.DataFrame,
    alpha: float,
    gamma: float,
    label_delay_hours: int,
) -> ReplayResult:
    """Adaptive conformal: the pooled threshold's working α_t is nudged by revealed misses.

    Alerts arrive hour by hour (by the time of their riskiest payment). An alert's label is
    revealed ``label_delay_hours`` later; at that point, if it was a positive, err = 1 when it
    was not reviewed. α_t is clipped to [0.001, 0.5].
    """
    calib_sorted = np.sort(calib_pos_scores)
    n = len(calib_sorted)

    def threshold(a: float) -> float:
        k = math.floor(a * (n + 1))
        return -math.inf if k < 1 or n == 0 else float(calib_sorted[min(k, n) - 1])

    frame = test.sort_values("hour").reset_index(drop=True)
    alpha_t = alpha
    reviewed = np.zeros(len(frame), dtype=bool)
    hours = frame["hour"].to_numpy()
    revealed_at = hours + np.timedelta64(label_delay_hours, "h")
    pending = 0  # index into frame of the next label to reveal, ordered by revealed_at
    reveal_order = np.argsort(revealed_at, kind="stable")
    trace = []
    for hour in np.unique(hours):
        # reveal labels whose delay has elapsed and update alpha_t
        while pending < len(frame) and revealed_at[reveal_order[pending]] <= hour:
            i = reveal_order[pending]
            pending += 1
            if frame.at[i, "label"]:
                err = 0.0 if reviewed[i] else 1.0
                alpha_t = float(np.clip(alpha_t + gamma * (alpha - err), 0.001, 0.5))
        now = hours == hour
        reviewed[now] = frame.loc[now, "score"].to_numpy() >= threshold(alpha_t)
        trace.append({"hour": str(hour), "alpha_t": round(alpha_t, 6)})
    frame = frame.assign(review=reviewed)
    by_day = []
    for day, part in frame.groupby("day", sort=True):
        pos = part["label"].to_numpy(dtype=bool)
        by_day.append(
            {
                "day": str(day),
                **_recall_summary(
                    int((pos & part["review"].to_numpy()).sum()),
                    int(pos.sum()),
                    int(part["review"].sum()),
                    len(part),
                ),
            }
        )
    pos = frame["label"].to_numpy(dtype=bool)
    overall = _recall_summary(
        int((pos & reviewed).sum()), int(pos.sum()), int(reviewed.sum()), len(frame)
    )
    overall["target_recall"] = 1 - alpha
    overall["gamma"] = gamma
    overall["label_delay_hours"] = label_delay_hours
    overall["alpha_trace"] = trace
    return ReplayResult(alpha, "aci_pooled", by_day, overall)
