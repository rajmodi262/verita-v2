"""Detect end to end on the generated fixture (quick settings)."""

from __future__ import annotations

import json

import lightgbm as lgb
import pandas as pd
import pytest
from typer.testing import CliRunner

from verita.cli import app
from verita.ml import stages
from verita.ml.detect import (
    TYPOLOGY_CLASSES,
    DetectConfig,
    load_frame,
    rules_score,
    run_detect,
    score_count,
)
from verita.ml.features import ALL_FEATURES
from verita.pipeline.config import PipelineError, get_dataset


@pytest.fixture(scope="module")
def detected(fx_run, fx_dataset):
    stages.stage_features(fx_dataset)
    return run_detect(fx_dataset, DetectConfig.quick())


def test_frame_has_splits_and_typologies(detected, fx_dataset):
    frame = load_frame(fx_dataset)
    assert set(frame["split"]) == {"train", "hpo", "calib", "test"}
    positives = frame[frame["is_laundering"]]
    assert positives["typology"].notna().all()
    assert frame.loc[~frame["is_laundering"], "typology"].isna().all()


def test_champion_beats_chance_and_reports_cis(detected):
    champion = next(m for m in detected.models if m["model"] == "lgbm_champion")
    test = champion["test"]
    assert test["pr_auc"]["value"] > 3 * test["base_rate"]
    for metric in ("f1", "pr_auc", "recall_at_precision_0_5"):
        ci = test[metric]
        assert ci["low"] <= ci["value"] <= ci["high"]
    assert champion["features"] == len(ALL_FEATURES)


def test_every_section_is_present(detected):
    names = [m["model"] for m in detected.models]
    assert names == ["rules_incumbent", "lgbm_transaction_only", "lgbm_champion"]
    assert len(detected.seeds["f1"]) == 2
    assert {a["removed_group"] for a in detected.ablation} == {
        "transaction",
        "velocity",
        "fan",
        "recency",
        "cycle",
    }
    assert len(detected.imbalance) == 3
    assert {"label_shuffle", "random_split"} <= set(detected.sanity)
    assert [t["typology"] for t in detected.per_typology] == TYPOLOGY_CLASSES
    assert detected.shap_global[0]["mean_abs_shap"] >= detected.shap_global[-1]["mean_abs_shap"]
    assert detected.latency["rows"] > 0


def test_label_shuffle_collapses(detected):
    shuffle = detected.sanity["label_shuffle"]
    champion = next(m for m in detected.models if m["model"] == "lgbm_champion")
    assert shuffle["test_pr_auc"] < champion["test"]["pr_auc"]["value"]


def test_artifacts_load_and_score_every_row(detected, fx_dataset):
    booster = lgb.Booster(model_file=str(fx_dataset.artifacts_dir / "detect" / "champion.txt"))
    assert booster.num_feature() == len(ALL_FEATURES)
    assert score_count(fx_dataset) == detected.split_sizes["train"]["rows"] + sum(
        detected.split_sizes[s]["rows"] for s in ("hpo", "calib", "test")
    )
    scores = pd.read_parquet(fx_dataset.processed_dir / "scores.parquet")
    assert scores["score"].between(0, 1).all()
    assert set(scores["typology_pred"]) <= set(TYPOLOGY_CLASSES)
    registry = json.loads((fx_dataset.artifacts_dir / "detect" / "registry.json").read_text())
    assert len(registry["champion_sha256"]) == 64 and registry["features"] == ALL_FEATURES


def test_metrics_file_is_written(detected, fx_dataset):
    metrics = json.loads((fx_dataset.artifacts_dir / "detect" / "metrics.json").read_text())
    assert metrics["dataset"] == "fixture" and metrics["threshold"] == detected.threshold


def test_rules_score_counts_fired_rules(detected, fx_dataset):
    frame = load_frame(fx_dataset)
    total, info = rules_score(frame, frame[frame["split"] == "train"])
    assert total.min() >= 0 and total.max() <= 6 and len(info["rules"]) == 6


def test_detect_requires_features(tmp_path):
    with pytest.raises(PipelineError, match="No features"):
        load_frame(get_dataset("fixture", root=tmp_path))


def test_cli_detect_quick(tmp_path):
    runner = CliRunner()
    root = str(tmp_path)
    for args in (
        ["data", "fixture"],
        ["data", "all", "--dataset", "fixture"],
        ["detect", "features", "--dataset", "fixture"],
        ["detect", "train", "--dataset", "fixture", "--quick"],
    ):
        extra = ["--root", root]
        result = runner.invoke(app, [*args, *extra])
        assert result.exit_code == 0, result.output
    assert (tmp_path / "artifacts" / "fixture" / "manifests" / "detect.json").exists()
