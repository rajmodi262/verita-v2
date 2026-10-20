"""Model validation gates on small, hand-built artifacts: each gate passes and fails for the
reason it claims to, and the drift gate only judges days with enough volume for PSI."""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest

from verita.ml import validation

SHA = "a" * 64
POLICY = {
    "version": 1,
    "gates": {
        "min_f1_ci_low": 0.15,
        "beats_incumbent": True,
        "max_f1_std_over_seeds": 0.03,
        "max_ece_after_calibration": 0.02,
        "max_shuffled_pr_auc_over_base_rate": 3.0,
        "max_major_drift_share": 0.25,
        "min_rows_for_drift": 1000,
        "min_typology_support_reported": 20,
    },
}


def _rate(value, low, high):
    return {"value": value, "low": low, "high": high}


def _write(root, *, champion_f1=(0.5, 0.44, 0.59), incumbent_f1=(0.01, 0.005, 0.02), days=None):
    detect = root / "detect"
    decide = root / "decide"
    detect.mkdir(parents=True)
    decide.mkdir(parents=True)
    (detect / "registry.json").write_text(json.dumps({"champion_sha256": SHA}))
    (detect / "metrics.json").write_text(
        json.dumps(
            {
                "models": [
                    {
                        "model": "lgbm_champion",
                        "test": {
                            "f1": _rate(*champion_f1),
                            "pr_auc": _rate(0.5, 0.4, 0.6),
                            "base_rate": 0.002,
                        },
                    },
                    {"model": "rules_incumbent", "test": {"f1": _rate(*incumbent_f1)}},
                ],
                "seeds": {"f1_std": 0.005},
                "sanity": {"label_shuffle": {"test_pr_auc": 0.0024, "base_rate": 0.002}},
                "per_typology": [
                    {"typology": "FAN-IN", "support": 74, "recall": _rate(0.3, 0.2, 0.4)}
                ],
            }
        )
    )
    (decide / "calibration.json").write_text(json.dumps({"after": {"ece": 0.002}}))
    features = [f"f{i}" for i in range(10)]
    (decide / "drift.json").write_text(
        json.dumps(
            {
                "features_checked": features,
                "by_day": days
                if days is not None
                else [
                    {
                        "day": "d1",
                        "rows": 50_000,
                        "features": [{"feature": "f0", "severity": "major"}],
                    }
                ],
            }
        )
    )
    return SimpleNamespace(name="ds", artifacts_dir=root)


def _gates(report):
    return {g["gate"]: g for g in report["gates"]}


def test_a_good_model_passes_every_gate(tmp_path):
    report = validation.build_report(_write(tmp_path), SHA, POLICY)
    assert report["passed"], [g for g in report["gates"] if not g["passed"]]
    assert len(validation.report_sha256(report)) == 64


def test_weak_or_unproven_models_fail_the_right_gates(tmp_path):
    ds = _write(tmp_path, champion_f1=(0.2, 0.1, 0.3), incumbent_f1=(0.15, 0.12, 0.18))
    gates = _gates(validation.build_report(ds, SHA, POLICY))
    assert not gates["f1_ci_low"]["passed"]  # lower bound 0.10 < 0.15
    assert not gates["beats_incumbent"]["passed"]  # 0.10 is not above the incumbent's 0.18


def test_drift_ignores_low_volume_days_but_lists_them(tmp_path):
    days = [
        {"day": "bulk", "rows": 200_000, "features": [{"feature": "f0", "severity": "moderate"}]},
        {
            "day": "tail",
            "rows": 40,
            "features": [{"feature": f"f{i}", "severity": "major"} for i in range(10)],
        },
    ]
    report = validation.build_report(_write(tmp_path, days=days), SHA, POLICY)
    drift = _gates(report)["drift"]
    assert drift["passed"] and drift["value"] == 0.0
    assert report["drift"]["days_below_volume_floor"] == [{"day": "tail", "rows": 40}]


def test_drift_fails_when_bulk_days_drift_or_nothing_is_assessable(tmp_path):
    days = [
        {
            "day": "bulk",
            "rows": 200_000,
            "features": [{"feature": f"f{i}", "severity": "major"} for i in range(4)],
        }
    ]
    gates = _gates(validation.build_report(_write(tmp_path / "a", days=days), SHA, POLICY))
    assert not gates["drift"]["passed"] and gates["drift"]["value"] == 0.4
    tail_only = [{"day": "tail", "rows": 10, "features": []}]
    gates = _gates(validation.build_report(_write(tmp_path / "b", days=tail_only), SHA, POLICY))
    assert not gates["drift"]["passed"] and gates["drift"]["value"] is None


def test_leakage_gate_trips_when_shuffled_labels_still_predict(tmp_path):
    ds = _write(tmp_path)
    metrics = json.loads((tmp_path / "detect" / "metrics.json").read_text())
    metrics["sanity"]["label_shuffle"]["test_pr_auc"] = 0.05  # 25x the base rate: leakage
    (tmp_path / "detect" / "metrics.json").write_text(json.dumps(metrics))
    assert not _gates(validation.build_report(ds, SHA, POLICY))["leakage_label_shuffle"]["passed"]


def test_unmeasured_typologies_fail_coverage(tmp_path):
    ds = _write(tmp_path)
    metrics = json.loads((tmp_path / "detect" / "metrics.json").read_text())
    metrics["per_typology"].append({"typology": "CYCLE", "support": 30, "recall": None})
    (tmp_path / "detect" / "metrics.json").write_text(json.dumps(metrics))
    gate = _gates(validation.build_report(ds, SHA, POLICY))["typology_coverage"]
    assert not gate["passed"] and gate["value"] == 1


def test_missing_artifacts_and_bad_policies_are_errors(tmp_path):
    with pytest.raises(validation.ValidationError, match="missing artifact"):
        validation.build_report(SimpleNamespace(name="x", artifacts_dir=tmp_path), SHA, POLICY)
    bad = tmp_path / "p.yaml"
    bad.write_text("version: 1\n")
    with pytest.raises(validation.ValidationError, match="not a model policy"):
        validation.load_policy(bad)


def test_the_shipped_policy_loads_and_names_every_gate_input():
    policy = validation.load_policy()
    assert set(POLICY["gates"]) <= set(policy["gates"])
    relaxed = copy.deepcopy(policy)
    assert relaxed["duties"]["approver_role"] != relaxed["duties"]["promoter_role"]


def test_markdown_report_states_the_verdict_and_the_drift_detail(tmp_path):
    report = validation.build_report(_write(tmp_path), SHA, POLICY)
    md = validation.render_markdown(report, "lgbm")
    assert "**PASSED**" in md and "Days assessed: d1" in md and "`f0`" in md


def test_a_policy_missing_a_gate_is_refused_not_half_applied(tmp_path):
    partial = copy.deepcopy(POLICY)
    del partial["gates"]["min_rows_for_drift"]
    with pytest.raises(validation.ValidationError, match="missing gates: min_rows_for_drift"):
        validation.build_report(_write(tmp_path), SHA, partial)
