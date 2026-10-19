"""Volume forecasting and drift monitoring."""

from __future__ import annotations

import numpy as np
import pytest

from verita.ml.drift import drift_table, psi, severity
from verita.ml.forecast import (
    QUANTILES,
    backtest,
    ets,
    forecast_all,
    lgbm_quantile,
    pinball,
    seasonal_naive,
)


def _series(days: int = 8, noise: float = 2.0, seed: int = 0):
    rng = np.random.default_rng(seed)
    hours = np.arange(days * 24)
    base = 20 + 10 * np.sin(2 * np.pi * hours / 24)
    return np.clip(base + rng.normal(0, noise, len(hours)), 0, None), hours


def test_seasonal_naive_repeats_the_last_day():
    hours = np.arange(72)
    series = (hours % 24).astype(float)
    fc = seasonal_naive(series, 24)
    assert np.allclose(fc.q(0.5), np.arange(24))
    assert fc.values.shape == (24, len(QUANTILES))


def test_seasonal_naive_handles_short_history():
    fc = seasonal_naive(np.array([3.0, 4.0]), 5)
    assert np.allclose(fc.q(0.5), 4.0)
    assert np.allclose(seasonal_naive(np.array([]), 3).q(0.5), 0.0)


@pytest.mark.parametrize("model", [ets, seasonal_naive])
def test_quantiles_are_ordered_and_non_negative(model):
    series, _ = _series()
    fc = model(series, 24)
    assert (np.diff(fc.values, axis=1) >= -1e-9).all()
    assert (fc.values >= 0).all()


def test_lgbm_quantiles_do_not_cross():
    series, hours = _series()
    fc = lgbm_quantile(series, hours, 12)
    assert (np.diff(fc.values, axis=1) >= -1e-9).all()


def test_short_history_falls_back_to_seasonal_naive():
    series, hours = _series(days=1)
    assert np.allclose(ets(series, 6).values, seasonal_naive(series, 6).values)
    assert np.allclose(lgbm_quantile(series, hours, 6).values, seasonal_naive(series, 6).values)


def test_pinball_matches_hand_calculation():
    actual = np.array([10.0, 10.0])
    predicted = np.array([8.0, 12.0])
    # under: 0.9*2 = 1.8; over: (0.9-1)*(-2) = 0.2 -> mean 1.0
    assert pinball(actual, predicted, 0.9) == pytest.approx(1.0)


def test_backtest_reports_every_model_with_sane_coverage():
    series, hours = _series(days=7)
    result = backtest(series, hours, test_start=5 * 24, step=12)
    assert set(result["models"]) == {"seasonal_naive", "ets", "lgbm", "ensemble"}
    assert result["origins"] == 4
    for scores in result["models"].values():
        assert 0 <= scores["coverage_95"] <= 1
        assert scores["mase"] > 0
    # on a clean seasonal series ETS should beat the naive baseline
    assert result["models"]["ets"]["mase"] < result["models"]["seasonal_naive"]["mase"]


def test_ensemble_is_the_mean_of_members():
    series, hours = _series()
    fcs = forecast_all(series, hours, 6)
    mean = np.mean([fcs[m].values for m in ("seasonal_naive", "ets", "lgbm")], axis=0)
    assert np.allclose(fcs["ensemble"].values, np.sort(mean, axis=1))


def test_psi_is_zero_for_the_same_distribution_and_large_for_a_shift():
    rng = np.random.default_rng(0)
    a = rng.normal(0, 1, 50_000)
    assert psi(a, rng.normal(0, 1, 50_000)) < 0.01
    assert psi(a, rng.normal(1.0, 1, 50_000)) > 0.25


def test_psi_edge_cases():
    assert psi(np.array([]), np.array([1.0])) == 0.0
    assert psi(np.ones(100), np.zeros(100)) == 0.0  # constant baseline: no bins
    assert psi(np.array([np.nan, 1.0, 2.0, 3.0]), np.array([1.0, 2.0])) >= 0.0


def test_severity_bands():
    assert severity(0.05) == "none"
    assert severity(0.1) == "moderate"
    assert severity(0.3) == "major"


def test_drift_table_sorts_by_psi_and_subsamples_ks():
    rng = np.random.default_rng(1)
    base = {"stable": rng.normal(0, 1, 5000), "moved": rng.normal(0, 1, 5000)}
    cur = {"stable": rng.normal(0, 1, 5000), "moved": rng.normal(2, 1, 5000)}
    rows = drift_table(base, cur, max_ks_rows=1000)
    assert [r["feature"] for r in rows] == ["moved", "stable"]
    assert rows[0]["severity"] == "major" and rows[0]["ks_pvalue"] < 1e-6


def test_backtest_bands_tile_the_test_period_once():
    series, hours = _series(days=7)
    result = backtest(series, hours, test_start=5 * 24, step=6)
    index = [b["index"] for b in result["bands"]]
    assert index == list(range(5 * 24, len(series)))
    assert all(b["q025"] <= b["q50"] <= b["q975"] for b in result["bands"])


def test_time_anchored_features_are_recognised():
    from verita.ml.decide import time_anchored

    assert time_anchored("r_age_min") and time_anchored("s_since_last_out_min")
    assert not time_anchored("s_payees_24h") and not time_anchored("score")
