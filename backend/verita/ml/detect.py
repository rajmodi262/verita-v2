"""Detect: train, select and evaluate the laundering detector (PIVOT §6.3–6.4, M2.09–M2.22).

Protocol
--------
* Splits are the count-based temporal splits from M1. ``train`` fits models, ``hpo`` selects
  hyper-parameters and the decision threshold, ``test`` is scored once at the end. ``calib`` is
  untouched here (it belongs to Decide).
* Every LightGBM fit trains on all training positives plus a seeded 20% sample of training
  negatives (documented imbalance strategy; compared against alternatives in the ablation).
  Scores are therefore *not* calibrated probabilities — Decide calibrates them.
* Test metrics carry block-bootstrap 95% CIs (6-hour blocks), and are reported for the whole
  test split and separately for its bulk and its sparse tail.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import duckdb
import lightgbm as lgb
import numpy as np
import numpy.typing as npt
import optuna
import pandas as pd

from verita.ml.evaluation import (
    best_f1_threshold,
    bootstrap_paired_delta_f1,
    confusion,
    summarize_binary,
    time_blocks,
    wilson,
)
from verita.ml.features import ALL_FEATURES, CATEGORICAL, FEATURE_GROUPS, TRANSACTION
from verita.pipeline.config import Dataset, PipelineError
from verita.pipeline.manifest import sha256_file
from verita.pipeline.patterns import UNATTRIBUTED
from verita.pipeline.splits import load_splits

FloatArray = npt.NDArray[np.float64]
BoolArray = npt.NDArray[np.bool_]

TYPOLOGY_CLASSES = [
    "BIPARTITE",
    "CYCLE",
    "FAN-IN",
    "FAN-OUT",
    "GATHER-SCATTER",
    "RANDOM",
    "SCATTER-GATHER",
    "STACK",
    UNATTRIBUTED,
]


@dataclass(frozen=True)
class DetectConfig:
    trials: int = 40
    n_boot: int = 1000
    seeds: tuple[int, ...] = (0, 1, 2, 3, 4)
    negative_rate: float = 0.2
    block_minutes: int = 360
    max_rounds: int = 2000
    early_stopping: int = 100
    shap_rows: int = 20_000

    @classmethod
    def quick(cls) -> DetectConfig:
        """Tiny settings for tests and the fixture."""
        return cls(
            trials=2, n_boot=50, seeds=(0, 1), max_rounds=60, early_stopping=10, shap_rows=500
        )


# ── data ─────────────────────────────────────────────────────────────────────


def load_frame(dataset: Dataset) -> pd.DataFrame:
    if not dataset.features_parquet.exists():
        msg = f"No features for {dataset.name}; run `verita detect features`"
        raise PipelineError(msg)
    splits = load_splits(dataset)
    frame = pd.read_parquet(dataset.features_parquet)
    links = pd.read_parquet(dataset.pattern_links_parquet)
    first = links.sort_values("attempt_id").drop_duplicates("txn_id")[["txn_id", "typology"]]
    frame = frame.merge(first, on="txn_id", how="left")
    frame.loc[frame["is_laundering"] & frame["typology"].isna(), "typology"] = UNATTRIBUTED
    bounds = np.array([splits.seq_ranges[n][1] for n in ("train", "hpo", "calib")])
    frame["split"] = np.select(
        [frame["seq"] <= bounds[0], frame["seq"] <= bounds[1], frame["seq"] <= bounds[2]],
        ["train", "hpo", "calib"],
        default="test",
    )
    frame["minute"] = (frame["ts"] - pd.Timestamp("2000-01-01")).dt.total_seconds() // 60
    frame["minute"] = frame["minute"].astype(np.int64)
    return frame


def tail_days(dataset: Dataset) -> set[str]:
    report = json.loads(dataset.validation_json.read_text(encoding="utf-8"))
    return set(report.get("daily_volume", {}).get("sparse_tail_days", []))


def subsample(frame: pd.DataFrame, rate: float, seed: int) -> pd.DataFrame:
    if rate >= 1:
        return frame
    rng = np.random.default_rng(seed)
    keep = frame["is_laundering"].to_numpy() | (rng.random(len(frame)) < rate)
    return frame[keep]


# ── models ───────────────────────────────────────────────────────────────────

BASE_PARAMS: dict[str, Any] = {
    "objective": "binary",
    "learning_rate": 0.05,
    "num_leaves": 63,
    "min_data_in_leaf": 50,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "lambda_l2": 1.0,
    "verbose": -1,
    "num_threads": 0,
}


def fit(
    train: pd.DataFrame,
    valid: pd.DataFrame,
    features: list[str],
    params: dict[str, Any],
    cfg: DetectConfig,
    seed: int,
) -> lgb.Booster:
    cats = [c for c in CATEGORICAL if c in features]
    dtrain = lgb.Dataset(
        train[features],
        train["is_laundering"].astype(int),
        categorical_feature=cats,
        free_raw_data=False,
    )
    dvalid = lgb.Dataset(
        valid[features],
        valid["is_laundering"].astype(int),
        categorical_feature=cats,
        reference=dtrain,
    )
    booster = lgb.train(
        {**BASE_PARAMS, **params, "seed": seed, "metric": "average_precision"},
        dtrain,
        num_boost_round=cfg.max_rounds,
        valid_sets=[dvalid],
        callbacks=[lgb.early_stopping(cfg.early_stopping, verbose=False)],
    )
    return booster


def score(booster: lgb.Booster, frame: pd.DataFrame, features: list[str]) -> FloatArray:
    return np.asarray(
        booster.predict(frame[features], num_iteration=booster.best_iteration), dtype=np.float64
    )


def tune(train: pd.DataFrame, hpo: pd.DataFrame, cfg: DetectConfig) -> dict[str, Any]:
    """Optuna search on the HPO split only; objective = max F1 on HPO."""
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    sub = subsample(train, cfg.negative_rate, seed=0)

    def objective(trial: optuna.Trial) -> float:
        params = {
            "learning_rate": trial.suggest_float("learning_rate", 0.02, 0.2, log=True),
            "num_leaves": trial.suggest_int("num_leaves", 15, 255, log=True),
            "min_data_in_leaf": trial.suggest_int("min_data_in_leaf", 10, 500, log=True),
            "feature_fraction": trial.suggest_float("feature_fraction", 0.5, 1.0),
            "lambda_l2": trial.suggest_float("lambda_l2", 1e-3, 30, log=True),
        }
        booster = fit(sub, hpo, ALL_FEATURES, params, cfg, seed=0)
        _, f1 = best_f1_threshold(
            hpo["is_laundering"].to_numpy(), score(booster, hpo, ALL_FEATURES)
        )
        return f1

    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=0))
    study.optimize(objective, n_trials=cfg.trials)
    return {
        "params": study.best_params,
        "hpo_f1": round(study.best_value, 6),
        "trials": len(study.trials),
    }


# ── incumbent rules ──────────────────────────────────────────────────────────


def rules_score(frame: pd.DataFrame, train: pd.DataFrame) -> tuple[FloatArray, dict[str, Any]]:
    """Six classic transaction-monitoring rules; the score is the number that fire."""
    large = float(train["log_amount_paid"].quantile(0.99))
    rules = {
        "large_amount (top 1% of training amounts)": frame["log_amount_paid"] >= large,
        "rapid_pass_through (sender received money < 60 min ago)": frame[
            "s_since_last_in_min"
        ].between(0, 59),
        "fan_out (sender paid >= 5 distinct payees in 24h)": frame["s_payees_24h"] >= 5,  # noqa: PLR2004
        "fan_in (receiver paid by >= 5 distinct payers in 24h)": frame["r_payers_24h"] >= 5,  # noqa: PLR2004
        "new_account (sender first seen < 24h ago)": frame["s_age_min"].between(-1, 1439),
        "cash_or_crypto (Cash or Bitcoin format)": frame["payment_format_code"].isin(
            [1, 2]
        ),  # Bitcoin, Cash in sorted enum order
    }
    total = np.zeros(len(frame))
    for fired in rules.values():
        total += fired.to_numpy(dtype=np.float64)
    return total, {"rules": list(rules), "large_amount_log_threshold": round(large, 4)}


# ── evaluation helpers ───────────────────────────────────────────────────────


def evaluate(
    name: str,
    y: BoolArray,
    scores: FloatArray,
    threshold: float,
    blocks: npt.NDArray[np.int64],
    tail_mask: BoolArray,
    cfg: DetectConfig,
) -> dict[str, Any]:
    out: dict[str, Any] = {"model": name}
    out["test"] = summarize_binary(y, scores, threshold, blocks, cfg.n_boot)
    for part, mask in (("test_bulk", ~tail_mask), ("test_tail", tail_mask)):
        if mask.sum() and y[mask].any():
            out[part] = summarize_binary(y[mask], scores[mask], threshold, blocks[mask], cfg.n_boot)
        else:
            out[part] = None
    return out


def per_typology_recall(test: pd.DataFrame, pred: BoolArray) -> list[dict[str, Any]]:
    rows = []
    positives = test["is_laundering"].to_numpy()
    for typology in TYPOLOGY_CLASSES:
        mask = positives & (test["typology"] == typology).to_numpy()
        support = int(mask.sum())
        hits = int((pred & mask).sum())
        ci = wilson(hits, support)
        rows.append(
            {"typology": typology, "support": support, "detected": hits, "recall": ci.to_dict()}
        )
    return rows


@dataclass
class DetectResult:
    dataset: str
    config: dict[str, Any]
    split_sizes: dict[str, dict[str, int]]
    hpo: dict[str, Any]
    threshold: float
    models: list[dict[str, Any]] = field(default_factory=list)
    seeds: dict[str, Any] = field(default_factory=dict)
    per_typology: list[dict[str, Any]] = field(default_factory=list)
    ablation: list[dict[str, Any]] = field(default_factory=list)
    imbalance: list[dict[str, Any]] = field(default_factory=list)
    sanity: dict[str, Any] = field(default_factory=dict)
    typology_head: dict[str, Any] = field(default_factory=dict)
    shap_global: list[dict[str, Any]] = field(default_factory=list)
    latency: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)
    timings: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class _Timer:
    def __init__(self, sink: dict[str, float]) -> None:
        self.sink = sink

    def __call__(self, name: str) -> _Timer:
        self.name = name
        return self

    def __enter__(self) -> None:
        self.started = time.perf_counter()

    def __exit__(self, *_: object) -> None:
        self.sink[self.name] = round(time.perf_counter() - self.started, 2)


def run_detect(dataset: Dataset, cfg: DetectConfig | None = None) -> DetectResult:  # noqa: PLR0915
    cfg = cfg or DetectConfig()
    timings: dict[str, float] = {}
    timer = _Timer(timings)
    frame = load_frame(dataset)
    train, hpo = frame[frame["split"] == "train"], frame[frame["split"] == "hpo"]
    test = frame[frame["split"] == "test"]
    if not train["is_laundering"].any() or not hpo["is_laundering"].any():
        msg = "train and hpo splits both need laundering examples"
        raise PipelineError(msg)
    y_test = test["is_laundering"].to_numpy()
    blocks = time_blocks(test["minute"].to_numpy(), cfg.block_minutes)
    tails = tail_days(dataset)
    tail_mask = test["ts"].dt.strftime("%Y-%m-%d").isin(tails).to_numpy()

    with timer("hpo"):
        tuned = tune(train, hpo, cfg)
    params = tuned["params"]

    def fit_eval(
        name: str,
        features: list[str],
        fit_params: dict[str, Any],
        seed: int = 0,
        rate: float | None = None,
    ) -> tuple[dict[str, Any], lgb.Booster, FloatArray, float]:
        sub = subsample(train, cfg.negative_rate if rate is None else rate, seed)
        booster = fit(sub, hpo, features, fit_params, cfg, seed)
        threshold, _ = best_f1_threshold(
            hpo["is_laundering"].to_numpy(), score(booster, hpo, features)
        )
        test_scores = score(booster, test, features)
        result = evaluate(name, y_test, test_scores, threshold, blocks, tail_mask, cfg)
        result["features"] = len(features)
        result["best_iteration"] = int(booster.best_iteration)
        return result, booster, test_scores, threshold

    result = DetectResult(
        dataset=dataset.name,
        config=asdict(cfg),
        split_sizes={
            n: {
                "rows": int((frame["split"] == n).sum()),
                "laundering": int(frame.loc[frame["split"] == n, "is_laundering"].sum()),
            }
            for n in ("train", "hpo", "calib", "test")
        },
        hpo=tuned,
        threshold=0.0,
    )

    with timer("models"):
        rules_test, rules_info = rules_score(test, train)
        rules_hpo, _ = rules_score(hpo, train)
        rule_threshold = max(1.0, best_f1_threshold(hpo["is_laundering"].to_numpy(), rules_hpo)[0])
        incumbent = evaluate(
            "rules_incumbent", y_test, rules_test, rule_threshold, blocks, tail_mask, cfg
        )
        incumbent["rules"] = rules_info
        tabular, _, _, _ = fit_eval("lgbm_transaction_only", TRANSACTION, params)
        champion, booster, champ_scores, threshold = fit_eval("lgbm_champion", ALL_FEATURES, params)
        result.models = [incumbent, tabular, champion]
        result.threshold = threshold

    champ_pred = champ_scores >= threshold
    result.per_typology = per_typology_recall(test, champ_pred)

    with timer("seeds"):
        runs = [champion] + [
            fit_eval("lgbm_champion", ALL_FEATURES, params, seed=s)[0] for s in cfg.seeds[1:]
        ]
        f1s = np.array([r["test"]["f1"]["value"] for r in runs])
        aps = np.array([r["test"]["pr_auc"]["value"] for r in runs])
        result.seeds = {
            "seeds": list(cfg.seeds),
            "f1": f1s.round(6).tolist(),
            "f1_mean": round(float(f1s.mean()), 6),
            "f1_std": round(float(f1s.std(ddof=1)), 6) if len(f1s) > 1 else 0.0,
            "pr_auc": aps.round(6).tolist(),
            "pr_auc_mean": round(float(aps.mean()), 6),
        }

    with timer("ablation"):
        for group, cols in FEATURE_GROUPS.items():
            kept = [f for f in ALL_FEATURES if f not in cols]
            res, _, scores_wo, _ = fit_eval(f"without_{group}", kept, params)
            pred_wo = scores_wo >= res["test"]["threshold"]
            delta = bootstrap_paired_delta_f1(y_test, champ_pred, pred_wo, blocks, cfg.n_boot)
            result.ablation.append(
                {
                    "removed_group": group,
                    "removed_features": len(cols),
                    "f1": res["test"]["f1"],
                    "champion_minus_this": delta.to_dict(),
                }
            )

    with timer("imbalance"):
        neg, pos = (~train["is_laundering"]).sum(), train["is_laundering"].sum()
        variants = [
            ("subsample_negatives_20pct (default)", params, None),
            ("all_data_scale_pos_weight", {**params, "scale_pos_weight": float(neg / pos)}, 1.0),
            ("all_data_unweighted", params, 1.0),
        ]
        for name, p, rate in variants:
            res = champion if rate is None else fit_eval(name, ALL_FEATURES, p, rate=rate)[0]
            result.imbalance.append(
                {"variant": name, "f1": res["test"]["f1"], "pr_auc": res["test"]["pr_auc"]}
            )

    with timer("sanity"):
        rng = np.random.default_rng(0)
        shuffled = train.copy()
        shuffled["is_laundering"] = rng.permutation(shuffled["is_laundering"].to_numpy())
        sub = subsample(shuffled, cfg.negative_rate, 0)
        b = fit(sub, hpo, ALL_FEATURES, params, cfg, 0)
        from verita.ml.evaluation import pr_auc  # noqa: PLC0415 - local to keep imports tidy

        result.sanity["label_shuffle"] = {
            "test_pr_auc": round(pr_auc(y_test, score(b, test, ALL_FEATURES)), 6),
            "base_rate": round(float(y_test.mean()), 6),
            "interpretation": "with shuffled labels PR-AUC should collapse to about the base rate",
        }
        result.sanity["random_split"] = _random_split_check(frame, params, cfg)

    with timer("typology_head"):
        result.typology_head, typology_booster = _typology_head(train, hpo, test, cfg)

    with timer("shap"):
        sample = test.sample(min(cfg.shap_rows, len(test)), random_state=0)
        contrib = booster.predict(
            sample[ALL_FEATURES], pred_contrib=True, num_iteration=booster.best_iteration
        )
        mean_abs = np.abs(np.asarray(contrib)[:, :-1]).mean(axis=0)
        order = np.argsort(-mean_abs)
        result.shap_global = [
            {"feature": ALL_FEATURES[i], "mean_abs_shap": round(float(mean_abs[i]), 6)}
            for i in order
        ]

    with timer("latency"):
        rows = test[ALL_FEATURES].head(10_000)
        runs_ms = []
        for _ in range(5):
            started = time.perf_counter()
            booster.predict(rows, num_iteration=booster.best_iteration)
            runs_ms.append((time.perf_counter() - started) * 1000)
        result.latency = {
            "rows": len(rows),
            "median_ms": round(float(np.median(runs_ms)), 2),
            "per_10k_rows_ms": round(float(np.median(runs_ms)) * 10_000 / max(len(rows), 1), 2),
        }

    with timer("artifacts"):
        result.artifacts = _save(dataset, booster, typology_booster, frame, threshold, params)
    result.timings = timings
    out = dataset.artifacts_dir / "detect" / "metrics.json"
    out.write_text(json.dumps(result.to_dict(), indent=2, default=str) + "\n", encoding="utf-8")
    return result


def _random_split_check(
    frame: pd.DataFrame, params: dict[str, Any], cfg: DetectConfig
) -> dict[str, Any]:
    """Same model on a *random* 60/20/20 split: shows how much a random split flatters F1."""
    rng = np.random.default_rng(0)
    draw = rng.random(len(frame))
    tr, va, te = frame[draw < 0.6], frame[(draw >= 0.6) & (draw < 0.8)], frame[draw >= 0.8]  # noqa: PLR2004
    b = fit(subsample(tr, cfg.negative_rate, 0), va, ALL_FEATURES, params, cfg, 0)
    thr, _ = best_f1_threshold(va["is_laundering"].to_numpy(), score(b, va, ALL_FEATURES))
    y = te["is_laundering"].to_numpy()
    tp, fp, fn = confusion(y, score(b, te, ALL_FEATURES) >= thr)
    f1 = 2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) else 0.0
    return {
        "random_split_test_f1": round(f1, 6),
        "interpretation": "compare with the temporal test F1; the gap is the optimism a "
        "random split would have reported",
    }


def _typology_head(
    train: pd.DataFrame, hpo: pd.DataFrame, test: pd.DataFrame, cfg: DetectConfig
) -> tuple[dict[str, Any], lgb.Booster]:
    classes = {name: i for i, name in enumerate(TYPOLOGY_CLASSES)}

    def xy(part: pd.DataFrame) -> tuple[pd.DataFrame, npt.NDArray[np.int64]]:
        pos = part[part["is_laundering"]]
        labels = np.asarray(pos["typology"].map(classes), dtype=np.int64)
        return pos[ALL_FEATURES], labels

    x_tr, y_tr = xy(train)
    x_va, y_va = xy(hpo)
    x_te, y_te = xy(test)
    params = {
        **BASE_PARAMS,
        "objective": "multiclass",
        "num_class": len(classes),
        "num_leaves": 15,
        "min_data_in_leaf": 5,
        "metric": "multi_logloss",
        "seed": 0,
    }
    dtrain = lgb.Dataset(x_tr, y_tr, categorical_feature=CATEGORICAL)
    dvalid = lgb.Dataset(x_va, y_va, reference=dtrain, categorical_feature=CATEGORICAL)
    booster = lgb.train(
        params,
        dtrain,
        num_boost_round=cfg.max_rounds,
        valid_sets=[dvalid],
        callbacks=[lgb.early_stopping(cfg.early_stopping, verbose=False)],
    )
    pred = np.asarray(booster.predict(x_te, num_iteration=booster.best_iteration)).argmax(1)
    per_class = []
    for name, idx in classes.items():
        support = int((y_te == idx).sum())
        tp = int(((pred == idx) & (y_te == idx)).sum())
        predicted = int((pred == idx).sum())
        precision = tp / predicted if predicted else 0.0
        recall = tp / support if support else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class.append(
            {
                "typology": name,
                "support": support,
                "precision": round(precision, 4),
                "recall": round(recall, 4),
                "f1": round(f1, 4),
            }
        )
    present = [c for c in per_class if c["support"]]
    macro = float(np.mean([c["f1"] for c in present])) if present else 0.0
    majority = float(np.bincount(y_te).max() / len(y_te)) if len(y_te) else 0.0
    return {
        "test_positives": len(y_te),
        "accuracy": round(float((pred == y_te).mean()) if len(y_te) else 0.0, 4),
        "majority_class_accuracy": round(majority, 4),
        "macro_f1": round(macro, 4),
        "per_class": per_class,
        "note": "evaluated on true laundering transactions only; routing aid, not a detector",
    }, booster


def _save(
    dataset: Dataset,
    booster: lgb.Booster,
    typology: lgb.Booster,
    frame: pd.DataFrame,
    threshold: float,
    params: dict[str, Any],
) -> dict[str, str]:
    out = dataset.artifacts_dir / "detect"
    out.mkdir(parents=True, exist_ok=True)
    champion_path, typology_path = out / "champion.txt", out / "typology.txt"
    booster.save_model(str(champion_path), num_iteration=booster.best_iteration)
    typology.save_model(str(typology_path), num_iteration=typology.best_iteration)
    scores = frame[["txn_id", "seq", "split"]].copy()
    scores["score"] = score(booster, frame, ALL_FEATURES)
    probs = np.asarray(typology.predict(frame[ALL_FEATURES], num_iteration=typology.best_iteration))
    scores["typology_pred"] = np.array(TYPOLOGY_CLASSES)[probs.argmax(1)]
    scores["typology_conf"] = probs.max(1)
    scores_path = dataset.processed_dir / "scores.parquet"
    scores.to_parquet(scores_path, index=False, compression="zstd")
    registry = {
        "model": "lgbm_champion",
        "features": ALL_FEATURES,
        "params": {**BASE_PARAMS, **params},
        "threshold": threshold,
        "champion_sha256": sha256_file(champion_path),
        "typology_sha256": sha256_file(typology_path),
        "features_sha256": sha256_file(dataset.features_parquet),
        "scores_sha256": sha256_file(scores_path),
    }
    registry_path = out / "registry.json"
    registry_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    return {
        "champion": _rel(champion_path),
        "typology": _rel(typology_path),
        "scores": _rel(scores_path),
        "registry": _rel(registry_path),
    }


def _rel(path: Path) -> str:
    return path.as_posix()


def score_count(dataset: Dataset) -> int:
    row = duckdb.sql(
        f"SELECT count(*) FROM read_parquet('{dataset.processed_dir / 'scores.parquet'}')"
    ).fetchone()
    return int(row[0]) if row else 0
