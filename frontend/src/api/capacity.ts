/**
 * Capacity planner API (Decide). Types come from the backend's OpenAPI; the Zod schemas are
 * checked against them at compile time and validate every response at runtime.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { ApiError, request } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];
export type CapacityMeta = Schemas["CapacityMeta"];
export type PlanPoint = Schemas["PlanPoint"];
export type Plan = Schemas["Plan"];
export type Frontier = Schemas["Frontier"];
export type Staffing = Schemas["Staffing"];
export type Forecast = Schemas["ForecastOut"];
export type Coverage = Schemas["Coverage"];
export type ReplayRun = Schemas["ReplayRun"];
export type SavedPlan = Schemas["SavedPlan"];
export type Assumptions = Schemas["Assumptions"];

const interval = z.object({ value: z.number(), low: z.number(), high: z.number() });

const assumptions = z.object({
  median_minutes: z.number(),
  typology_multiplier: z.record(z.string(), z.number()),
  productive_hours: z.number(),
  analyst_hourly_rate: z.number(),
  miss_cost_rate: z.number(),
  min_analysts: z.number(),
  max_analysts: z.number(),
  overridden: z.array(z.string()).exactOptional(),
}) satisfies z.ZodType<Assumptions>;

const capacityMeta = z.object({
  days: z.array(z.string()),
  alphas: z.array(z.number()),
  frontier_alphas: z.array(z.number()),
  modes: z.array(z.string()),
  objectives: z.array(z.string()),
  default_alpha: z.number(),
  operations: assumptions,
}) satisfies z.ZodType<CapacityMeta>;

const planPoint = z.object({
  analysts: z.number(),
  objective: z.string(),
  capacity_minutes: z.number(),
  alerts: z.number(),
  reviewed: z.number(),
  review_minutes: z.number(),
  guarantee: z.object({
    required_alerts: z.number(),
    required_minutes: z.number(),
    feasible: z.boolean(),
    analysts_needed: z.number(),
  }),
  expected_recall: interval,
  expected_cases_caught: z.number(),
  expected_cases_total: z.number(),
  expected_value_caught_usd: z.number(),
  expected_missed_value_usd: z.number(),
  value_recall: z.number(),
  review_cost_usd: z.number(),
  expected_miss_cost_usd: z.number(),
  objective_value: z.number(),
  greedy_objective_value: z.number(),
  optimality_gap: z.number(),
  solver: z.string(),
  realised: z
    .object({ positives: z.number(), caught: z.number(), recall: z.number().nullable() })
    .nullable()
    .exactOptional(),
}) satisfies z.ZodType<PlanPoint>;

const plan = planPoint.extend({
  day: z.string(),
  alpha: z.number(),
  mode: z.string(),
  target_recall: z.number(),
  threshold: z.number().nullable(),
  selected_alert_ids: z.array(z.number()),
  guaranteed_alert_ids: z.array(z.number()),
  assumptions,
  outside_expected: z.number(),
}) satisfies z.ZodType<Plan>;

const frontier = z.object({
  day: z.string(),
  alpha: z.number(),
  mode: z.string(),
  objective: z.string(),
  solver: z.string(),
  points: z.array(planPoint),
}) satisfies z.ZodType<Frontier>;

const staffing = z.object({
  alpha: z.number(),
  mode: z.string(),
  days: z.array(
    z.object({
      day: z.string(),
      alerts: z.number(),
      required_alerts: z.number(),
      analysts_needed: z.number(),
    }),
  ),
}) satisfies z.ZodType<Staffing>;

const nullableNumber = z.number().nullable();

const forecast = z.object({
  origins: z.number(),
  horizon_hours: z.number(),
  step_hours: z.number(),
  mase_scale: z.number(),
  models: z.record(
    z.string(),
    z.object({
      mase: nullableNumber,
      pinball_10: nullableNumber,
      pinball_50: nullableNumber,
      pinball_90: nullableNumber,
      coverage_80: nullableNumber,
      coverage_95: nullableNumber,
    }),
  ),
  series: z.array(z.object({ hour: z.string(), alerts: z.number() })),
  bands: z.array(
    z.object({
      hour: z.string(),
      q025: z.number(),
      q10: z.number(),
      q50: z.number(),
      q90: z.number(),
      q975: z.number(),
    }),
  ),
  test_start: z.string(),
  workload_definition: z.string(),
}) satisfies z.ZodType<Forecast>;

const recallSummary = z.object({
  positives: z.number(),
  caught: z.number(),
  recall: interval,
  reviewed: z.number(),
  alerts: z.number(),
  review_share: z.number(),
});

const overall = recallSummary.extend({
  target_recall: z.number(),
  gamma: z.number().nullable().exactOptional(),
  label_delay_hours: z.number().nullable().exactOptional(),
  alpha_trace: z
    .array(z.object({ hour: z.string(), alpha_t: z.number() }))
    .nullable()
    .exactOptional(),
});

const replayRun = z.object({
  alpha: z.number(),
  mode: z.string(),
  by_day: z.array(recallSummary.extend({ day: z.string() })),
  overall,
}) satisfies z.ZodType<ReplayRun>;

const coverage = z.object({
  alpha: z.number(),
  runs: z.record(z.string(), replayRun),
  tail_days: z.array(z.string()),
  label_delay_sensitivity: z.record(z.string(), overall),
  gamma: z.number(),
}) satisfies z.ZodType<Coverage>;

const savedPlan = z.object({
  id: z.number(),
  date: z.string(),
  analysts: z.number(),
  alpha: z.number(),
  mode: z.string(),
  created_by: z.number(),
  created_at: z.string(),
  result: z.record(z.string(), z.unknown()),
  selected_alert_ids: z.array(z.number()),
}) satisfies z.ZodType<SavedPlan>;

const savedPlanOut = z.object({ id: z.number(), plan });

export type Mode = "pooled" | "mondrian";
export type Objective = "cases" | "value";

export interface WhatIf {
  median_minutes?: number | undefined;
  productive_hours?: number | undefined;
  analyst_hourly_rate?: number | undefined;
}

export interface PlanQuery {
  date: string;
  analysts: number;
  alpha: number;
  mode: Mode;
  objective: Objective;
  whatIf?: WhatIf;
}

function planParams(q: PlanQuery): string {
  const params = new URLSearchParams({
    date: q.date,
    analysts: String(q.analysts),
    alpha: String(q.alpha),
    mode: q.mode,
    objective: q.objective,
  });
  for (const [key, value] of Object.entries(q.whatIf ?? {})) {
    if (value !== undefined) params.set(key, String(value));
  }
  return params.toString();
}

const STATIC = { staleTime: 10 * 60_000 } as const;

export function useCapacityMeta() {
  return useQuery({
    queryKey: ["capacity", "meta"],
    queryFn: ({ signal }) => request("/capacity/meta", { schema: capacityMeta, signal }),
    ...STATIC,
  });
}

export function useFrontier(
  date: string | undefined,
  alpha: number,
  mode: Mode,
  objective: Objective,
) {
  return useQuery({
    queryKey: ["capacity", "frontier", date, alpha, mode, objective],
    queryFn: ({ signal }) => {
      const params = new URLSearchParams({
        date: date ?? "",
        alpha: String(alpha),
        mode,
        objective,
      });
      return request(`/capacity/frontier?${params.toString()}`, { schema: frontier, signal });
    },
    enabled: date !== undefined,
    placeholderData: keepPreviousData,
    ...STATIC,
  });
}

export function useStaffing(alpha: number, mode: Mode) {
  return useQuery({
    queryKey: ["capacity", "staffing", alpha, mode],
    queryFn: ({ signal }) =>
      request(`/capacity/staffing?alpha=${String(alpha)}&mode=${mode}`, {
        schema: staffing,
        signal,
      }),
    placeholderData: keepPreviousData,
    ...STATIC,
  });
}

/** The exact plan; ``q`` is null until the controls settle, so dragging never floods the API. */
export function usePlan(q: PlanQuery | null) {
  return useQuery({
    queryKey: ["capacity", "plan", q],
    queryFn: ({ signal }) => {
      if (q === null) throw new Error("usePlan ran while disabled");
      return request(`/capacity/plan?${planParams(q)}`, { schema: plan, signal });
    },
    enabled: q !== null,
    placeholderData: keepPreviousData,
    staleTime: 5 * 60_000,
  });
}

export function useForecast() {
  return useQuery({
    queryKey: ["capacity", "forecast"],
    queryFn: ({ signal }) => request("/capacity/forecast", { schema: forecast, signal }),
    ...STATIC,
  });
}

export function useCoverage(alpha: number) {
  return useQuery({
    queryKey: ["capacity", "coverage", alpha],
    queryFn: ({ signal }) =>
      request(`/capacity/coverage?alpha=${String(alpha)}`, { schema: coverage, signal }),
    placeholderData: keepPreviousData,
    ...STATIC,
  });
}

/** Latest saved plan for a day, or null when none has been saved. */
export function useLatestPlan(date: string | undefined) {
  return useQuery({
    queryKey: ["capacity", "latest", date],
    queryFn: async ({ signal }) => {
      try {
        return await request(`/capacity/plans/latest?date=${date ?? ""}`, {
          schema: savedPlan,
          signal,
        });
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    },
    enabled: date !== undefined,
  });
}

export function useSavePlan() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (q: Omit<PlanQuery, "whatIf">) =>
      request("/capacity/plans", {
        method: "POST",
        body: {
          date: q.date,
          analysts: q.analysts,
          alpha: q.alpha,
          mode: q.mode,
          objective: q.objective,
        },
        schema: savedPlanOut,
      }),
    onSuccess: (_saved, q) => {
      void client.invalidateQueries({ queryKey: ["capacity", "latest", q.date] });
    },
  });
}

const reliabilityBin = z.object({
  mean_predicted: z.number(),
  observed_rate: z.number(),
  low: z.number(),
  high: z.number(),
  n: z.number(),
});

const calibrationSide = z.object({
  ece: z.number(),
  brier: z.number(),
  reliability: z.array(reliabilityBin),
});

const splitInfo = z.object({ split: z.string(), alerts: z.number(), positives: z.number() });

const calibration = z.object({
  fitted_on: splitInfo,
  evaluated_on: splitInfo,
  before: calibrationSide,
  after: calibrationSide,
  note: z.string(),
}) satisfies z.ZodType<Schemas["Calibration"]>;

const drift = z.object({
  baseline: z.string(),
  features_checked: z.array(z.string()),
  by_day: z.array(
    z.object({
      day: z.string(),
      rows: z.number(),
      features: z.array(
        z.object({
          feature: z.string(),
          psi: z.number(),
          severity: z.string(),
          ks_statistic: z.number().nullable(),
          ks_pvalue: z.number().nullable(),
        }),
      ),
      max_psi: z.number(),
      recalibrate: z.boolean(),
    }),
  ),
}) satisfies z.ZodType<Schemas["Drift"]>;

export type Calibration = Schemas["Calibration"];
export type Drift = Schemas["Drift"];

export function useCalibration() {
  return useQuery({
    queryKey: ["capacity", "calibration"],
    queryFn: ({ signal }) => request("/capacity/calibration", { schema: calibration, signal }),
    ...STATIC,
  });
}

export function useDrift() {
  return useQuery({
    queryKey: ["capacity", "drift"],
    queryFn: ({ signal }) => request("/capacity/drift", { schema: drift, signal }),
    ...STATIC,
  });
}
