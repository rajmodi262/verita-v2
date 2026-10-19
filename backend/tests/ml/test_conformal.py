"""Calibration and the conformal recall guarantee."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from verita.ml.conformal import (
    apply_thresholds,
    brier,
    conformal_threshold,
    expected_calibration_error,
    fit_isotonic,
    fit_thresholds,
    reliability,
    replay_aci,
    replay_static,
)


def test_threshold_matches_the_order_statistic():
    scores = np.arange(1, 100, dtype=float)  # n = 99, alpha = 0.1 -> k = 10
    assert conformal_threshold(scores, 0.1) == 10.0


def test_too_few_positives_means_review_everything():
    assert conformal_threshold(np.array([0.5, 0.7]), 0.05) == -math.inf
    assert conformal_threshold(np.array([]), 0.05) == -math.inf


@pytest.mark.parametrize("alpha", [0.0, 1.0, -0.1])
def test_alpha_must_be_a_probability(alpha):
    with pytest.raises(ValueError, match="alpha"):
        conformal_threshold(np.array([0.1, 0.2]), alpha)


@pytest.mark.parametrize("alpha", [0.05, 0.1, 0.2])
def test_marginal_coverage_holds_and_is_tight(alpha):
    """Over many exchangeable draws, P(new positive >= t) is in [1-a, 1-a+1/(n+1)]."""
    rng = np.random.default_rng(7)
    n, trials = 60, 4000
    hits = 0
    for _ in range(trials):
        draw = rng.beta(2, 5, n + 1)
        hits += draw[-1] >= conformal_threshold(draw[:-1], alpha)
    rate = hits / trials
    se = math.sqrt(alpha * (1 - alpha) / trials)
    assert rate >= 1 - alpha - 3 * se
    assert rate <= 1 - alpha + 1 / (n + 1) + 3 * se


def test_mondrian_falls_back_for_small_groups():
    rng = np.random.default_rng(0)
    scores = rng.random(400)
    labels = np.zeros(400, dtype=bool)
    labels[:120] = True
    groups = np.array(["A"] * 100 + ["B"] * 20 + ["A"] * 280)
    th = fit_thresholds(scores, labels, groups, 0.1, min_group=50)
    assert "A" in th.by_group and "B" in th.fallback_groups
    assert th.for_group("B") == th.pooled
    assert th.group_sizes == {"A": 100, "B": 20}
    mask = apply_thresholds(scores, groups, th, "mondrian")
    expected = np.where(groups == "A", scores >= th.by_group["A"], scores >= th.pooled)
    assert (mask == expected).all()
    assert th.to_dict()["alpha"] == 0.1


def test_infinite_threshold_serialises_as_null():
    th = fit_thresholds(np.array([0.2]), np.array([True]), np.array(["A"]), 0.05)
    assert th.to_dict()["pooled"] is None


def test_isotonic_improves_calibration_of_a_miscalibrated_score():
    rng = np.random.default_rng(1)
    p = rng.random(20000)
    labels = rng.random(20000) < p**3  # the score overstates risk
    before = expected_calibration_error(p, labels)
    iso = fit_isotonic(p, labels)
    after = expected_calibration_error(iso.predict(p), labels)
    assert after < before / 3
    assert brier(iso.predict(p), labels) < brier(p, labels)
    bins = reliability(iso.predict(p), labels)
    assert sum(b["n"] for b in bins) == 20000
    assert all(b["low"] <= b["observed_rate"] <= b["high"] for b in bins)


def test_empty_inputs_are_harmless():
    empty = np.array([], dtype=float)
    assert expected_calibration_error(empty, empty.astype(bool)) == 0.0
    assert brier(empty, empty.astype(bool)) == 0.0


def _stream(rng, hours: int, shift: float) -> pd.DataFrame:
    """Hourly alerts; positives' scores drift down by ``shift`` over the period."""
    rows = []
    start = pd.Timestamp("2022-09-01")
    for h in range(hours):
        n = 40
        label = rng.random(n) < 0.15
        drift = shift * h / hours
        score = np.where(label, rng.beta(5, 2, n) - drift, rng.beta(2, 5, n))
        hour = start + pd.Timedelta(hours=h)
        rows += [
            {"hour": hour, "day": hour.strftime("%Y-%m-%d"), "score": s, "label": bool(y)}
            for s, y in zip(score, label, strict=True)
        ]
    frame = pd.DataFrame(rows)
    frame["group"] = "ALL"
    return frame


def test_static_replay_meets_target_without_shift():
    rng = np.random.default_rng(3)
    calib, test = _stream(rng, 96, 0.0), _stream(rng, 96, 0.0)
    th = fit_thresholds(
        calib["score"].to_numpy(), calib["label"].to_numpy(), calib["group"].to_numpy(), 0.1
    )
    result = replay_static(test, th, "pooled")
    assert result.overall["recall"]["high"] >= 0.9
    assert len(result.by_day) == 4
    assert result.overall["reviewed"] <= result.overall["alerts"]


def test_aci_recovers_coverage_under_drift():
    rng = np.random.default_rng(4)
    calib, test = _stream(rng, 96, 0.0), _stream(rng, 240, 0.45)
    calib_pos = calib.loc[calib["label"], "score"].to_numpy()
    th = fit_thresholds(
        calib["score"].to_numpy(), calib["label"].to_numpy(), calib["group"].to_numpy(), 0.1
    )
    static = replay_static(test, th, "pooled").overall["recall"]["value"]
    aci = replay_aci(calib_pos, test, 0.1, gamma=0.02, label_delay_hours=6)
    assert static < 0.88  # drift breaks the static guarantee
    assert aci.overall["recall"]["value"] > static + 0.02
    assert aci.overall["label_delay_hours"] == 6
    assert min(t["alpha_t"] for t in aci.overall["alpha_trace"]) < 0.1  # α_t tightened


@given(
    scores=st.lists(st.floats(0, 1, allow_nan=False), min_size=1, max_size=300),
    a=st.floats(0.001, 0.998),
    b=st.floats(0.001, 0.998),
)
def test_threshold_is_monotone_in_alpha(scores, a, b):
    """A stricter guarantee (smaller α) never raises the threshold: it reviews at least as much."""
    lo, hi = sorted((a, b))
    arr = np.array(scores)
    assert conformal_threshold(arr, lo) <= conformal_threshold(arr, hi)
