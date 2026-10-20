"""``reports/metrics.json``: the single source of every number Verita shows (PIVOT §15).

Built from the run artifacts — nothing is computed or typed here, only gathered, trimmed and
labelled. Each dataset section mirrors the Evidence Room tabs (data, detect, decide, defend,
lineage); ``headline`` lists the figures that appear in prose (README, landing page), each with
its interval, sample size, split and the artifact it came from.

The file is committed for the demo: docs and UI read it, and CI regenerates the docs from it
and fails if a committed copy drifts.
"""

from __future__ import annotations

import json
import subprocess  # nosec B404 - fixed git invocation
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from verita.pipeline.config import CONFIG_DIR, REPO_ROOT, Dataset, get_dataset, load_yaml

SCHEMA_VERSION = 1
REPORTS_DIR = REPO_ROOT / "reports"
DATASET_LABELS = {
    "hi_small": "IBM AML HI-Small (synthetic)",
    "li_small": "IBM AML LI-Small (synthetic)",
}


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def git_sha() -> str:
    try:
        out = subprocess.run(  # nosec B603 B607 - fixed argv, git from PATH, build machine only
            ["git", "rev-parse", "--short=12", "HEAD"],  # noqa: S607
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return out.stdout.strip()


def _model(models: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    return next((m for m in models if m["model"] == name), None)


def _data(ds: Dataset) -> dict[str, Any] | None:
    validation = _read(ds.validation_json)
    splits = _read(ds.splits_json)
    if validation is None or splits is None:
        return None
    contract = validation["contract"]
    return {
        "source": contract["source"],
        "rows": contract["rows"],
        "laundering": contract["laundering"],
        "laundering_rate": round(contract["laundering"] / contract["rows"], 6),
        "time_span": {"from": contract["ts_min"], "to": contract["ts_max"]},
        "contract_passed": contract["passed"],
        "violations": contract["violations"],
        "facts": contract["facts"],
        "graph": validation["graph"],
        "patterns": {
            k: validation["patterns"][k]
            for k in ("attempts", "coverage", "laundering_attributed", "laundering_unattributed")
        },
        "patterns_by_typology": validation["patterns"]["by_typology"],
        "sparse_tail_days": validation["daily_volume"]["sparse_tail_days"],
        "splits": {
            "method": splits["method"],
            "fractions": splits["fractions"],
            **splits["summary"],
        },
        "files": [
            {"name": f["name"], "sha256": f["actual_sha256"], "ok": f["ok"]}
            for f in validation["files"]
        ],
    }


def _detect(ds: Dataset, baselines: dict[str, Any]) -> dict[str, Any] | None:
    m = _read(ds.artifacts_dir / "detect" / "metrics.json")
    if m is None:
        return None

    def summary(row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        out = {}
        for part in ("test", "test_bulk", "test_tail"):
            t = row.get(part)
            if t:
                out[part] = {
                    k: t[k]
                    for k in (
                        "f1",
                        "pr_auc",
                        "precision",
                        "recall",
                        "positives",
                        "rows",
                        "base_rate",
                    )
                    if k in t
                }
        return out

    registry = _read(ds.artifacts_dir / "detect" / "registry.json") or {}
    incumbent: dict[str, Any] = next(
        (r for r in m["models"] if r["model"] == "rules_incumbent"), {}
    )
    hits = {h["rule"]: h for h in incumbent.get("rule_hits_test", [])}
    rules = incumbent.get("rules")
    return {
        "rules": None
        if not isinstance(rules, dict)
        else {
            "tuned_on": rules["tuned_on"],
            "rules": [
                {
                    **r,
                    "test_alerts": hits.get(r["rule"], {}).get("alerts"),
                    "test_laundering": hits.get(r["rule"], {}).get("laundering"),
                }
                for r in rules["rules"]
            ],
        },
        "n_features": len(registry.get("features", [])),
        "threshold": m["threshold"],
        "hpo": m["hpo"],
        "models": {r["model"]: summary(r) for r in m["models"]},
        "seeds": m["seeds"],
        "per_typology": m["per_typology"],
        "ablation": [
            {"removed_group": a["removed_group"], "f1": a["f1"], "delta": a["champion_minus_this"]}
            for a in m["ablation"]
        ],
        "imbalance": m["imbalance"],
        "sanity": m["sanity"],
        "typology_head": {
            k: m["typology_head"][k] for k in ("accuracy", "majority_class_accuracy", "macro_f1")
        },
        "shap_top": m["shap_global"][:10],
        "latency": m["latency"],
        "published_baselines": {
            "source": baselines["source"],
            "metric": baselines["metric"],
            "rows": baselines["datasets"].get(ds.name, {}),
        },
    }


def _decide(ds: Dataset) -> dict[str, Any] | None:
    root = ds.artifacts_dir / "decide"
    calibration = _read(root / "calibration.json")
    coverage = _read(root / "coverage.json")
    if calibration is None or coverage is None:
        return None
    forecast = _read(root / "forecast.json") or {}
    thresholds = _read(root / "thresholds.json") or {}
    drift = _read(root / "drift.json") or {}
    runs = {}
    for alpha, by_run in coverage["by_alpha"].items():
        runs[alpha] = {
            name: {
                "overall": {k: v for k, v in r["overall"].items() if k != "alpha_trace"},
                "by_day": r["by_day"],
            }
            for name, r in by_run.items()
        }
    frontier = _read(root / "frontier.json") or {}
    gaps = [
        p["optimality_gap"]
        for days in frontier.values()
        for points in days.values()
        for p in points
        if "optimality_gap" in p
    ]
    return {
        "calibration": calibration,
        "coverage": {
            "by_alpha": runs,
            "label_delay_sensitivity": coverage["label_delay_sensitivity"],
            "gamma": coverage["gamma"],
            "tail_days": coverage["tail_days"],
        },
        "thresholds": thresholds,
        "forecast": {
            k: forecast.get(k)
            for k in ("origins", "horizon_hours", "step_hours", "models", "workload_definition")
        },
        "drift": {
            "excluded_time_anchored": drift.get("excluded_time_anchored", []),
            "by_day": [
                {k: d[k] for k in ("day", "rows", "max_psi", "recalibrate")}
                | {"top": d["features"][0]["feature"] if d["features"] else None}
                for d in drift.get("by_day", [])
            ],
        },
        "frontier_greedy_points": len(gaps),
        "staffing": _staffing(frontier),
        "bench": _read(ds.artifacts_dir / "bench.json"),
    }


def _staffing(frontier: dict[str, Any]) -> dict[str, Any] | None:
    """Analysts each replay day needs for the default 95% guarantee (pooled, cases)."""
    days = frontier.get("0.05|pooled|cases")
    if not days:
        return None
    needed = {day: pts[0]["guarantee"]["analysts_needed"] for day, pts in sorted(days.items())}
    return {"alpha": 0.05, "by_day": needed, "max_analysts_needed": max(needed.values())}


def _defend(ds: Dataset) -> dict[str, Any] | None:
    ev = _read(ds.artifacts_dir / "defend" / "verifier_eval.json")
    if ev is None:
        return None
    return {k: ev[k] for k in ev if k != "seconds"}


def _governance(ds: Dataset) -> dict[str, Any] | None:
    """The newest model-risk validation (``verita models validate``) and the model's state."""
    record = _read(ds.artifacts_dir / "models" / "validation.json")
    if record is None:
        return None
    report = record.get("report", {})
    return {
        "model_version_id": record.get("model_version_id"),
        "model": record.get("model"),
        "status": record.get("status"),
        "governance": record.get("governance"),
        "sha256": record.get("sha256"),
        "passed": report.get("passed"),
        "policy_version": report.get("policy_version"),
        "gates": report.get("gates", []),
        "drift": report.get("drift", {}),
    }


def _lineage(ds: Dataset) -> list[dict[str, Any]]:
    out = []
    for path in sorted(ds.manifests_dir.glob("*.json")) if ds.manifests_dir.exists() else []:
        m = _read(path)
        out.append(
            {
                "stage": path.stem,
                "git_revision": m.get("git_revision"),
                "config_hash": m.get("config_hash"),
                "duration_s": m.get("duration_s"),
                "started_at": m.get("started_at"),
                "inputs": m.get("inputs", {}),
                "outputs": m.get("outputs", {}),
            }
        )
    return out


def _headline(name: str, sec: dict[str, Any]) -> list[dict[str, Any]]:
    """The figures that appear in prose, each traceable to its source."""
    out: list[dict[str, Any]] = []
    label = DATASET_LABELS.get(name, name)

    def add(key: str, text: str, value: Any, source: str, split: str, **extra: Any) -> None:
        if isinstance(value, dict):
            out.append(
                {
                    "key": key,
                    "label": text,
                    "dataset": label,
                    "split": split,
                    "source": source,
                    **value,
                    **extra,
                }
            )
        elif value is not None:
            out.append(
                {
                    "key": key,
                    "label": text,
                    "dataset": label,
                    "split": split,
                    "source": source,
                    "value": value,
                    **extra,
                }
            )

    detect = sec.get("detect")
    if detect:
        champ = (detect["models"].get("lgbm_champion") or {}).get("test", {})
        rules = (detect["models"].get("rules_incumbent") or {}).get("test", {})
        add(
            "detect.f1",
            "Laundering F1 (champion)",
            champ.get("f1"),
            "artifacts/detect/metrics.json",
            "test",
            n=champ.get("positives"),
        )
        add(
            "detect.pr_auc",
            "PR-AUC (champion)",
            champ.get("pr_auc"),
            "artifacts/detect/metrics.json",
            "test",
        )
        add(
            "detect.rules_f1",
            "Laundering F1 (rules incumbent)",
            rules.get("f1"),
            "artifacts/detect/metrics.json",
            "test",
        )
        add(
            "detect.seed_std",
            "F1 standard deviation over seeds",
            detect["seeds"].get("f1_std"),
            "artifacts/detect/metrics.json",
            "test",
        )
        published = detect["published_baselines"]["rows"].get("GFP + LightGBM")
        if published:
            add(
                "detect.paper_gfp_lgbm",
                "Published GFP + LightGBM F1 (%)",
                published["mean"],
                detect["published_baselines"]["source"],
                "test",
            )
    decide = sec.get("decide")
    if decide:
        runs = decide["coverage"]["by_alpha"].get("0.05", {})
        for run, text in (
            ("static_pooled", "static conformal"),
            ("aci_pooled", "adaptive conformal (ACI)"),
        ):
            if run in runs:
                o = runs[run]["overall"]
                add(
                    f"decide.recall_{run}",
                    f"Realised recall at a 95% guarantee, {text}",
                    o["recall"],
                    "artifacts/decide/coverage.json",
                    "test",
                    n=o["positives"],
                    reviewed=o["reviewed"],
                )
        cal = decide["calibration"]
        add(
            "decide.ece_after",
            "Expected calibration error after isotonic",
            cal["after"]["ece"],
            "artifacts/decide/calibration.json",
            "test",
        )
        add(
            "decide.ece_before",
            "Expected calibration error before calibration",
            cal["before"]["ece"],
            "artifacts/decide/calibration.json",
            "test",
        )
    defend = sec.get("defend")
    if defend:
        add(
            "defend.detection",
            "Planted narrative faults caught by the verifier",
            defend["overall_detection"],
            "artifacts/defend/verifier_eval.json",
            "test",
        )
        add(
            "defend.false_alarm",
            "Clean narratives wrongly rejected",
            defend["clean_false_alarm"],
            "artifacts/defend/verifier_eval.json",
            "test",
        )
    bench = (decide or {}).get("bench") or {}
    if bench.get("subgraph"):
        add(
            "perf.subgraph_p95_ms",
            "Evidence subgraph latency p95 (ms)",
            bench["subgraph"]["p95_ms"],
            "artifacts/bench.json",
            "test",
            n=bench["subgraph"]["n"],
        )
    return out


def _perf(root: Path) -> dict[str, Any]:
    """k6 results (perf/results/*.json, written by `k6 run --summary-export`)."""
    out: dict[str, Any] = {}
    for path in sorted((root / "perf" / "results").glob("*.json")):
        m = _read(path)["metrics"]
        out[path.stem] = {
            "requests_per_second": round(m["http_reqs"]["rate"], 1),
            "p95_ms": round(m["http_req_duration"]["p(95)"], 1),
            "p50_ms": round(m["http_req_duration"]["med"], 1),
            "error_rate": m["http_req_failed"]["value"],
            "requests": m["http_reqs"]["count"],
        }
    return out


def build(
    root: Path = REPO_ROOT, datasets: tuple[str, ...] = ("hi_small", "li_small")
) -> dict[str, Any]:
    baselines = load_yaml(CONFIG_DIR / "baselines.yaml")
    sections: dict[str, Any] = {}
    headline: list[dict[str, Any]] = []
    for name in datasets:
        ds = get_dataset(name, root=root)
        sec = {
            "label": DATASET_LABELS.get(name, name),
            "data": _data(ds),
            "detect": _detect(ds, baselines),
            "decide": _decide(ds),
            "defend": _defend(ds),
            "governance": _governance(ds),
            "lineage": _lineage(ds),
        }
        if sec["data"] is None:
            continue
        sections[name] = sec
        headline += _headline(name, sec)
    return {
        "perf": _perf(root),
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "git_sha": git_sha(),
        "synthetic_data_notice": (
            "All results are on synthetic data (IBM AML, Altman et al. 2023). They do not "
            "establish performance on real bank data."
        ),
        "primary_dataset": "hi_small",
        "headline": headline,
        "datasets": sections,
    }


def write(metrics: dict[str, Any], path: Path | None = None) -> Path:
    path = path or REPORTS_DIR / "metrics.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
