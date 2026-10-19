"""Evaluation primitives with honest uncertainty (PIVOT §6.4).

Confidence intervals use a **block bootstrap over time**: transactions are grouped into
fixed-length time blocks and whole blocks are resampled, so correlated activity within a block
(one laundering attempt spans many rows) isn't treated as independent evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
from scipy import stats
from sklearn.metrics import average_precision_score, precision_recall_curve

FloatArray = npt.NDArray[np.float64]
BoolArray = npt.NDArray[np.bool_]
IntArray = npt.NDArray[np.int64]


@dataclass(frozen=True)
class Interval:
    value: float
    low: float
    high: float

    def to_dict(self) -> dict[str, float]:
        return {
            "value": round(self.value, 6),
            "low": round(self.low, 6),
            "high": round(self.high, 6),
        }


def f1_from_counts(tp: float, fp: float, fn: float) -> float:
    denom = 2 * tp + fp + fn
    return float(2 * tp / denom) if denom else 0.0


def confusion(y: BoolArray, pred: BoolArray) -> tuple[int, int, int]:
    tp = int(np.sum(pred & y))
    fp = int(np.sum(pred & ~y))
    fn = int(np.sum(~pred & y))
    return tp, fp, fn


def best_f1_threshold(y: BoolArray, scores: FloatArray) -> tuple[float, float]:
    """Threshold maximizing F1 (chosen on a validation split, then frozen)."""
    precision, recall, thresholds = precision_recall_curve(y, scores)
    if not len(thresholds):
        return 0.5, 0.0
    denom = precision + recall
    f1 = np.divide(2 * precision * recall, denom, out=np.zeros_like(denom), where=denom > 0)
    best = int(np.argmax(f1[:-1]))
    return float(thresholds[best]), float(f1[best])


def recall_at_precision(y: BoolArray, scores: FloatArray, min_precision: float) -> float:
    if not y.any():
        return 0.0
    precision, recall, _ = precision_recall_curve(y, scores)
    ok = precision >= min_precision
    return float(recall[ok].max()) if ok.any() else 0.0


def pr_auc(y: BoolArray, scores: FloatArray) -> float:
    return float(average_precision_score(y, scores)) if y.any() else 0.0


def _dense(blocks: IntArray) -> IntArray:
    """Renumber block ids 0..k-1 so a subset (e.g. the tail) has no empty blocks."""
    _, dense = np.unique(blocks, return_inverse=True)
    return dense.astype(np.int64)


def time_blocks(minutes: IntArray, block_minutes: int) -> IntArray:
    """Block index per row (dense, starting at 0)."""
    raw = (minutes - minutes.min()) // block_minutes
    _, dense = np.unique(raw, return_inverse=True)
    return dense.astype(np.int64)


def bootstrap_f1(
    y: BoolArray, pred: BoolArray, blocks: IntArray, n_boot: int = 1000, seed: int = 0
) -> Interval:
    """Block-bootstrap CI for F1 at a fixed decision rule (fast: resamples block counts)."""
    blocks = _dense(blocks)
    n_blocks = int(blocks.max()) + 1 if len(blocks) else 0
    tp = np.bincount(blocks, weights=(pred & y).astype(float), minlength=n_blocks)
    fp = np.bincount(blocks, weights=(pred & ~y).astype(float), minlength=n_blocks)
    fn = np.bincount(blocks, weights=(~pred & y).astype(float), minlength=n_blocks)
    point = f1_from_counts(tp.sum(), fp.sum(), fn.sum())
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, n_blocks, size=(n_boot, n_blocks))
    t, f, n = tp[draws].sum(1), fp[draws].sum(1), fn[draws].sum(1)
    denom = 2 * t + f + n
    samples = np.where(denom > 0, 2 * t / np.maximum(denom, 1e-12), 0.0)
    low, high = np.quantile(samples, [0.025, 0.975])
    return Interval(point, float(low), float(high))


def bootstrap_paired_delta_f1(
    y: BoolArray,
    pred_a: BoolArray,
    pred_b: BoolArray,
    blocks: IntArray,
    n_boot: int = 1000,
    seed: int = 0,
) -> Interval:
    """CI for F1(a) − F1(b) on the same resampled blocks (for ablations)."""
    blocks = _dense(blocks)
    n_blocks = int(blocks.max()) + 1 if len(blocks) else 0

    def counts(pred: BoolArray) -> tuple[FloatArray, FloatArray, FloatArray]:
        def count(mask: BoolArray) -> FloatArray:
            weights = mask.astype(np.float64)
            return np.bincount(blocks, weights=weights, minlength=n_blocks).astype(np.float64)

        return count(pred & y), count(pred & ~y), count(~pred & y)

    a, b = counts(pred_a), counts(pred_b)
    point = f1_from_counts(*(c.sum() for c in a)) - f1_from_counts(*(c.sum() for c in b))
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, n_blocks, size=(n_boot, n_blocks))

    def f1s(c: tuple[FloatArray, FloatArray, FloatArray]) -> FloatArray:
        t, f, n = (x[draws].sum(1) for x in c)
        denom = 2 * t + f + n
        return np.where(denom > 0, 2 * t / np.maximum(denom, 1e-12), 0.0)

    delta = f1s(a) - f1s(b)
    low, high = np.quantile(delta, [0.025, 0.975])
    return Interval(point, float(low), float(high))


def bootstrap_metric(
    y: BoolArray,
    scores: FloatArray,
    blocks: IntArray,
    metric: str,
    n_boot: int = 200,
    seed: int = 0,
    min_precision: float = 0.5,
) -> Interval:
    """Block-bootstrap CI for a score-based metric ('pr_auc' or 'recall_at_precision')."""
    blocks = _dense(blocks)

    def compute(yy: BoolArray, ss: FloatArray) -> float:
        if metric == "pr_auc":
            return pr_auc(yy, ss)
        return recall_at_precision(yy, ss, min_precision)

    point = compute(y, scores)
    order = np.argsort(blocks, kind="stable")
    sorted_blocks = blocks[order]
    bounds = np.searchsorted(sorted_blocks, np.arange(int(blocks.max()) + 2))
    rng = np.random.default_rng(seed)
    n_blocks = len(bounds) - 1
    samples = []
    for _ in range(n_boot):
        picked = rng.integers(0, n_blocks, size=n_blocks)
        idx = np.concatenate([order[bounds[b] : bounds[b + 1]] for b in picked])
        samples.append(compute(y[idx], scores[idx]))
    low, high = np.quantile(samples, [0.025, 0.975])
    return Interval(point, float(low), float(high))


def wilson(successes: int, total: int, z: float = 1.959964) -> Interval:
    """Wilson score interval for a proportion (used for per-typology recall)."""
    if total == 0:
        return Interval(0.0, 0.0, 0.0)
    p = successes / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = z * np.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    # Clamp so float rounding can never put the estimate outside its own interval.
    low = max(0.0, min(float(centre - half), p))
    high = min(1.0, max(float(centre + half), p))
    return Interval(p, low, high)


def summarize_binary(
    y: BoolArray, scores: FloatArray, threshold: float, blocks: IntArray, n_boot: int, seed: int = 0
) -> dict[str, Any]:
    pred = scores >= threshold
    tp, fp, fn = confusion(y, pred)
    return {
        "rows": len(y),
        "positives": int(y.sum()),
        "threshold": round(threshold, 6),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(tp / (tp + fp), 6) if tp + fp else 0.0,
        "recall": round(tp / (tp + fn), 6) if tp + fn else 0.0,
        "f1": bootstrap_f1(y, pred, blocks, n_boot, seed).to_dict(),
        "pr_auc": bootstrap_metric(
            y, scores, blocks, "pr_auc", max(50, n_boot // 5), seed
        ).to_dict(),
        "recall_at_precision_0_5": bootstrap_metric(
            y, scores, blocks, "recall_at_precision", max(50, n_boot // 5), seed
        ).to_dict(),
        "base_rate": round(float(y.mean()), 6) if len(y) else 0.0,
    }


def ks_two_sample(a: FloatArray, b: FloatArray) -> float:
    return float(stats.ks_2samp(a, b).pvalue)
