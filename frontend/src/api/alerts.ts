/**
 * Alert queue API. TypeScript types come from the backend's OpenAPI (schema.d.ts, generated);
 * the Zod schemas are checked against those types at compile time and validate at runtime.
 */
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { request } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];
export type AlertSummary = Schemas["AlertSummary"];
export type AlertList = Schemas["AlertList"];
export type AlertDetail = Schemas["AlertDetail"];
export type QueueMeta = Schemas["QueueMeta"];
export type Subgraph = Schemas["Subgraph"];
export type GraphEdge = Schemas["GraphEdge"];
export type GraphNode = Schemas["GraphNode"];

const alertSummary = z.object({
  id: z.number(),
  account_id: z.string(),
  alert_date: z.string(),
  score: z.number(),
  score_top3_mean: z.number(),
  calibrated_prob: z.number().nullable(),
  typology_pred: z.string(),
  typology_conf: z.number(),
  top_txn_id: z.number(),
  top_amount: z.number(),
  top_currency: z.string(),
  n_transactions: z.number(),
  n_flagged: z.number(),
  status: z.string(),
}) satisfies z.ZodType<AlertSummary>;

const alertList = z.object({
  items: z.array(alertSummary),
  next_cursor: z.string().nullable(),
  total: z.number(),
  threshold: z.number(),
}) satisfies z.ZodType<AlertList>;

const alertDetail = alertSummary.extend({
  reasons: z.array(
    z.object({
      rank: z.number(),
      feature: z.string(),
      value: z.number(),
      shap: z.number(),
      text: z.string(),
      evidence_id: z.string(),
    }),
  ),
  dispositions: z.array(
    z.object({
      id: z.number(),
      action: z.string(),
      reason_code: z.string(),
      note: z.string(),
      user_id: z.number(),
      created_at: z.string(),
    }),
  ),
}) satisfies z.ZodType<AlertDetail>;

const queueMeta = z.object({
  model: z.object({
    id: z.number(),
    name: z.string(),
    dataset: z.string(),
    threshold: z.number(),
    alert_floor: z.number().nullable(),
  }),
  days: z.array(z.object({ date: z.string(), alerts: z.number() })),
  by_status: z.record(z.string(), z.number()),
  typologies: z.array(z.string()),
  dismiss_reasons: z.record(z.string(), z.string()),
  escalate_reasons: z.record(z.string(), z.string()),
}) satisfies z.ZodType<QueueMeta>;

const graphEdge = z.object({
  evidence_id: z.string(),
  txn_id: z.number(),
  from: z.string(),
  to: z.string(),
  ts: z.string(),
  amount_paid: z.number(),
  currency_paid: z.string(),
  amount_received: z.number(),
  currency_received: z.string(),
  payment_format: z.string(),
  score: z.number(),
  flagged: z.boolean(),
  on_dominant_path: z.boolean(),
}) satisfies z.ZodType<GraphEdge>;

const subgraph = z.object({
  alert_id: z.number(),
  window: z.object({ from: z.string(), to: z.string() }),
  center: z.string(),
  nodes: z.array(
    z.object({
      id: z.string(),
      is_center: z.boolean(),
      max_score: z.number(),
      degree: z.number(),
    }),
  ),
  edges: z.array(graphEdge),
  dominant_path: z.object({
    evidence_id: z.string(),
    txn_ids: z.array(z.number()),
    evidence_ids: z.array(z.string()),
  }),
  motif: z.object({ evidence_id: z.string(), signals: z.array(z.string()) }),
  truncated: z.boolean(),
}) satisfies z.ZodType<Subgraph>;

export interface QueueFilters {
  date?: string | undefined;
  status?: string | undefined;
  typology?: string | undefined;
  minScore?: number | undefined;
}

export const PAGE_SIZE = 100;

function queueParams(filters: QueueFilters, cursor: string | null): string {
  const params = new URLSearchParams({ limit: String(PAGE_SIZE) });
  if (filters.date) params.set("date", filters.date);
  if (filters.status) params.set("status", filters.status);
  if (filters.typology) params.set("typology", filters.typology);
  if (filters.minScore !== undefined) params.set("min_score", String(filters.minScore));
  if (cursor) params.set("cursor", cursor);
  return params.toString();
}

export function useQueueMeta() {
  return useQuery({
    queryKey: ["alerts", "meta"],
    queryFn: ({ signal }) => request("/alerts/meta", { schema: queueMeta, signal }),
    staleTime: 60_000,
  });
}

export function useAlertQueue(filters: QueueFilters) {
  return useInfiniteQuery({
    queryKey: ["alerts", "list", filters],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) =>
      request(`/alerts?${queueParams(filters, pageParam)}`, { schema: alertList, signal }),
    getNextPageParam: (last) => last.next_cursor,
  });
}

export function useAlert(id: number) {
  return useQuery({
    queryKey: ["alerts", "detail", id],
    queryFn: ({ signal }) => request(`/alerts/${String(id)}`, { schema: alertDetail, signal }),
  });
}

export function useSubgraph(id: number) {
  return useQuery({
    queryKey: ["alerts", "subgraph", id],
    queryFn: ({ signal }) =>
      request(`/alerts/${String(id)}/subgraph`, { schema: subgraph, signal }),
    staleTime: 5 * 60_000,
  });
}

export type DispositionAction = "escalate" | "dismiss" | "reopen";

export interface DispositionInput {
  alertId: number;
  action: DispositionAction;
  reasonCode: string;
  note: string;
}

export function useDisposition() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: DispositionInput) =>
      request(`/alerts/${String(input.alertId)}/disposition`, {
        method: "POST",
        body: { action: input.action, reason_code: input.reasonCode, note: input.note },
        schema: alertDetail,
      }),
    onSuccess: (detail) => {
      client.setQueryData(["alerts", "detail", detail.id], detail);
      void client.invalidateQueries({ queryKey: ["alerts", "list"] });
      void client.invalidateQueries({ queryKey: ["alerts", "meta"] });
    },
  });
}
