"""Model validation report (model risk management): policy gates evaluated on the artifacts.

The report is what an independent validator reads before approving a detector, and what the
API stores (with its SHA-256) on the model version. Every figure comes from a file the pipeline
already wrote and the Evidence Room already shows, so the report can be regenerated and checked.
Gates and thresholds live in ``configs/model_policy.yaml``, owned by model risk.

The report refuses to validate artifacts that are not the model's: the champion file on disk
must hash to the version's ``champion_sha256``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from verita.defend.canonical import canonicalize
from verita.pipeline.config import CONFIG_DIR, Dataset

POLICY_PATH = CONFIG_DIR / "model_policy.yaml"
REPORT_VERSION = 1


class ValidationError(RuntimeError):
    """The report cannot be produced (missing artifacts, or artifacts of another model)."""


@dataclass(frozen=True)
class Gate:
    name: str
    passed: bool
    value: float | bool | None
    limit: float | bool
    rule: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate": self.name,
            "passed": self.passed,
            "value": self.value,
            "limit": self.limit,
            "rule": self.rule,
        }


REQUIRED_GATES = frozenset(
    {
        "min_f1_ci_low",
        "beats_incumbent",
        "max_f1_std_over_seeds",
        "max_ece_after_calibration",
        "max_shuffled_pr_auc_over_base_rate",
        "max_major_drift_share",
        "min_rows_for_drift",
        "min_typology_support_reported",
    }
)


def check_policy(policy: Any, source: str = "policy") -> dict[str, Any]:
    """A policy missing a gate is refused outright, never half-applied."""
    if not isinstance(policy, dict) or not isinstance(policy.get("gates"), dict):
        raise ValidationError(f"{source} is not a model policy (no `gates`)")
    missing = sorted(REQUIRED_GATES - set(policy["gates"]))
    if missing:
        raise ValidationError(f"{source} is missing gates: {', '.join(missing)}")
    return policy


def load_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    return check_policy(yaml.safe_load(path.read_text(encoding="utf-8")), str(path))


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValidationError(f"missing artifact: {path.name} (run the pipeline first)")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValidationError(f"{path.name} is not a JSON object")
    return data


def _model(metrics: dict[str, Any], name: str) -> dict[str, Any]:
    for m in metrics.get("models", []):
        if m.get("model") == name:
            test = m.get("test")
            if isinstance(test, dict):
                return test
    raise ValidationError(f"metrics.json has no test results for {name}")


def report_sha256(report: dict[str, Any]) -> str:
    return hashlib.sha256(canonicalize(report)).hexdigest()


def build_report(dataset: Dataset, champion_sha256: str, policy: dict[str, Any]) -> dict[str, Any]:
    """Evaluate every gate for the model whose champion file hashes to CHAMPION_SHA256."""
    detect = dataset.artifacts_dir / "detect"
    decide = dataset.artifacts_dir / "decide"
    registry = _read(detect / "registry.json")
    if registry.get("champion_sha256") != champion_sha256:
        raise ValidationError(
            "the detect artifacts on disk belong to a different model "
            f"({str(registry.get('champion_sha256'))[:12]}…); re-run the pipeline for this one"
        )
    metrics = _read(detect / "metrics.json")
    calibration = _read(decide / "calibration.json")
    drift = _read(decide / "drift.json")
    g = check_policy(policy)["gates"]

    champion = _model(metrics, "lgbm_champion")
    incumbent = _model(metrics, "rules_incumbent")
    f1, inc_f1 = champion["f1"], incumbent["f1"]
    seeds = metrics.get("seeds", {})
    shuffle = metrics.get("sanity", {}).get("label_shuffle", {})
    base_rate = float(shuffle.get("base_rate") or champion.get("base_rate") or 0.0)
    shuffled = float(shuffle.get("test_pr_auc", 0.0))
    shuffle_ratio = shuffled / base_rate if base_rate else None
    ece = float(calibration.get("after", {}).get("ece", 1.0))

    floor = int(g["min_rows_for_drift"])
    days = drift.get("by_day", [])
    assessed = [d for d in days if int(d.get("rows", 0)) >= floor]
    below_floor = [{"day": d.get("day"), "rows": d.get("rows")} for d in days if d not in assessed]
    major = sorted(
        {
            f["feature"]
            for day in assessed
            for f in day.get("features", [])
            if f.get("severity") == "major"
        }
    )
    checked = max(len(drift.get("features_checked", []) or []), 1)
    major_share = len(major) / checked if assessed else None

    support_floor = int(g["min_typology_support_reported"])
    typologies = metrics.get("per_typology", [])
    unreported = [
        t["typology"]
        for t in typologies
        if t.get("support", 0) >= support_floor and not isinstance(t.get("recall"), dict)
    ]

    gates = [
        Gate(
            "f1_ci_low",
            f1["low"] >= g["min_f1_ci_low"],
            f1["low"],
            g["min_f1_ci_low"],
            "lower bound of the test-split F1 95% interval ≥ limit",
        ),
        Gate(
            "beats_incumbent",
            (f1["low"] > inc_f1["high"]) or not g["beats_incumbent"],
            f1["low"] > inc_f1["high"],
            g["beats_incumbent"],
            "champion F1 interval lies entirely above the rules incumbent's",
        ),
        Gate(
            "seed_stability",
            float(seeds.get("f1_std", 1.0)) <= g["max_f1_std_over_seeds"],
            seeds.get("f1_std"),
            g["max_f1_std_over_seeds"],
            "standard deviation of test F1 across training seeds ≤ limit",
        ),
        Gate(
            "calibration",
            ece <= g["max_ece_after_calibration"],
            ece,
            g["max_ece_after_calibration"],
            "expected calibration error after isotonic, held-out split ≤ limit",
        ),
        Gate(
            "leakage_label_shuffle",
            shuffle_ratio is not None and shuffle_ratio <= g["max_shuffled_pr_auc_over_base_rate"],
            None if shuffle_ratio is None else round(shuffle_ratio, 3),
            g["max_shuffled_pr_auc_over_base_rate"],
            "with shuffled labels, test PR-AUC ÷ base rate ≤ limit (no learnable leakage)",
        ),
        Gate(
            "drift",
            major_share is not None and major_share <= g["max_major_drift_share"],
            None if major_share is None else round(major_share, 3),
            g["max_major_drift_share"],
            f"share of monitored features with major PSI drift on any day of ≥ {floor} rows "
            "≤ limit (no assessable day fails the gate)",
        ),
        Gate(
            "typology_coverage",
            not unreported,
            len(unreported),
            0,
            f"every typology with ≥ {support_floor} test positives has recall measured",
        ),
    ]
    return {
        "report_version": REPORT_VERSION,
        "policy_version": policy.get("version"),
        "dataset": dataset.name,
        "champion_sha256": champion_sha256,
        "passed": all(gate.passed for gate in gates),
        "gates": [gate.to_dict() for gate in gates],
        "performance": {
            "champion_f1": f1,
            "champion_pr_auc": champion.get("pr_auc"),
            "incumbent_f1": inc_f1,
            "test_positives": champion.get("positives"),
            "threshold": champion.get("threshold"),
        },
        "per_typology": [
            {"typology": t["typology"], "support": t.get("support"), "recall": t.get("recall")}
            for t in typologies
        ],
        "drift": {
            "days_assessed": [d.get("day") for d in assessed],
            "days_below_volume_floor": below_floor,
            "major_drift_features": major,
        },
        "limitations": [
            "Trained and evaluated on synthetic data (IBM AML); says nothing about real banks.",
            "Detection gates measure the test split only; they do not replace ongoing monitoring.",
        ],
    }


def render_markdown(report: dict[str, Any], model_name: str) -> str:
    verdict = "PASSED" if report["passed"] else "FAILED"
    lines = [
        f"# Validation report: {model_name} ({report['dataset']})",
        "",
        f"Policy version {report['policy_version']} · champion `{report['champion_sha256'][:12]}` "
        f"· **{verdict}**",
        "",
        "| Gate | Result | Value | Limit | Rule |",
        "|---|---|---|---|---|",
    ]
    for gate in report["gates"]:
        mark = "pass" if gate["passed"] else "**fail**"
        lines.append(
            f"| {gate['gate']} | {mark} | {gate['value']} | {gate['limit']} | {gate['rule']} |"
        )
    drift = report.get("drift", {})
    if drift:
        lines += [
            "",
            "## Drift",
            f"Days assessed: {', '.join(drift['days_assessed']) or 'none'}.",
            "Features with major drift: "
            + (", ".join(f"`{f}`" for f in drift["major_drift_features"]) or "none")
            + ".",
            "Days below the volume floor (reported, not gated): "
            + (
                ", ".join(
                    f"{d['day']} ({d['rows']} rows)" for d in drift["days_below_volume_floor"]
                )
                or "none"
            )
            + ".",
        ]
    lines += ["", "## Limitations", *[f"- {item}" for item in report["limitations"]], ""]
    return "\n".join(lines)
