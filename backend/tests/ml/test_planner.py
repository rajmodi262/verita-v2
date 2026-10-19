"""Capacity planner: exact knapsack, guarantee constraint, infeasibility and recall interval."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from verita.optimize.planner import (
    Operations,
    _greedy,
    _knapsack_cpsat,
    candidate_pool,
    expected_recall_interval,
    frontier,
    plan_day,
    prepare,
    usd,
)

OPS = Operations(
    median_minutes=30.0,
    typology_multiplier={"FAN-OUT": 1.0, "CYCLE": 2.0, "UNKNOWN": 1.0},
    productive_hours=1.0,  # 60 minutes per analyst keeps the examples small
    analyst_hourly_rate=50.0,
    miss_cost_rate=0.1,
    min_analysts=1,
    max_analysts=3,
)


def _alerts(probs, amounts, typologies) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "id": range(1, len(probs) + 1),
            "score": probs,
            "calibrated_prob": probs,
            "top_amount": amounts,
            "top_currency": ["US Dollar"] * len(probs),
            "typology_pred": typologies,
        }
    )
    return prepare(frame, OPS)


def test_operations_load_from_repo_config():
    ops = Operations.load()
    assert ops.median_minutes > 0 and ops.min_analysts >= 1
    assert ops.minutes_for("NOT-A-TYPOLOGY") > 0


def test_usd_conversion_and_preparation():
    assert usd(100, "Euro") == pytest.approx(108)
    assert usd(5, "Unlisted") == 5
    alerts = _alerts([0.5], [1000.0], ["CYCLE"])
    assert alerts.loc[0, "minutes"] == 60.0
    assert alerts.loc[0, "expected_value"] == pytest.approx(500.0)


def test_exact_solver_beats_greedy_where_greedy_is_suboptimal():
    # capacity 10: greedy takes the best-ratio item (6 min, 7) and then nothing fits;
    # optimum is the two 5-minute items (5 + 5 = 10 value)
    values = np.array([7.0, 5.0, 5.0])
    minutes = np.array([6.0, 5.0, 5.0])
    none = np.zeros(3, dtype=bool)
    greedy = _greedy(values, minutes, 10, none)
    exact = _knapsack_cpsat(values, minutes, 10, none)
    assert values[greedy].sum() == 7.0
    assert values[exact].sum() == 10.0
    assert minutes[exact].sum() <= 10


def test_forced_alerts_are_always_selected():
    values = np.array([1.0, 100.0, 50.0])
    minutes = np.array([5.0, 5.0, 5.0])
    forced = np.array([True, False, False])
    chosen = _knapsack_cpsat(values, minutes, 10, forced)
    assert chosen[0] and chosen[1] and not chosen[2]


def test_plan_reports_gap_cost_and_recall():
    alerts = _alerts([0.9, 0.6, 0.2, 0.1], [1000, 500, 100, 50], ["FAN-OUT"] * 4)
    mask = np.array([True, False, False, False])
    plan = plan_day(alerts, 1, mask, OPS)  # 60 minutes = 2 alerts
    assert plan["reviewed"] == 2 and plan["selected"][0]
    assert plan["guarantee"]["feasible"] is True
    assert plan["optimality_gap"] >= 0
    assert plan["review_cost_usd"] == pytest.approx(50.0)
    assert 0 <= plan["expected_recall"]["low"] <= plan["expected_recall"]["high"] <= 1
    assert plan["expected_value_caught_usd"] == pytest.approx(900 + 300)


def test_infeasible_guarantee_reports_analysts_needed():
    alerts = _alerts([0.9] * 5, [100] * 5, ["CYCLE"] * 5)  # 5 x 60 minutes required
    plan = plan_day(alerts, 2, np.ones(5, dtype=bool), OPS)
    assert plan["guarantee"]["feasible"] is False
    assert plan["guarantee"]["analysts_needed"] == 5
    assert plan["reviewed"] == 2  # still uses the capacity it has, best value first


def test_frontier_is_monotone_in_analysts():
    rng = np.random.default_rng(0)
    n = 30
    alerts = _alerts(rng.random(n), rng.random(n) * 1000, ["FAN-OUT"] * n)
    rows = frontier(alerts, np.zeros(n, dtype=bool), OPS, exact=True)
    assert [r["analysts"] for r in rows] == [1, 2, 3]
    caught = [r["expected_value_caught_usd"] for r in rows]
    assert caught == sorted(caught)
    assert all("selected" not in r for r in rows)


def test_expected_recall_interval_bounds():
    probs = np.array([0.9, 0.5, 0.1])
    all_reviewed = expected_recall_interval(probs, np.ones(3, dtype=bool))
    assert all_reviewed == {"value": 1.0, "low": 1.0, "high": 1.0}
    some = expected_recall_interval(probs, np.array([True, False, False]))
    assert some["value"] == pytest.approx(0.9 / 1.5, abs=1e-6)
    assert some["low"] <= some["value"] <= some["high"]
    assert expected_recall_interval(np.array([]), np.array([], dtype=bool))["value"] == 1.0


def test_what_if_overrides_change_only_what_was_asked():
    ops, changed = OPS.with_overrides(median_minutes=45, productive_hours=None)
    assert changed == ["median_minutes"]
    assert ops.median_minutes == 45 and ops.productive_hours == OPS.productive_hours
    with pytest.raises(ValueError, match="cannot override"):
        OPS.with_overrides(miss_cost_rate=0.5)


def test_plan_names_its_solver():
    alerts = _alerts([0.9, 0.5], [100, 100], ["FAN-OUT"] * 2)
    none = np.zeros(2, dtype=bool)
    assert plan_day(alerts, 1, none, OPS)["solver"] == "cp-sat"
    assert plan_day(alerts, 1, none, OPS, solve_exact=False)["solver"] == "greedy"


def test_positives_outside_the_queue_count_against_recall():
    probs = np.array([0.5, 0.5])
    reviewed = np.ones(2, dtype=bool)
    with_outside = expected_recall_interval(probs, reviewed, outside_expected=1.0)
    assert with_outside["value"] == pytest.approx(0.5)
    assert with_outside["low"] < 0.5 < with_outside["high"]


def test_large_days_use_the_normal_approximation_with_a_sane_interval():
    rng = np.random.default_rng(2)
    probs = rng.random(20_000) * 0.01
    reviewed = probs > 0.008
    interval = expected_recall_interval(probs, reviewed)
    assert interval["low"] <= interval["value"] <= interval["high"]
    assert interval["high"] - interval["low"] < 0.2


def test_candidate_pool_keeps_forced_and_densest_alerts():
    values = np.arange(100, dtype=float)
    minutes = np.full(100, 10.0)
    forced = np.zeros(100, dtype=bool)
    forced[0] = True
    pool = candidate_pool(values, minutes, capacity=20, forced=forced)  # 2 fit -> pool of 10
    assert pool[0] and pool[90:].all() and pool.sum() == 11
    small = candidate_pool(values[:5], minutes[:5], capacity=20, forced=forced[:5])
    assert small.all()


def test_exact_plan_on_a_large_day_never_loses_to_greedy():
    rng = np.random.default_rng(5)
    n = 3000
    alerts = _alerts(rng.random(n), rng.random(n) * 1000, rng.choice(["FAN-OUT", "CYCLE"], n))
    plan = plan_day(alerts, 3, np.zeros(n, dtype=bool), OPS)
    assert plan["objective_value"] >= plan["greedy_objective_value"]
    assert plan["review_minutes"] <= plan["capacity_minutes"]


def test_objective_chooses_between_cases_and_dollars():
    # one likely small case vs one unlikely huge payment; room for one review
    alerts = _alerts([0.9, 0.05], [100.0, 1_000_000.0], ["CYCLE", "CYCLE"])
    none = np.zeros(2, dtype=bool)
    cases = plan_day(alerts, 1, none, OPS, objective="cases")
    value = plan_day(alerts, 1, none, OPS, objective="value")
    assert cases["selected"].tolist() == [True, False]
    assert value["selected"].tolist() == [False, True]
    assert cases["expected_cases_caught"] > value["expected_cases_caught"]
    assert value["value_recall"] > cases["value_recall"]
    with pytest.raises(ValueError, match="objective"):
        plan_day(alerts, 1, none, OPS, objective="vibes")


def test_frontier_backtests_against_true_labels():
    alerts = _alerts([0.9, 0.6, 0.2, 0.1], [100] * 4, ["FAN-OUT"] * 4)
    labels = np.array([True, False, True, False])
    rows = frontier(alerts, np.zeros(4, dtype=bool), OPS, labels=labels, outside_positives=2)
    one = rows[0]["realised"]  # 1 analyst = 2 reviews: the two likeliest
    assert one == {"positives": 4, "caught": 1, "recall": 0.25}
    assert "realised" not in frontier(alerts, np.zeros(4, dtype=bool), OPS)[0]


def test_exact_solver_respects_fractional_handling_times():
    # five 14.4-minute alerts fill 72 minutes exactly; rounding each up to 15 would fit only 4
    values = np.ones(6)
    minutes = np.full(6, 14.4)
    chosen = _knapsack_cpsat(values, minutes, 72.0, np.zeros(6, dtype=bool))
    assert chosen.sum() == 5
