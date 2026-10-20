/**
 * Case files API (Defend). Types come from the backend's OpenAPI; the Zod schemas are checked
 * against them at compile time and validate every response at runtime.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { API_PREFIX, request } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];
export type CaseDetail = Schemas["CaseDetail"];
export type CaseSummary = Schemas["CaseSummary"];
export type CaseMeta = Schemas["CaseMeta"];
export type EvidenceItem = Schemas["EvidenceItem"];
/** A narrative sentence as the server returns it (citations always present). */
export type Sentence = Required<Schemas["SentenceIn"]>;
export type SentenceReport = Schemas["SentenceReport"];
export type Claim = Schemas["ClaimOut"];
export type Job = Schemas["JobOut"];
export type SignatureCheck = Schemas["SignatureCheck"];
export type CaseEvent = Schemas["EventOut"];

const record = z.record(z.string(), z.unknown());
const section = z.enum(["who", "what", "when", "where", "why", "how"]);

const sentence = z.object({
  section,
  text: z.string(),
  evidence_ids: z.array(z.string()),
}) satisfies z.ZodType<Sentence>;

const claim = z.object({
  kind: z.string(),
  text: z.string(),
  passed: z.boolean(),
  expected: z.string().nullable(),
  detail: z.string(),
}) satisfies z.ZodType<Claim>;

const report = z.object({
  passed: z.boolean(),
  verifier_version: z.string(),
  sentences: z.array(
    z.object({
      index: z.number(),
      section: z.string(),
      text: z.string(),
      evidence_ids: z.array(z.string()),
      passed: z.boolean(),
      errors: z.array(z.string()),
      claims: z.array(claim),
    }),
  ),
  coverage: z.record(z.string(), z.boolean()),
  errors: z.array(z.string()),
  failed_sentences: z.array(z.number()),
}) satisfies z.ZodType<Schemas["Report"]>;

const ledgerCheck = z.object({
  valid: z.boolean(),
  broken_at: z.number().nullable(),
  reason: z.string().nullable(),
  head: z.string().nullable().exactOptional(),
  length: z.number().nullable().exactOptional(),
}) satisfies z.ZodType<Schemas["LedgerCheck"]>;

const caseDetail = z.object({
  id: z.number(),
  title: z.string(),
  state: z.string(),
  created_by: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
  alert_ids: z.array(z.number()),
  evidence: z.array(z.object({ id: z.string(), kind: z.string(), payload: record })),
  narrative: z
    .object({
      id: z.number(),
      version: z.number(),
      mode: z.string(),
      provider: z.string(),
      model: z.string(),
      prompt_hash: z.string(),
      sentences: z.array(sentence),
      created_by: z.string(),
      created_at: z.string(),
    })
    .nullable(),
  verification: z
    .object({ id: z.number(), passed: z.boolean(), report, created_at: z.string() })
    .nullable(),
  events: z.array(
    z.object({
      seq: z.number(),
      type: z.string(),
      actor: z.string().nullable(),
      payload: record,
      created_at: z.string(),
      hash: z.string(),
      prev_hash: z.string(),
    }),
  ),
  ledger: ledgerCheck,
  signature: z
    .object({
      merkle_root: z.string(),
      key_id: z.string(),
      signed_by: z.string(),
      signed_at: z.string(),
    })
    .nullable(),
  permissions: z.object({
    edit: z.boolean(),
    submit: z.boolean(),
    approve: z.boolean(),
    approve_blockers: z.array(z.string()),
    return: z.boolean(),
    close: z.boolean(),
  }),
}) satisfies z.ZodType<CaseDetail>;

const caseList = z.object({
  items: z.array(
    z.object({
      id: z.number(),
      title: z.string(),
      state: z.string(),
      created_by: z.string(),
      updated_at: z.string(),
      alerts: z.number(),
    }),
  ),
}) satisfies z.ZodType<Schemas["CaseList"]>;

const caseMeta = z.object({
  return_reasons: z.record(z.string(), z.string()),
  close_reasons: z.record(z.string(), z.string()),
  llm_providers: z.array(z.string()),
  offline_only: z.boolean(),
}) satisfies z.ZodType<CaseMeta>;

const job = z.object({
  id: z.number(),
  kind: z.string(),
  status: z.string(),
  attempts: z.number(),
  progress: z.string(),
  result: record.nullable(),
  error: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
}) satisfies z.ZodType<Job>;

const signatureCheck = z.object({
  valid: z.boolean(),
  signature_valid: z.boolean(),
  root_matches: z.boolean(),
  recomputed_root: z.string(),
  changed_leaves: z.array(z.string()),
  ledger: ledgerCheck,
}) satisfies z.ZodType<SignatureCheck>;

const keys = z.object({
  keys: z.array(
    z.object({
      key_id: z.string(),
      algorithm: z.string(),
      public_key_pem: z.string(),
      created_at: z.string(),
      message_format: z.string(),
    }),
  ),
}) satisfies z.ZodType<Schemas["Keys"]>;

export type PublicKey = z.infer<typeof keys>["keys"][number];

const caseKey = (id: number) => ["cases", "detail", id] as const;

export function exportUrl(id: number, kind: "json" | "pdf" | "tampered"): string {
  const file =
    kind === "pdf" ? "export.pdf" : kind === "json" ? "export.json" : "export-tampered.json";
  return `${API_PREFIX}/cases/${String(id)}/${file}`;
}

export function useCaseMeta() {
  return useQuery({
    queryKey: ["cases", "meta"],
    queryFn: ({ signal }) => request("/cases/meta", { schema: caseMeta, signal }),
    staleTime: 10 * 60_000,
  });
}

export function useCases() {
  return useQuery({
    queryKey: ["cases", "list"],
    queryFn: ({ signal }) => request("/cases", { schema: caseList, signal }),
  });
}

export function useCase(id: number) {
  return useQuery({
    queryKey: caseKey(id),
    queryFn: ({ signal }) => request(`/cases/${String(id)}`, { schema: caseDetail, signal }),
  });
}

export function usePublicKeys() {
  return useQuery({
    queryKey: ["keys"],
    queryFn: ({ signal }) => request("/keys", { schema: keys, signal }),
    staleTime: Infinity,
  });
}

export function useSignatureCheck(id: number, enabled: boolean) {
  return useQuery({
    queryKey: ["cases", "signature", id],
    queryFn: ({ signal }) =>
      request(`/cases/${String(id)}/verify-signature`, { schema: signatureCheck, signal }),
    enabled,
  });
}

/** Poll a job until it finishes; the case is refetched when it does. */
export function useJob(jobId: number | null, caseId: number) {
  const client = useQueryClient();
  return useQuery({
    queryKey: ["jobs", jobId],
    queryFn: async ({ signal }) => {
      const result = await request(`/jobs/${String(jobId)}`, { schema: job, signal });
      if (result.status === "done" || result.status === "failed") {
        void client.invalidateQueries({ queryKey: caseKey(caseId) });
      }
      return result;
    },
    enabled: jobId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "done" || status === "failed" ? false : 700;
    },
  });
}

function useCaseAction<TBody>(id: number, method: "POST" | "PUT", path: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: TBody) =>
      request(`/cases/${String(id)}${path}`, { method, body, schema: caseDetail }),
    onSuccess: (detail) => {
      client.setQueryData(caseKey(id), detail);
      void client.invalidateQueries({ queryKey: ["cases", "list"] });
    },
  });
}

export const useEditNarrative = (id: number) =>
  useCaseAction<{ sentences: Sentence[] }>(id, "PUT", "/narrative");
export const useVerify = (id: number) =>
  useCaseAction<Record<string, never>>(id, "POST", "/verify");
export const useSubmit = (id: number) =>
  useCaseAction<Record<string, never>>(id, "POST", "/submit");
export const useApprove = (id: number) =>
  useCaseAction<Record<string, never>>(id, "POST", "/approve");
export const useReturn = (id: number) =>
  useCaseAction<{ reason: string; note: string }>(id, "POST", "/return");
export const useClose = (id: number) =>
  useCaseAction<{ reason: string; note: string }>(id, "POST", "/close");

export function useDraft(id: number) {
  return useMutation({
    mutationFn: (mode: "auto" | "llm" | "offline") =>
      request(`/cases/${String(id)}/narrative`, { method: "POST", body: { mode }, schema: job }),
  });
}

export function useCreateCase() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (alertIds: number[]) =>
      request("/cases", { method: "POST", body: { alert_ids: alertIds }, schema: caseDetail }),
    onSuccess: (detail) => {
      client.setQueryData(caseKey(detail.id), detail);
      void client.invalidateQueries({ queryKey: ["cases", "list"] });
      void client.invalidateQueries({ queryKey: ["alerts"] });
    },
  });
}
