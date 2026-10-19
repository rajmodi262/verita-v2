"""Response models for the capacity planner; they drive the frontend's generated types."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Interval(BaseModel):
    value: float
    low: float
    high: float


class Assumptions(BaseModel):
    median_minutes: float
    typology_multiplier: dict[str, float]
    productive_hours: float
    analyst_hourly_rate: float
    miss_cost_rate: float
    min_analysts: int
    max_analysts: int
    overridden: list[str] = Field(default_factory=list)


class Guarantee(BaseModel):
    required_alerts: int
    required_minutes: float
    feasible: bool
    analysts_needed: int


class Realised(BaseModel):
    """Replay-only backtest: what the plan actually caught, judged by the true labels."""

    positives: int
    caught: int
    recall: float | None


class PlanPoint(BaseModel):
    """One staffing level: what reviewing the best alerts that fit would achieve."""

    analysts: int
    objective: str
    capacity_minutes: float
    alerts: int
    reviewed: int
    review_minutes: float
    guarantee: Guarantee
    expected_recall: Interval
    expected_cases_caught: float
    expected_cases_total: float
    expected_value_caught_usd: float
    expected_missed_value_usd: float
    value_recall: float
    review_cost_usd: float
    expected_miss_cost_usd: float
    objective_value: float
    greedy_objective_value: float
    optimality_gap: float
    solver: str
    realised: Realised | None = None


class Plan(PlanPoint):
    day: str
    alpha: float
    mode: str
    target_recall: float
    threshold: float | None
    selected_alert_ids: list[int]
    guaranteed_alert_ids: list[int] = Field(
        description="Alerts the guarantee requires; empty when the guarantee is infeasible"
    )
    assumptions: Assumptions
    outside_expected: float


class SavedPlanOut(BaseModel):
    id: int
    plan: Plan


class SavedPlan(BaseModel):
    id: int
    date: str
    analysts: int
    alpha: float
    mode: str
    created_by: int
    created_at: str
    result: dict[str, object]
    selected_alert_ids: list[int]


class CapacityMeta(BaseModel):
    days: list[str]
    alphas: list[float]
    frontier_alphas: list[float]
    modes: list[str]
    objectives: list[str]
    default_alpha: float
    operations: Assumptions


class Frontier(BaseModel):
    day: str
    alpha: float
    mode: str
    objective: str
    solver: str
    points: list[PlanPoint]


class StaffingDay(BaseModel):
    day: str
    alerts: int
    required_alerts: int
    analysts_needed: int


class Staffing(BaseModel):
    alpha: float
    mode: str
    days: list[StaffingDay]


class ModelScore(BaseModel):
    mase: float | None
    pinball_10: float | None
    pinball_50: float | None
    pinball_90: float | None
    coverage_80: float | None
    coverage_95: float | None


class HourCount(BaseModel):
    hour: str
    alerts: int


class Band(BaseModel):
    """Out-of-sample ensemble forecast for one hour (issued at the latest rolling origin)."""

    hour: str
    q025: float
    q10: float
    q50: float
    q90: float
    q975: float


class ForecastOut(BaseModel):
    origins: int
    horizon_hours: int
    step_hours: int
    mase_scale: float
    models: dict[str, ModelScore]
    series: list[HourCount]
    bands: list[Band]
    test_start: str
    workload_definition: str


class RecallSummary(BaseModel):
    positives: int
    caught: int
    recall: Interval
    reviewed: int
    alerts: int
    review_share: float


class DayRecall(RecallSummary):
    day: str


class AlphaPoint(BaseModel):
    hour: str
    alpha_t: float


class OverallRecall(RecallSummary):
    target_recall: float
    gamma: float | None = None
    label_delay_hours: int | None = None
    alpha_trace: list[AlphaPoint] | None = None


class ReplayRun(BaseModel):
    alpha: float
    mode: str
    by_day: list[DayRecall]
    overall: OverallRecall


class Coverage(BaseModel):
    alpha: float
    runs: dict[str, ReplayRun]
    tail_days: list[str]
    label_delay_sensitivity: dict[str, OverallRecall]
    gamma: float


class ReliabilityBin(BaseModel):
    mean_predicted: float
    observed_rate: float
    low: float
    high: float
    n: int


class CalibrationSide(BaseModel):
    ece: float
    brier: float
    reliability: list[ReliabilityBin]


class SplitInfo(BaseModel):
    split: str
    alerts: int
    positives: int


class Calibration(BaseModel):
    fitted_on: SplitInfo
    evaluated_on: SplitInfo
    before: CalibrationSide
    after: CalibrationSide
    note: str


class DriftFeature(BaseModel):
    feature: str
    psi: float
    severity: str
    ks_statistic: float | None
    ks_pvalue: float | None


class DriftDay(BaseModel):
    day: str
    rows: int
    features: list[DriftFeature]
    max_psi: float
    recalibrate: bool


class Drift(BaseModel):
    baseline: str
    features_checked: list[str]
    excluded_time_anchored: list[str]
    by_day: list[DriftDay]
