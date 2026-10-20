/** Model governance (M10.01): versions, their validation reports, and lifecycle actions. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { request } from "./client";

const gate = z.object({
  gate: z.string(),
  passed: z.boolean(),
  value: z.unknown(),
  limit: z.unknown(),
  rule: z.string(),
});

const modelOut = z.object({
  id: z.number(),
  name: z.string(),
  dataset: z.string(),
  status: z.string(),
  is_champion: z.boolean(),
  champion_sha256: z.string(),
  git_revision: z.string().nullable(),
  threshold: z.number(),
  created_at: z.string(),
  proposed_by: z.string().nullable(),
  validation: z
    .object({
      passed: z.boolean(),
      sha256: z.string().nullable(),
      policy_version: z.unknown(),
      failed_gates: z.array(z.string()),
    })
    .nullable(),
  approved_by_id: z.number().nullable(),
  approved_at: z.string().nullable(),
  promoted_by_id: z.number().nullable(),
  promoted_at: z.string().nullable(),
  decision_note: z.string().nullable(),
  governance: z.string(),
  bypass_reason: z.string().nullable(),
});

const modelDetail = modelOut.extend({
  report: z
    .object({ passed: z.boolean(), gates: z.array(gate) })
    .loose()
    .nullable(),
});

export type ModelVersion = z.infer<typeof modelOut>;
export type ModelDetail = z.infer<typeof modelDetail>;
export type Gate = z.infer<typeof gate>;

export function useModels() {
  return useQuery({
    queryKey: ["models", "list"],
    queryFn: ({ signal }) =>
      request("/models", { schema: z.object({ items: z.array(modelOut) }), signal }),
  });
}

export function useModel(id: number | null) {
  return useQuery({
    queryKey: ["models", "detail", id],
    enabled: id !== null,
    queryFn: ({ signal }) => request(`/models/${String(id)}`, { schema: modelDetail, signal }),
  });
}

export function useModelAction(id: number, action: "validate" | "approve" | "reject" | "promote") {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (note: string | null) =>
      request(`/models/${String(id)}/${action}`, {
        method: "POST",
        body: action === "validate" ? undefined : { note },
        schema: modelDetail,
      }),
    onSuccess: (detail) => {
      client.setQueryData(["models", "detail", id], detail);
      void client.invalidateQueries({ queryKey: ["models", "list"] });
    },
  });
}
