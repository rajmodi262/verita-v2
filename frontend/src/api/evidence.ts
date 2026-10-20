/**
 * Evidence Room: the generated `reports/metrics.json`, served as-is with its SHA-256.
 *
 * The file is a report, not an API contract, so the schema below validates only the parts the
 * Evidence Room reads (the rest passes through untouched) and every section may be absent —
 * a dataset that has not been through Decide simply has no Decide tab content.
 */
import { useQuery } from "@tanstack/react-query";
import { z } from "zod";

import { request } from "./client";

const interval = z
  .object({
    value: z.number(),
    low: z.number().nullable().optional(),
    high: z.number().nullable().optional(),
  })
  .loose();
const wilson = z.object({ value: z.number(), low: z.number(), high: z.number() }).loose();
const rate = interval.extend({ hits: z.number(), total: z.number() }).loose();

const testScores = z
  .object({
    f1: interval,
    pr_auc: interval,
    precision: z.number(),
    recall: z.number(),
    positives: z.number(),
  })
  .loose();

const detect = z
  .object({
    n_features: z.number(),
    threshold: z.number(),
    hpo: z.object({ trials: z.number(), hpo_f1: z.number() }).loose(),
    models: z.record(
      z.string(),
      z
        .object({
          test: testScores,
          test_bulk: testScores.optional(),
          test_tail: testScores.optional(),
        })
        .loose(),
    ),
    seeds: z
      .object({ seeds: z.array(z.number()), f1_mean: z.number(), f1_std: z.number() })
      .loose(),
    per_typology: z.array(
      z.object({
        typology: z.string(),
        support: z.number(),
        detected: z.number(),
        recall: interval,
      }),
    ),
    ablation: z.array(z.object({ removed_group: z.string(), f1: interval, delta: interval })),
    imbalance: z.array(z.object({ variant: z.string(), f1: interval, pr_auc: interval }).loose()),
    sanity: z
      .object({
        label_shuffle: z.object({ test_pr_auc: z.number(), base_rate: z.number() }).loose(),
        random_split: z.object({ random_split_test_f1: z.number() }).loose(),
      })
      .loose(),
    typology_head: z.object({
      accuracy: z.number(),
      majority_class_accuracy: z.number(),
      macro_f1: z.number(),
    }),
    shap_top: z.array(z.object({ feature: z.string(), mean_abs_shap: z.number() }).loose()),
    published_baselines: z.object({
      source: z.string(),
      metric: z.string(),
      rows: z.record(z.string(), z.object({ mean: z.number(), std: z.number() })),
    }),
  })
  .loose();

const bin = z.object({
  mean_predicted: z.number(),
  observed_rate: z.number(),
  low: z.number(),
  high: z.number(),
  n: z.number(),
});
const calibrationSide = z.object({ ece: z.number(), brier: z.number(), reliability: z.array(bin) });

const dayRecall = z
  .object({
    day: z.string(),
    positives: z.number(),
    caught: z.number(),
    recall: wilson,
    reviewed: z.number(),
    alerts: z.number(),
    review_share: z.number(),
  })
  .loose();
const replay = z.object({
  overall: z
    .object({
      positives: z.number(),
      caught: z.number(),
      recall: wilson,
      reviewed: z.number(),
      alerts: z.number(),
      review_share: z.number(),
      target_recall: z.number(),
    })
    .loose(),
  by_day: z.array(dayRecall),
});

const decide = z
  .object({
    calibration: z.object({ before: calibrationSide, after: calibrationSide }).loose(),
    coverage: z
      .object({
        by_alpha: z.record(z.string(), z.record(z.string(), replay)),
        label_delay_sensitivity: z.record(
          z.string(),
          z.object({ recall: interval, reviewed: z.number() }).loose(),
        ),
        gamma: z.number(),
        tail_days: z.array(z.string()),
      })
      .loose(),
    forecast: z
      .object({
        origins: z.number().nullable(),
        horizon_hours: z.number().nullable(),
        models: z
          .record(
            z.string(),
            z
              .object({
                mase: z.number().nullable(),
                coverage_80: z.number().nullable(),
                coverage_95: z.number().nullable(),
              })
              .loose(),
          )
          .nullable(),
      })
      .loose(),
    drift: z
      .object({
        excluded_time_anchored: z.array(z.string()),
        by_day: z.array(
          z.object({
            day: z.string(),
            rows: z.number(),
            max_psi: z.number(),
            recalibrate: z.boolean(),
            top: z.string().nullable(),
          }),
        ),
      })
      .loose(),
    staffing: z
      .object({ by_day: z.record(z.string(), z.number()), max_analysts_needed: z.number() })
      .loose()
      .nullable(),
    bench: z
      .object({
        subgraph: z
          .object({
            n: z.number(),
            p50_ms: z.number(),
            p95_ms: z.number(),
            target_p95_ms: z.number(),
          })
          .loose(),
        plan: z
          .object({
            warm: z.object({ p95_ms: z.number() }).loose(),
            cold: z.object({ p95_ms: z.number() }).loose(),
          })
          .loose(),
      })
      .loose()
      .nullable(),
  })
  .loose();

const defend = z
  .object({
    cases: z.number(),
    claims_checked_on_clean: z.number(),
    clean_false_alarm: rate,
    overall_detection: rate,
    verifier_version: z.string(),
    faults: z.record(
      z.string(),
      z.object({
        planted: z.number(),
        detection: rate,
        localisation: rate,
        misses: z.array(
          z.object({
            alert_id: z.number(),
            change: z.string(),
            sentence: z.object({ text: z.string() }).loose(),
          }),
        ),
      }),
    ),
    llm: z.object({ run: z.boolean(), reason: z.string().optional() }).loose(),
  })
  .loose();

const data = z
  .object({
    source: z.string(),
    rows: z.number(),
    laundering: z.number(),
    laundering_rate: z.number(),
    time_span: z.object({ from: z.string(), to: z.string() }),
    contract_passed: z.boolean(),
    violations: z.record(z.string(), z.number()),
    patterns: z.object({
      attempts: z.number(),
      coverage: z.number(),
      laundering_attributed: z.number(),
      laundering_unattributed: z.number(),
    }),
    patterns_by_typology: z.record(
      z.string(),
      z.object({ attempts: z.number(), transactions: z.number() }),
    ),
    sparse_tail_days: z.array(z.string()),
    splits: z.object({ method: z.string() }).catchall(z.unknown()),
    files: z.array(z.object({ name: z.string(), sha256: z.string(), ok: z.boolean() })),
  })
  .loose();

const lineage = z.array(
  z.object({
    stage: z.string(),
    git_revision: z.string().nullable().optional(),
    config_hash: z.string().nullable().optional(),
    duration_s: z.number().nullable().optional(),
    started_at: z.string().nullable().optional(),
    inputs: z.record(z.string(), z.string()),
    outputs: z.record(z.string(), z.string()),
  }),
);

const datasetSection = z.object({
  label: z.string(),
  data: data.nullable(),
  detect: detect.nullable(),
  decide: decide.nullable(),
  defend: defend.nullable(),
  lineage,
});

const headline = z
  .object({
    key: z.string(),
    label: z.string(),
    value: z.number(),
    low: z.number().nullable().optional(),
    high: z.number().nullable().optional(),
    dataset: z.string(),
    split: z.string(),
    source: z.string(),
    n: z.number().nullable().optional(),
  })
  .loose();

export const metricsFile = z.object({
  schema_version: z.number(),
  generated_at: z.string(),
  git_sha: z.string(),
  synthetic_data_notice: z.string(),
  primary_dataset: z.string(),
  headline: z.array(headline),
  datasets: z.record(z.string(), datasetSection),
});

const evidenceResponse = z.object({ sha256: z.string(), metrics: metricsFile });

export type MetricsFile = z.infer<typeof metricsFile>;
export type DatasetSection = z.infer<typeof datasetSection>;
export type Headline = z.infer<typeof headline>;
export type Interval = z.infer<typeof interval>;
export type DetectSection = z.infer<typeof detect>;
export type DecideSection = z.infer<typeof decide>;
export type DefendSection = z.infer<typeof defend>;
export type DataSection = z.infer<typeof data>;

export function useEvidence() {
  return useQuery({
    queryKey: ["evidence-room"],
    queryFn: ({ signal }) =>
      request("/evidence-room/metrics", { schema: evidenceResponse, signal }),
    staleTime: 10 * 60_000,
  });
}

export function headlineValue(m: MetricsFile, key: string): Headline | undefined {
  return m.headline.find((h) => h.key === key);
}

const headlineResponse = z.object({
  sha256: z.string(),
  git_sha: z.string(),
  schema_version: z.number(),
  synthetic_data_notice: z.string(),
  headline: z.array(headline),
});
export type HeadlineResponse = z.infer<typeof headlineResponse>;

/** Public (no sign-in): the landing page's measured figures. */
export function useHeadline() {
  return useQuery({
    queryKey: ["evidence-room", "headline"],
    queryFn: ({ signal }) =>
      request("/evidence-room/headline", { schema: headlineResponse, signal }),
    staleTime: 10 * 60_000,
    retry: false,
  });
}
