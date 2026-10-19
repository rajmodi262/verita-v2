import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from verita.ml.evaluation import (
    best_f1_threshold,
    bootstrap_f1,
    bootstrap_metric,
    bootstrap_paired_delta_f1,
    f1_from_counts,
    pr_auc,
    recall_at_precision,
    summarize_binary,
    time_blocks,
    wilson,
)


def test_f1_from_counts():
    assert f1_from_counts(0, 0, 0) == 0.0
    assert f1_from_counts(5, 5, 0) == pytest.approx(2 / 3)


def test_best_threshold_separates_perfectly():
    y = np.array([0, 0, 1, 1], dtype=bool)
    s = np.array([0.1, 0.2, 0.8, 0.9])
    threshold, f1 = best_f1_threshold(y, s)
    assert f1 == 1.0 and 0.2 < threshold <= 0.8


def test_best_threshold_without_positives():
    _, f1 = best_f1_threshold(np.zeros(3, dtype=bool), np.array([0.1, 0.2, 0.3]))
    assert f1 == 0.0


def test_recall_at_precision():
    y = np.array([1, 0, 1, 0, 0], dtype=bool)
    s = np.array([0.9, 0.8, 0.7, 0.2, 0.1])
    assert recall_at_precision(y, s, 0.6) == 1.0  # 2 of 3 at the 0.7 cut
    assert recall_at_precision(y, s, 1.0) == 0.5
    assert recall_at_precision(np.zeros(2, dtype=bool), s[:2], 0.5) == 0.0
    assert pr_auc(np.zeros(2, dtype=bool), s[:2]) == 0.0


def test_time_blocks_are_dense():
    blocks = time_blocks(np.array([0, 10, 800, 2000, 2001]), 360)
    assert blocks.tolist() == [0, 0, 1, 2, 2]


@given(st.integers(0, 50), st.integers(1, 100))
def test_wilson_contains_the_estimate(successes, total):
    successes = min(successes, total)
    ci = wilson(successes, total)
    assert 0 <= ci.low <= ci.value <= ci.high <= 1


def test_wilson_empty():
    assert wilson(0, 0).to_dict() == {"value": 0.0, "low": 0.0, "high": 0.0}


def _synthetic(n=4000, seed=0):
    rng = np.random.default_rng(seed)
    y = rng.random(n) < 0.05
    s = np.where(y, rng.normal(0.7, 0.15, n), rng.normal(0.3, 0.15, n))
    blocks = np.arange(n) // 100
    return y, s, blocks


def test_bootstrap_interval_brackets_the_point_estimate():
    y, s, blocks = _synthetic()
    ci = bootstrap_f1(y, s >= 0.5, blocks, n_boot=300)
    assert ci.low <= ci.value <= ci.high and ci.high - ci.low < 0.3
    m = bootstrap_metric(y, s, blocks, "pr_auc", n_boot=60)
    assert m.low <= m.value <= m.high
    r = bootstrap_metric(y, s, blocks, "recall_at_precision", n_boot=60)
    assert 0 <= r.low <= r.high <= 1


def test_paired_delta_is_zero_for_identical_rules():
    y, s, blocks = _synthetic()
    delta = bootstrap_paired_delta_f1(y, s >= 0.5, s >= 0.5, blocks, n_boot=100)
    assert delta.value == delta.low == delta.high == 0.0


def test_paired_delta_detects_a_worse_rule():
    y, s, blocks = _synthetic()
    worse = np.random.default_rng(1).random(len(y)) < 0.05
    delta = bootstrap_paired_delta_f1(y, s >= 0.5, worse, blocks, n_boot=200)
    assert delta.low > 0  # the good rule is better with confidence


def test_bootstrap_handles_sparse_block_ids():
    y, s, blocks = _synthetic()
    sparse = blocks * 1000  # e.g. a tail subset whose block ids have gaps
    assert bootstrap_metric(y, s, sparse, "pr_auc", n_boot=20).value == pytest.approx(pr_auc(y, s))


def test_summarize_binary_shape():
    y, s, blocks = _synthetic()
    out = summarize_binary(y, s, 0.5, blocks, n_boot=50)
    assert out["tp"] + out["fn"] == out["positives"]
    assert {"f1", "pr_auc", "recall_at_precision_0_5"} <= set(out)
