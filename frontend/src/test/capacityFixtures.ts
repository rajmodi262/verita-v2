import type {
  Assumptions,
  CapacityMeta,
  Coverage,
  Forecast,
  Frontier,
  Plan,
  PlanPoint,
  ReplayRun,
  Staffing,
} from "../api/capacity";

export const DAY = "2022-09-08";

export const OPS: Assumptions = {
  median_minutes: 30,
  typology_multiplier: { "FAN-OUT": 1, CYCLE: 1.5, UNKNOWN: 1 },
  productive_hours: 6,
  analyst_hourly_rate: 60,
  miss_cost_rate: 0.1,
  min_analysts: 1,
  max_analysts: 4,
};

export const CAPACITY_META: CapacityMeta = {
  days: [DAY, "2022-09-12"],
  alphas: [0.01, 0.05, 0.1, 0.2],
  frontier_alphas: [0.01, 0.05, 0.1, 0.2],
  modes: ["pooled", "mondrian"],
  objectives: ["cases", "value"],
  default_alpha: 0.05,
  operations: OPS,
};

export function point(analysts: number, overrides: Partial<PlanPoint> = {}): PlanPoint {
  return {
    analysts,
    objective: "cases",
    capacity_minutes: analysts * 360,
    alerts: 18547,
    reviewed: analysts * 12,
    review_minutes: analysts * 355,
    guarantee: {
      required_alerts: 11890,
      required_minutes: 356700,
      feasible: false,
      analysts_needed: 991,
    },
    expected_recall: { value: 0.1 * analysts, low: 0.08 * analysts, high: 0.12 * analysts },
    expected_cases_caught: 23.4 * analysts,
    expected_cases_total: 233.3,
    expected_value_caught_usd: 1000 * analysts,
    expected_missed_value_usd: 50000 - 1000 * analysts,
    value_recall: 0.02 * analysts,
    review_cost_usd: 355 * analysts,
    expected_miss_cost_usd: 5000,
    objective_value: 23.4 * analysts,
    greedy_objective_value: 23.4 * analysts,
    optimality_gap: 0,
    solver: "greedy",
    realised: { positives: 302, caught: 30 * analysts, recall: (30 * analysts) / 302 },
    ...overrides,
  };
}

export function frontier(day = DAY): Frontier {
  return {
    day,
    alpha: 0.05,
    mode: "pooled",
    objective: "cases",
    solver: "greedy",
    points: [1, 2, 3, 4].map((n) => point(n)),
  };
}

export function plan(analysts: number, overrides: Partial<Plan> = {}): Plan {
  return {
    ...point(analysts, { solver: "cp-sat", optimality_gap: 0.0123 }),
    realised: null,
    day: DAY,
    alpha: 0.05,
    mode: "pooled",
    target_recall: 0.95,
    threshold: 0.0039,
    selected_alert_ids: [501, 502, 503],
    guaranteed_alert_ids: [],
    assumptions: { ...OPS, overridden: [] },
    outside_expected: 1.7,
    ...overrides,
  };
}

export const STAFFING: Staffing = {
  alpha: 0.05,
  mode: "pooled",
  days: [
    { day: DAY, alerts: 18547, required_alerts: 11890, analysts_needed: 991 },
    { day: "2022-09-12", alerts: 239, required_alerts: 239, analysts_needed: 3 },
  ],
};

const hours = Array.from({ length: 72 }, (_, i) => {
  const d = new Date(Date.UTC(2022, 8, 6, i));
  return d.toISOString().slice(0, 19);
});

export const FORECAST: Forecast = {
  origins: 4,
  horizon_hours: 24,
  step_hours: 6,
  mase_scale: 10,
  models: {
    seasonal_naive: {
      mase: 2.9,
      pinball_10: 1,
      pinball_50: 2,
      pinball_90: 3,
      coverage_80: 0.82,
      coverage_95: 0.86,
    },
    ensemble: {
      mase: 2.1,
      pinball_10: 1,
      pinball_50: 2,
      pinball_90: 3,
      coverage_80: 0.53,
      coverage_95: 0.67,
    },
  },
  series: hours.map((hour, i) => ({ hour, alerts: 100 + (i % 24) * 5 })),
  bands: hours.slice(48).map((hour) => ({
    hour,
    q025: 50,
    q10: 80,
    q50: 120,
    q90: 160,
    q975: 200,
  })),
  test_start: hours[48] ?? "",
  workload_definition: "alerts per hour",
};

function run(mode: string, recall: number, reviewed: number): ReplayRun {
  const day = (d: string, positives: number) => ({
    day: d,
    positives,
    caught: Math.round(positives * recall),
    recall: { value: recall, low: recall - 0.02, high: Math.min(recall + 0.01, 1) },
    reviewed: reviewed / 2,
    alerts: 100000,
    review_share: 0.5,
  });
  return {
    alpha: 0.05,
    mode,
    by_day: [day(DAY, 302), day("2022-09-12", 239)],
    overall: {
      positives: 541,
      caught: Math.round(541 * recall),
      recall: { value: recall, low: recall - 0.01, high: recall + 0.01 },
      reviewed,
      alerts: 200000,
      review_share: reviewed / 200000,
      target_recall: 0.95,
    },
  };
}

export const COVERAGE: Coverage = {
  alpha: 0.05,
  runs: {
    static_pooled: run("static_pooled", 0.984, 134186),
    static_mondrian: run("static_mondrian", 0.985, 138352),
    aci_pooled: run("aci_pooled", 0.964, 120457),
  },
  tail_days: ["2022-09-12"],
  label_delay_sensitivity: {},
  gamma: 0.005,
};

export const CALIBRATION = {
  fitted_on: { split: "calib", alerts: 1000, positives: 10 },
  evaluated_on: { split: "test", alerts: 2000, positives: 30 },
  before: { ece: 0.0116, brier: 0.002, reliability: [] },
  after: { ece: 0.002, brier: 0.0018, reliability: [] },
  note: "isotonic",
};

export const DRIFT = {
  baseline: "calib split",
  features_checked: ["s_payees_7d", "score"],
  excluded_time_anchored: ["r_age_min"],
  by_day: [
    {
      day: DAY,
      rows: 1000,
      features: [
        { feature: "r_age_min", psi: 4.08, severity: "major", ks_statistic: 0.3, ks_pvalue: 0 },
      ],
      max_psi: 4.08,
      recalibrate: true,
    },
  ],
};

export function planKey(analysts: number, extra = ""): string {
  return `GET /capacity/plan?date=${DAY}&analysts=${String(analysts)}&alpha=0.05&mode=pooled&objective=cases${extra}`;
}

export const CAPACITY_ROUTES = {
  "GET /capacity/meta": CAPACITY_META,
  [`GET /capacity/frontier?date=${DAY}&alpha=0.05&mode=pooled&objective=cases`]: frontier(),
  "GET /capacity/staffing?alpha=0.05&mode=pooled": STAFFING,
  "GET /capacity/forecast": FORECAST,
  "GET /capacity/coverage?alpha=0.05": COVERAGE,
  "GET /capacity/calibration": CALIBRATION,
  "GET /capacity/drift": DRIFT,
} as const;
