"""Alert-volume forecasting with honest intervals (PIVOT §7.3, M4.10–M4.12).

The IBM data has only ~10 days of bulk traffic, so the series is **hourly**. History is the
out-of-sample part of the timeline only (hpo + calib + test): training-split scores are
in-sample and would overstate alert volume.

Models
    seasonal_naive  value 24 hours earlier (the baseline every model must beat)
    ets             additive Holt-Winters with a 24-hour season (statsmodels)
    lgbm            LightGBM quantile regression on lags 1, 2, 3, 24 and hour of day
    ensemble        mean of the three models' quantiles

Backtest
    Rolling origin every 6 hours across the test period, 24-hour horizon. Scored by MASE
    (scaled by the in-sample seasonal-naive error), pinball loss and 80% / 95% interval
    coverage — an interval that claims 95% should cover about 95% of outcomes.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Any

import lightgbm as lgb
import numpy as np
import numpy.typing as npt
import pandas as pd

FloatArray = npt.NDArray[np.float64]
SEASON = 24
HORIZON = 24
STEP = 6
QUANTILES = (0.025, 0.1, 0.5, 0.9, 0.975)
MODELS = ("seasonal_naive", "ets", "lgbm", "ensemble")


@dataclass
class Forecast:
    """Quantile forecasts, shape (horizon, len(QUANTILES))."""

    values: FloatArray

    def q(self, level: float) -> FloatArray:
        return self.values[:, QUANTILES.index(level)]


def _residual_quantiles(residuals: FloatArray) -> FloatArray:
    if len(residuals) == 0:
        return np.zeros(len(QUANTILES))
    return np.quantile(residuals, QUANTILES)


def seasonal_naive(history: FloatArray, horizon: int = HORIZON) -> Forecast:
    if len(history) < SEASON:
        point = np.full(horizon, history[-1] if len(history) else 0.0)
        return Forecast(np.clip(point[:, None] + np.zeros(len(QUANTILES)), 0, None))
    reps = int(np.ceil(horizon / SEASON))
    point = np.tile(history[-SEASON:], reps)[:horizon]
    residuals = history[SEASON:] - history[:-SEASON]
    spread = _residual_quantiles(residuals)
    return Forecast(np.clip(point[:, None] + spread[None, :], 0, None))


def ets(history: FloatArray, horizon: int = HORIZON) -> Forecast:
    from statsmodels.tsa.holtwinters import ExponentialSmoothing  # noqa: PLC0415 - heavy

    if len(history) < 2 * SEASON:
        return seasonal_naive(history, horizon)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = ExponentialSmoothing(
            history,
            trend=None,
            seasonal="add",
            seasonal_periods=SEASON,
            initialization_method="estimated",
        )
        fitted = model.fit(optimized=True)
    point = np.asarray(fitted.forecast(horizon), dtype=float)
    spread = _residual_quantiles(np.asarray(history - fitted.fittedvalues, dtype=float))
    return Forecast(np.clip(point[:, None] + spread[None, :], 0, None))


def _lag_frame(series: FloatArray, hours: npt.NDArray[np.int64]) -> pd.DataFrame:
    s = pd.Series(series)
    return pd.DataFrame(
        {
            "lag1": s.shift(1),
            "lag2": s.shift(2),
            "lag3": s.shift(3),
            "lag24": s.shift(24),
            "hour": hours % 24,
        }
    )


def lgbm_quantile(
    history: FloatArray, hours: npt.NDArray[np.int64], horizon: int = HORIZON
) -> Forecast:
    """Recursive multi-step: each step's median feeds the next step's lags."""
    if len(history) < 2 * SEASON:
        return seasonal_naive(history, horizon)
    frame = _lag_frame(history, hours).iloc[SEASON:]
    target = history[SEASON:]
    models = {}
    for level in QUANTILES:
        params = {
            "objective": "quantile",
            "alpha": level,
            "learning_rate": 0.05,
            "num_leaves": 7,
            "min_data_in_leaf": 5,
            "verbose": -1,
            "seed": 0,
        }
        models[level] = lgb.train(params, lgb.Dataset(frame, target), num_boost_round=150)
    extended = list(history)
    out = np.zeros((horizon, len(QUANTILES)))
    for step in range(horizon):
        hour = int(hours[-1] + step + 1)
        row = pd.DataFrame(
            [
                {
                    "lag1": extended[-1],
                    "lag2": extended[-2],
                    "lag3": extended[-3],
                    "lag24": extended[-24],
                    "hour": hour % 24,
                }
            ]
        )
        preds = np.array([float(models[q].predict(row)[0]) for q in QUANTILES])
        preds = np.maximum.accumulate(np.clip(preds, 0, None))  # quantiles must not cross
        out[step] = preds
        extended.append(preds[QUANTILES.index(0.5)])
    return Forecast(out)


def forecast_all(
    history: FloatArray, hours: npt.NDArray[np.int64], horizon: int = HORIZON
) -> dict[str, Forecast]:
    fc = {
        "seasonal_naive": seasonal_naive(history, horizon),
        "ets": ets(history, horizon),
        "lgbm": lgbm_quantile(history, hours, horizon),
    }
    stacked = np.stack([f.values for f in fc.values()])
    fc["ensemble"] = Forecast(np.sort(stacked.mean(axis=0), axis=1))
    return fc


def pinball(actual: FloatArray, predicted: FloatArray, level: float) -> float:
    diff = actual - predicted
    return float(np.mean(np.maximum(level * diff, (level - 1) * diff)))


def backtest(
    series: FloatArray,
    hours: npt.NDArray[np.int64],
    test_start: int,
    step: int = STEP,
    horizon: int = HORIZON,
) -> dict[str, Any]:
    """Rolling-origin evaluation from ``test_start`` to the end of the series."""
    scale = float(np.mean(np.abs(series[SEASON:test_start] - series[: test_start - SEASON])))
    scale = scale if scale > 0 else 1.0
    per_model: dict[str, dict[str, list[float]]] = {
        m: {"abs": [], "p10": [], "p50": [], "p90": [], "in80": [], "in95": []} for m in MODELS
    }
    origins = list(range(test_start, len(series) - 1, step))
    bands: list[dict[str, float | int]] = []
    for origin in origins:
        h = min(horizon, len(series) - origin)
        actual = series[origin : origin + h]
        fcs = forecast_all(series[:origin], hours[:origin], h)
        for name, fc in fcs.items():
            acc = per_model[name]
            acc["abs"] += list(np.abs(actual - fc.q(0.5)))
            acc["p10"].append(pinball(actual, fc.q(0.1), 0.1))
            acc["p50"].append(pinball(actual, fc.q(0.5), 0.5))
            acc["p90"].append(pinball(actual, fc.q(0.9), 0.9))
            acc["in80"] += list((actual >= fc.q(0.1)) & (actual <= fc.q(0.9)))
            acc["in95"] += list((actual >= fc.q(0.025)) & (actual <= fc.q(0.975)))
        # the first `step` hours of each origin's ensemble tile the test period exactly once
        ens = fcs["ensemble"].values
        for i in range(min(step, h)):
            bands.append(
                {
                    "index": origin + i,
                    **{
                        name: round(float(ens[i, j]), 3)
                        for j, name in enumerate(("q025", "q10", "q50", "q90", "q975"))
                    },
                }
            )
    results = {}
    for name, acc in per_model.items():
        results[name] = {
            "mase": round(float(np.mean(acc["abs"])) / scale, 4) if acc["abs"] else None,
            "pinball_10": round(float(np.mean(acc["p10"])), 4) if acc["p10"] else None,
            "pinball_50": round(float(np.mean(acc["p50"])), 4) if acc["p50"] else None,
            "pinball_90": round(float(np.mean(acc["p90"])), 4) if acc["p90"] else None,
            "coverage_80": round(float(np.mean(acc["in80"])), 4) if acc["in80"] else None,
            "coverage_95": round(float(np.mean(acc["in95"])), 4) if acc["in95"] else None,
        }
    return {
        "origins": len(origins),
        "horizon_hours": horizon,
        "step_hours": step,
        "mase_scale": round(scale, 4),
        "models": results,
        "bands": bands,
    }
