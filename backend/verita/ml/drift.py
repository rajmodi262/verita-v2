"""Drift monitoring (PIVOT §7.5, M4.18): PSI and KS per feature and on the score."""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt
from scipy import stats

FloatArray = npt.NDArray[np.float64]
PSI_MODERATE = 0.10
PSI_MAJOR = 0.25


def psi(expected: FloatArray, actual: FloatArray, bins: int = 10) -> float:
    """Population Stability Index with quantile bins cut on the baseline."""
    e = expected[np.isfinite(expected)]
    a = actual[np.isfinite(actual)]
    if len(e) == 0 or len(a) == 0:
        return 0.0
    edges = np.unique(np.quantile(e, np.linspace(0, 1, bins + 1)))
    if len(edges) < 2:  # noqa: PLR2004 - constant baseline
        return 0.0
    edges[0], edges[-1] = -np.inf, np.inf
    eps = 1e-6
    ep = np.clip(np.histogram(e, edges)[0] / len(e), eps, None)
    ap = np.clip(np.histogram(a, edges)[0] / len(a), eps, None)
    return float(np.sum((ap - ep) * np.log(ap / ep)))


def severity(value: float) -> str:
    if value >= PSI_MAJOR:
        return "major"
    if value >= PSI_MODERATE:
        return "moderate"
    return "none"


def drift_table(
    baseline: dict[str, FloatArray],
    current: dict[str, FloatArray],
    max_ks_rows: int = 200_000,
    seed: int = 0,
) -> list[dict[str, Any]]:
    rng = np.random.default_rng(seed)
    rows: list[dict[str, Any]] = []
    for name, base in baseline.items():
        cur = current[name]
        value = psi(base, cur)
        b = base if len(base) <= max_ks_rows else rng.choice(base, max_ks_rows, replace=False)
        c = cur if len(cur) <= max_ks_rows else rng.choice(cur, max_ks_rows, replace=False)
        ks = stats.ks_2samp(b, c) if len(b) and len(c) else None
        rows.append(
            {
                "feature": name,
                "psi": round(value, 6),
                "severity": severity(value),
                "ks_statistic": round(float(ks.statistic), 6) if ks is not None else None,
                "ks_pvalue": float(ks.pvalue) if ks is not None else None,
            }
        )
    rows.sort(key=lambda r: -float(r["psi"]))
    return rows
