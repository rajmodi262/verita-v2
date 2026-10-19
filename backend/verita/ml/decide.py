"""`verita decide run`: calibration, recall guarantee, coverage replay, forecasting, drift and
capacity frontiers (PIVOT §7, M4).

Everything is computed at the alert level (account-day, scored by its riskiest payment) over
the out-of-sample splits: ``calib`` fits the calibrator and the conformal thresholds; ``test``
is replayed. Results land in ``artifacts/<dataset>/decide/*.json``; calibrated probabilities
are written back to the alerts table for the planner.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb
import joblib
import numpy as np
import numpy.typing as npt
import pandas as pd
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from verita.db.detect_models import Alert, ModelVersion
from verita.ml.alerts import dataset_floor
from verita.ml.conformal import (
    DEFAULT_ALPHA,
    Thresholds,
    apply_thresholds,
    brier,
    expected_calibration_error,
    fit_isotonic,
    fit_thresholds,
    reliability,
    replay_aci,
    replay_static,
)
from verita.ml.drift import drift_table
from verita.ml.features import ALL_FEATURES
from verita.ml.forecast import backtest
from verita.optimize.planner import OBJECTIVES, Operations, frontier, prepare
from verita.pipeline.config import CONFIG_DIR, Dataset, PipelineError, load_yaml

FloatArray = npt.NDArray[np.float64]
ALPHAS = (0.01, 0.05, 0.10, 0.20)
FRONTIER_ALPHAS = ALPHAS  # every offered guarantee gets a precomputed frontier
ACI_GAMMA = 0.005
LABEL_DELAYS_HOURS = (6, 24, 48)
DRIFT_FEATURES = 12


@dataclass
class DecideReport:
    dataset: str
    alerts_frame_rows: int
    files: dict[str, str] = field(default_factory=dict)
    timings: dict[str, float] = field(default_factory=dict)
    headline: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def decide_dir(dataset: Dataset) -> Path:
    path = dataset.artifacts_dir / "decide"
    path.mkdir(parents=True, exist_ok=True)
    return path


def label_delay_hours() -> int:
    raw = load_yaml(CONFIG_DIR / "operations.yaml")
    return int(raw.get("label_delay_hours", 24))


def account_day_frame(dataset: Dataset) -> pd.DataFrame:
    """Every account-day in hpo / calib / test, scored by its riskiest payment."""
    scores = dataset.processed_dir / "scores.parquet"
    if not scores.exists():
        msg = f"No scores for {dataset.name}; run `verita detect train`"
        raise PipelineError(msg)
    con = duckdb.connect()
    con.execute("SET enable_progress_bar = false")
    frame: pd.DataFrame = con.execute(f"""
        WITH s AS (
            SELECT t.txn_id, t.ts, CAST(t.ts AS DATE) AS day, t.from_id, t.to_id,
                   t.amount_paid, t.currency_paid, sc.score, sc.split, sc.typology_pred
            FROM read_parquet('{dataset.transactions_parquet}') t
            JOIN read_parquet('{scores}') sc USING (txn_id)
            WHERE sc.split IN ('hpo', 'calib', 'test')
        ),
        ends AS (
            SELECT from_id AS account_id, * EXCLUDE (from_id, to_id) FROM s
            UNION ALL
            SELECT to_id, * EXCLUDE (from_id, to_id) FROM s WHERE to_id <> from_id
        ),
        ranked AS (
            SELECT *, row_number() OVER (PARTITION BY account_id, day
                                         ORDER BY score DESC, txn_id) AS r FROM ends
        )
        SELECT r.account_id, r.day, r.score, r.split, r.typology_pred AS "group",
               date_trunc('hour', r.ts) AS hour, r.txn_id AS top_txn_id,
               r.amount_paid AS top_amount, r.currency_paid AS top_currency,
               coalesce(d.label, false) AS label
        FROM ranked r
        LEFT JOIN read_parquet('{dataset.account_day_parquet}') d
               ON d.account_id = r.account_id AND d.day = r.day
        WHERE r.r = 1
    """).df()
    frame["day"] = frame["day"].astype(str)
    frame["hour"] = pd.to_datetime(frame["hour"])
    return frame


def _calibration(frame: pd.DataFrame, out: Path) -> tuple[Any, dict[str, Any]]:
    calib, test = frame[frame["split"] == "calib"], frame[frame["split"] == "test"]
    model = fit_isotonic(calib["score"].to_numpy(), calib["label"].to_numpy(dtype=bool))
    joblib.dump(model, out / "isotonic.joblib")
    y = test["label"].to_numpy(dtype=bool)
    raw = test["score"].to_numpy(dtype=float)
    cal = np.asarray(model.predict(raw), dtype=float)
    result = {
        "fitted_on": {
            "split": "calib",
            "alerts": len(calib),
            "positives": int(calib["label"].sum()),
        },
        "evaluated_on": {"split": "test", "alerts": len(test), "positives": int(y.sum())},
        "before": {
            "ece": round(expected_calibration_error(raw, y), 6),
            "brier": round(brier(raw, y), 8),
            "reliability": reliability(raw, y),
        },
        "after": {
            "ece": round(expected_calibration_error(cal, y), 6),
            "brier": round(brier(cal, y), 8),
            "reliability": reliability(cal, y),
        },
        "note": "Raw scores come from a model trained on subsampled negatives, so they are not "
        "probabilities; isotonic regression on the calibration split maps them to "
        "probabilities. Equal-mass bins.",
    }
    return model, result


def _thresholds(frame: pd.DataFrame) -> dict[str, Any]:
    calib = frame[frame["split"] == "calib"]
    out = {}
    for alpha in ALPHAS:
        out[str(alpha)] = fit_thresholds(
            calib["score"].to_numpy(), calib["label"].to_numpy(), calib["group"].to_numpy(), alpha
        ).to_dict()
    return out


def _coverage(frame: pd.DataFrame, tail_days: set[str]) -> dict[str, Any]:
    calib, test = frame[frame["split"] == "calib"], frame[frame["split"] == "test"]
    calib_pos = calib.loc[calib["label"], "score"].to_numpy(dtype=float)
    result: dict[str, Any] = {"by_alpha": {}, "label_delay_sensitivity": {}}
    for alpha in ALPHAS:
        th = fit_thresholds(
            calib["score"].to_numpy(), calib["label"].to_numpy(), calib["group"].to_numpy(), alpha
        )
        runs = {
            "static_pooled": replay_static(test, th, "pooled").to_dict(),
            "static_mondrian": replay_static(test, th, "mondrian").to_dict(),
            "aci_pooled": replay_aci(
                calib_pos, test, alpha, ACI_GAMMA, label_delay_hours()
            ).to_dict(),
        }
        bulk = test[~test["day"].isin(tail_days)]
        runs["static_pooled_bulk_only"] = replay_static(bulk, th, "pooled").to_dict()
        result["by_alpha"][str(alpha)] = runs
    for delay in LABEL_DELAYS_HOURS:
        r = replay_aci(calib_pos, test, DEFAULT_ALPHA, ACI_GAMMA, delay).to_dict()
        r["overall"].pop("alpha_trace", None)
        result["label_delay_sensitivity"][str(delay)] = r["overall"]
    result["tail_days"] = sorted(tail_days)
    result["gamma"] = ACI_GAMMA
    return result


def _forecast(frame: pd.DataFrame, thresholds: dict[str, Any]) -> dict[str, Any]:
    """Hourly count of alerts the default guarantee requires reviewing (the workload)."""
    cut = thresholds[str(DEFAULT_ALPHA)]["pooled"]
    cut = -np.inf if cut is None else float(cut)
    work = frame[frame["score"] >= cut]
    counts = work.groupby("hour").size()
    full = pd.date_range(frame["hour"].min(), frame["hour"].max(), freq="h")
    series = counts.reindex(full, fill_value=0).astype(float)
    hours = ((full - full[0]) / pd.Timedelta(hours=1)).astype(int).to_numpy()
    test_start_hour = frame.loc[frame["split"] == "test", "hour"].min()
    start = int(np.searchsorted(full, test_start_hour))
    values: FloatArray = np.asarray(series.to_numpy(), dtype=np.float64)
    result = backtest(values, hours, start)
    for band in result["bands"]:
        band["hour"] = pd.Timestamp(full[int(band.pop("index"))]).isoformat()
    result["series"] = [
        {"hour": pd.Timestamp(h).isoformat(), "alerts": int(v)}
        for h, v in zip(full, series.to_numpy(), strict=True)
    ]
    result["test_start"] = test_start_hour.isoformat()
    result["workload_definition"] = (
        f"alerts per hour whose score clears the α={DEFAULT_ALPHA} pooled conformal threshold"
    )
    return result


def time_anchored(feature: str) -> bool:
    """Features measured from a fixed origin (account age, time since last activity).

    They grow with the calendar by construction, so any later window "drifts" from any earlier
    one; PSI on them measures elapsed time, not a change in behaviour.
    """
    return "_age_" in feature or "_since_last_" in feature


def _drift(dataset: Dataset, frame: pd.DataFrame, shap_order: list[str]) -> dict[str, Any]:
    checked = [f for f in shap_order if not time_anchored(f)][:DRIFT_FEATURES]
    excluded = [f for f in shap_order if time_anchored(f)]
    feats = pd.read_parquet(dataset.features_parquet, columns=["seq", "ts", *checked])
    splits = json.loads(dataset.splits_json.read_text(encoding="utf-8"))["seq_ranges"]
    calib_lo, calib_hi = splits["calib"]
    test_lo = splits["test"][0]
    base = feats[(feats["seq"] >= calib_lo) & (feats["seq"] <= calib_hi)]
    test = feats[feats["seq"] >= test_lo]
    by_day = []
    calib_scores = frame.loc[frame["split"] == "calib", "score"].to_numpy(dtype=float)
    for day, part in test.groupby(test["ts"].dt.strftime("%Y-%m-%d")):
        baseline = {c: base[c].to_numpy(dtype=float) for c in checked}
        current = {c: part[c].to_numpy(dtype=float) for c in checked}
        day_scores = frame.loc[(frame["split"] == "test") & (frame["day"] == day), "score"]
        baseline["score"] = calib_scores
        current["score"] = day_scores.to_numpy(dtype=float)
        table = drift_table(baseline, current)
        by_day.append(
            {
                "day": day,
                "rows": len(part),
                "features": table,
                "max_psi": table[0]["psi"] if table else 0.0,
                "recalibrate": any(r["severity"] == "major" for r in table),
            }
        )
    return {
        "baseline": "calib split",
        "features_checked": [*checked, "score"],
        "excluded_time_anchored": excluded,
        "by_day": by_day,
    }


def _frontiers(
    frame: pd.DataFrame, iso: Any, thresholds: dict[str, Any], ops: Operations, floor: float
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Staffing frontier per test day, over exactly the alerts the queue holds (score ≥ floor).

    Account-days below the floor are never shown to an analyst, so their expected positives
    (Σ calibrated p) are passed to the planner as uncatchable: recall is never overstated.
    """
    test = frame[frame["split"] == "test"].copy()
    test["calibrated_prob"] = np.asarray(iso.predict(test["score"].to_numpy()), dtype=float)
    test["typology_pred"] = test["group"]
    in_queue = test["score"].to_numpy() >= floor
    queue = test[in_queue]
    outside = test[~in_queue].groupby("day")["calibrated_prob"].sum().to_dict()
    queue_info: dict[str, Any] = {
        "floor": floor,
        "by_day": {
            str(day): {
                "alerts": len(part),
                "outside_expected": round(float(outside.get(day, 0.0)), 4),
                "outside_account_days": int((test.loc[~in_queue, "day"] == day).sum()),
                "outside_positives": int(
                    test.loc[~in_queue & (test["day"] == day).to_numpy(), "label"].sum()
                ),
            }
            for day, part in queue.groupby("day")
        },
        "note": "Expected positives below the alert floor count against every plan's recall.",
    }
    out: dict[str, Any] = {}
    for alpha in FRONTIER_ALPHAS:
        t = thresholds[str(alpha)]
        th = Thresholds(
            alpha=alpha,
            pooled=-np.inf if t["pooled"] is None else t["pooled"],
            by_group={k: (-np.inf if v is None else v) for k, v in t["by_group"].items()},
        )
        for mode in ("pooled", "mondrian"):
            for objective in OBJECTIVES:
                days = {}
                for day, part in queue.groupby("day"):
                    prepared = prepare(part, ops)
                    mask = apply_thresholds(
                        prepared["score"].to_numpy(), prepared["group"].to_numpy(), th, mode
                    )
                    info = queue_info["by_day"][str(day)]
                    days[str(day)] = frontier(
                        prepared,
                        mask,
                        ops,
                        False,
                        info["outside_expected"],
                        objective,
                        labels=prepared["label"].to_numpy(dtype=bool),
                        outside_positives=info["outside_positives"],
                    )
                out[f"{alpha}|{mode}|{objective}"] = days
    return out, queue_info


def _write(out: Path, name: str, data: Any) -> str:
    path = out / f"{name}.json"
    path.write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")
    return path.as_posix()


def run_decide(dataset: Dataset, db: Session | None = None) -> DecideReport:
    out = decide_dir(dataset)
    timings: dict[str, float] = {}

    def timed(name: str, started: float) -> None:
        timings[name] = round(time.perf_counter() - started, 2)

    t = time.perf_counter()
    frame = account_day_frame(dataset)
    timed("frame", t)
    report = DecideReport(dataset=dataset.name, alerts_frame_rows=len(frame))
    validation = json.loads(dataset.validation_json.read_text(encoding="utf-8"))
    tail = set(validation.get("daily_volume", {}).get("sparse_tail_days", []))
    metrics = json.loads((dataset.artifacts_dir / "detect" / "metrics.json").read_text())
    shap_order = [r["feature"] for r in metrics["shap_global"]] or ALL_FEATURES

    t = time.perf_counter()
    iso, calibration = _calibration(frame, out)
    report.files["calibration"] = _write(out, "calibration", calibration)
    timed("calibration", t)

    t = time.perf_counter()
    thresholds = _thresholds(frame)
    report.files["thresholds"] = _write(out, "thresholds", thresholds)
    timed("thresholds", t)

    t = time.perf_counter()
    coverage = _coverage(frame, tail)
    report.files["coverage"] = _write(out, "coverage", coverage)
    timed("coverage", t)

    t = time.perf_counter()
    report.files["forecast"] = _write(out, "forecast", _forecast(frame, thresholds))
    timed("forecast", t)

    t = time.perf_counter()
    report.files["drift"] = _write(out, "drift", _drift(dataset, frame, shap_order))
    timed("drift", t)

    t = time.perf_counter()
    ops = Operations.load()
    frontiers, queue_info = _frontiers(frame, iso, thresholds, ops, dataset_floor(dataset))
    report.files["frontier"] = _write(out, "frontier", frontiers)
    report.files["queue"] = _write(out, "queue", queue_info)
    report.files["operations"] = _write(out, "operations", ops.to_dict())
    timed("frontier", t)

    if db is not None:
        t = time.perf_counter()
        _write_calibrated(db, iso)
        timed("calibrated_alerts", t)

    default = coverage["by_alpha"][str(DEFAULT_ALPHA)]
    report.headline = {
        "alpha": DEFAULT_ALPHA,
        "target_recall": 1 - DEFAULT_ALPHA,
        "static_pooled_recall": default["static_pooled"]["overall"]["recall"],
        "aci_recall": default["aci_pooled"]["overall"]["recall"],
        "ece_before": calibration["before"]["ece"],
        "ece_after": calibration["after"]["ece"],
    }
    report.timings = timings
    return report


def _write_calibrated(db: Session, iso: Any) -> None:
    version = db.scalar(select(ModelVersion).where(ModelVersion.is_champion))
    if version is None:
        return
    rows = db.execute(
        select(Alert.id, Alert.score).where(Alert.model_version_id == version.id)
    ).all()
    if not rows:
        return
    ids = np.array([r[0] for r in rows])
    probs = np.asarray(iso.predict(np.array([r[1] for r in rows], dtype=float)), dtype=float)
    db.execute(
        update(Alert),
        [{"id": int(i), "calibrated_prob": float(p)} for i, p in zip(ids, probs, strict=True)],
    )
    db.flush()
