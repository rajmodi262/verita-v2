"""Detect stages with run manifests (wrapping features.py and detect.py)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from verita.ml.alerts import write_alerts
from verita.ml.decide import run_decide
from verita.ml.detect import DetectConfig, run_detect
from verita.ml.evidence_store import build_evidence_store
from verita.ml.features import build_features
from verita.pipeline.config import Dataset
from verita.pipeline.manifest import run_manifest


def stage_features(dataset: Dataset) -> dict[str, Any]:
    with run_manifest("features", dataset.name, dataset.manifests_dir) as m:
        m.add_input(dataset.transactions_parquet)
        report = build_features(dataset)
        m.add_output(dataset.features_parquet)
        m.metrics.update(report.to_dict())
    return report.to_dict()


def stage_detect(dataset: Dataset, *, quick: bool = False) -> dict[str, Any]:
    cfg = DetectConfig.quick() if quick else DetectConfig()
    (dataset.artifacts_dir / "detect").mkdir(parents=True, exist_ok=True)
    with run_manifest(
        "detect", dataset.name, dataset.manifests_dir, {"quick": quick, **cfg.__dict__}
    ) as m:
        m.add_input(dataset.features_parquet)
        m.add_input(dataset.pattern_links_parquet)
        m.add_input(dataset.splits_json)
        result = run_detect(dataset, cfg)
        for path in result.artifacts.values():
            m.add_output(__import__("pathlib").Path(path))
        champion = next(r for r in result.models if r["model"] == "lgbm_champion")
        m.metrics.update(
            test_f1=champion["test"]["f1"]["value"],
            test_pr_auc=champion["test"]["pr_auc"]["value"],
            timings=result.timings,
        )
    summary = {
        "threshold": result.threshold,
        "hpo": result.hpo,
        "models": {
            r["model"]: {"f1": r["test"]["f1"], "pr_auc": r["test"]["pr_auc"]}
            for r in result.models
        },
        "seeds": result.seeds,
        "timings": result.timings,
    }
    return summary


def stage_alerts(dataset: Dataset, db: Session) -> dict[str, Any]:
    with run_manifest("alerts", dataset.name, dataset.manifests_dir) as m:
        m.add_input(dataset.processed_dir / "scores.parquet")
        store = build_evidence_store(dataset)
        report = write_alerts(dataset, db)
        m.metrics.update(report.to_dict())
        m.metrics["evidence_store_mb"] = round(store.stat().st_size / 1e6, 1)
    return report.to_dict()


def stage_decide(dataset: Dataset, db: Session | None) -> dict[str, Any]:
    with run_manifest("decide", dataset.name, dataset.manifests_dir) as m:
        m.add_input(dataset.processed_dir / "scores.parquet")
        report = run_decide(dataset, db)
        m.metrics.update(report.headline)
        m.metrics["timings"] = report.timings
    return report.to_dict()
