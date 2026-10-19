"""`verita detect alerts`: test-window scores → account-day alerts in the database (M3.02).

* Window: the **test** split only, so every alert is out-of-sample.
* Alert floor: the score that keeps 99% of HPO-split laundering transactions — deliberately
  generous. Which alerts actually get worked is Decide's job (capacity plan, recall guarantee).
* An alert is an (account, day) where any payment touching the account scored ≥ floor. Each
  alert keeps its riskiest payment and that payment's top-5 SHAP reasons.
* Ground truth (``truth_label``) is stored for validation and never shown in the analyst queue.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, cast

import duckdb
import lightgbm as lgb
import numpy as np
import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from verita.db.detect_models import Alert, AlertReason, Disposition, ModelVersion
from verita.ml.features import ALL_FEATURES
from verita.ml.reasons import top_reasons
from verita.pipeline.config import Dataset, PipelineError
from verita.pipeline.manifest import git_revision

FLOOR_RECALL = 0.99


@dataclass
class AlertReport:
    model_version_id: int
    floor: float
    threshold: float
    alerts: int
    positive_alerts: int
    flagged_alerts: int
    days: list[str]

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _registry(dataset: Dataset) -> dict[str, Any]:
    path = dataset.artifacts_dir / "detect" / "registry.json"
    if not path.exists():
        msg = f"No trained detector for {dataset.name}; run `verita detect train`"
        raise PipelineError(msg)
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def alert_floor(scores: pd.DataFrame, txn_labels: pd.Series) -> float:
    hpo = scores[scores["split"] == "hpo"]
    positives = hpo.loc[txn_labels.reindex(hpo["txn_id"]).to_numpy(), "score"]
    if positives.empty:
        msg = "HPO split has no laundering transactions to set the alert floor"
        raise PipelineError(msg)
    return float(np.quantile(positives, 1 - FLOOR_RECALL))


def _scores_and_labels(
    dataset: Dataset, con: duckdb.DuckDBPyConnection
) -> tuple[pd.DataFrame, pd.Series]:
    scores = pd.read_parquet(dataset.processed_dir / "scores.parquet")
    labels = (
        con.execute(
            f"SELECT txn_id, is_laundering FROM read_parquet('{dataset.transactions_parquet}')"
        )
        .df()
        .set_index("txn_id")["is_laundering"]
    )
    return scores, labels


def dataset_floor(dataset: Dataset) -> float:
    """The alert floor for a dataset's current scores (same rule the queue was built with)."""
    con = duckdb.connect()
    con.execute("SET enable_progress_bar = false")
    return alert_floor(*_scores_and_labels(dataset, con))


def build_alert_frame(dataset: Dataset, threshold: float) -> tuple[pd.DataFrame, float]:
    con = duckdb.connect()
    con.execute("SET enable_progress_bar = false")
    scores, labels = _scores_and_labels(dataset, con)
    floor = alert_floor(scores, labels)
    con.register("scores", scores)
    frame: pd.DataFrame = con.execute(f"""
        WITH test AS (
            SELECT t.txn_id, t.ts, CAST(t.ts AS DATE) AS day, t.from_id, t.to_id,
                   t.amount_paid, t.currency_paid, s.score, s.typology_pred, s.typology_conf
            FROM read_parquet('{dataset.transactions_parquet}') t
            JOIN scores s USING (txn_id)
            WHERE s.split = 'test'
        ),
        ends AS (
            SELECT from_id AS account_id, * EXCLUDE (from_id, to_id) FROM test
            UNION ALL
            SELECT to_id, * EXCLUDE (from_id, to_id) FROM test WHERE to_id <> from_id
        ),
        ranked AS (
            SELECT *, row_number() OVER (PARTITION BY account_id, day
                                         ORDER BY score DESC, txn_id) AS r
            FROM ends
        ),
        agg AS (
            SELECT account_id, day,
                   max(score) AS score,
                   avg(score) FILTER (WHERE r <= 3) AS score_top3_mean,
                   count(*) AS n_transactions,
                   count(*) FILTER (WHERE score >= {threshold}) AS n_flagged
            FROM ranked GROUP BY account_id, day HAVING max(score) >= {floor}
        )
        SELECT a.*, r.txn_id AS top_txn_id, r.amount_paid AS top_amount,
               r.currency_paid AS top_currency, r.typology_pred, r.typology_conf,
               coalesce(d.label, false) AS truth_label,
               coalesce(d.typologies, []) AS truth_typologies
        FROM agg a
        JOIN ranked r ON r.account_id = a.account_id AND r.day = a.day AND r.r = 1
        LEFT JOIN read_parquet('{dataset.account_day_parquet}') d
               ON d.account_id = a.account_id AND d.day = a.day
        ORDER BY a.day, a.score DESC
    """).df()
    return frame, floor


def reasons_for(
    dataset: Dataset, booster: lgb.Booster, txn_ids: list[int]
) -> dict[int, list[dict[str, Any]]]:
    if not txn_ids:
        return {}
    con = duckdb.connect()
    con.execute("SET enable_progress_bar = false")
    con.register("ids", pd.DataFrame({"txn_id": txn_ids}))
    feats = (
        con.execute(
            f"SELECT f.* FROM read_parquet('{dataset.features_parquet}') f JOIN ids USING (txn_id)"
        )
        .df()
        .drop_duplicates("txn_id")
        .set_index("txn_id")
    )
    contrib = np.asarray(booster.predict(feats[ALL_FEATURES], pred_contrib=True))[:, :-1]
    out: dict[int, list[dict[str, Any]]] = {}
    values = feats[ALL_FEATURES].to_numpy(dtype=float)
    for row, txn_id in enumerate(feats.index):
        out[int(txn_id)] = top_reasons(ALL_FEATURES, values[row].tolist(), contrib[row].tolist())
    return out


def write_alerts(dataset: Dataset, db: Session) -> AlertReport:
    registry = _registry(dataset)
    metrics_path = dataset.artifacts_dir / "detect" / "metrics.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else {}
    threshold = float(registry["threshold"])
    frame, floor = build_alert_frame(dataset, threshold)

    version = db.scalar(
        select(ModelVersion).where(ModelVersion.champion_sha256 == registry["champion_sha256"])
    )
    if version is None:
        version = ModelVersion(
            name=registry["model"],
            dataset=dataset.name,
            git_revision=git_revision(),
            champion_sha256=registry["champion_sha256"],
            features_sha256=registry["features_sha256"],
            threshold=threshold,
            metrics={
                "alert_floor": floor,
                "floor_recall": FLOOR_RECALL,
                "test": next(
                    (m["test"] for m in metrics.get("models", []) if m["model"] == "lgbm_champion"),
                    {},
                ),
            },
        )
        db.add(version)
        db.flush()
    else:
        worked = db.scalar(
            select(Disposition.id)
            .join(Alert, Alert.id == Disposition.alert_id)
            .where(Alert.model_version_id == version.id)
            .limit(1)
        )
        if worked is not None:
            msg = (
                "Alerts for this model version have analyst decisions; reloading would "
                "erase their history. Train and deploy a new model version instead."
            )
            raise PipelineError(msg)
        db.execute(delete(Alert).where(Alert.model_version_id == version.id))
    for other in db.scalars(select(ModelVersion).where(ModelVersion.dataset == dataset.name)):
        other.is_champion = other.id == version.id

    booster = lgb.Booster(model_file=str(dataset.artifacts_dir / "detect" / "champion.txt"))
    reasons = reasons_for(dataset, booster, frame["top_txn_id"].astype(int).unique().tolist())
    alerts = []
    records = cast("list[dict[str, Any]]", frame.to_dict(orient="records"))
    for row in records:
        alert = Alert(
            model_version_id=version.id,
            account_id=row["account_id"],
            alert_date=row["day"],
            score=float(row["score"]),
            score_top3_mean=float(row["score_top3_mean"]),
            typology_pred=str(row["typology_pred"]),
            typology_conf=float(row["typology_conf"]),
            top_txn_id=int(row["top_txn_id"]),
            top_amount=float(row["top_amount"]),
            top_currency=str(row["top_currency"]),
            n_transactions=int(row["n_transactions"]),
            n_flagged=int(row["n_flagged"]),
            truth_label=bool(row["truth_label"]),
            truth_typologies=[str(t) for t in row["truth_typologies"]],
        )
        alert.reasons = [
            AlertReason(
                rank=int(r["rank"]),
                feature=str(r["feature"]),
                value=float(r["value"]),
                shap=float(r["shap"]),
                text=str(r["text"]),
            )
            for r in reasons.get(int(row["top_txn_id"]), [])
        ]
        alerts.append(alert)
    db.add_all(alerts)
    db.flush()
    return AlertReport(
        model_version_id=version.id,
        floor=round(floor, 6),
        threshold=round(threshold, 6),
        alerts=len(frame),
        positive_alerts=int(frame["truth_label"].sum()),
        flagged_alerts=int((frame["n_flagged"] > 0).sum()),
        days=sorted({str(d) for d in frame["day"]}),
    )
