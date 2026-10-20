import type { CaseDetail, Sentence } from "../api/cases";

export const SENTENCES: Sentence[] = [
  {
    section: "what",
    text: "Between 2022-09-07 and 2022-09-08 the case file records 4 payments across 5 accounts, totalling 30,546.75 US Dollar at fixed conversion rates.",
    evidence_ids: ["EV-CASE-1"],
  },
  {
    section: "how",
    text: "On 2022-09-08, account 8000AAAA1 at bank 70 paid 9,800.00 US Dollar to account 8000BBBB2 at bank 11 by ACH.",
    evidence_ids: ["EV-TXN-101"],
  },
];

function report(failing: boolean) {
  return {
    passed: !failing,
    verifier_version: "1.0.0",
    coverage: { "dominant path": true, "case total": true, "date range": true, typology: !failing },
    errors: failing ? ["coverage: the narrative never states the typology"] : [],
    failed_sentences: failing ? [1] : [],
    sentences: SENTENCES.map((s, index) => ({
      index,
      section: s.section,
      text: s.text,
      evidence_ids: s.evidence_ids,
      passed: !(failing && index === 1),
      errors: [],
      claims:
        failing && index === 1
          ? [
              {
                kind: "amount",
                text: "9,800.00 US Dollar",
                passed: false,
                expected: "amount 9500.0 US Dollar",
                detail: "cited evidence says amount 9500.0 US Dollar",
              },
            ]
          : [
              {
                kind: "count",
                text: "4 payments",
                passed: true,
                expected: "count 4.0 payment",
                detail: "matches cited evidence",
              },
            ],
    })),
  };
}

export function caseDetail(overrides: Partial<CaseDetail> = {}, failing = false): CaseDetail {
  return {
    id: 1,
    title: "Fan-Out activity around 70:8000AAAA1",
    state: failing ? "draft" : "verified",
    created_by: "priya",
    created_at: "2022-09-12T09:00:00+00:00",
    updated_at: "2022-09-12T09:05:00+00:00",
    alert_ids: [7],
    evidence: [
      { id: "EV-CASE-1", kind: "case", payload: { total_usd: 30546.75, payments: 4 } },
      { id: "EV-TXN-101", kind: "txn", payload: { amount_paid: 9800, currency_paid: "US Dollar" } },
    ],
    narrative: {
      id: 3,
      version: 1,
      mode: "offline",
      provider: "template",
      model: "offline-template-narrative_v1",
      prompt_hash: "ab".repeat(32),
      sentences: SENTENCES,
      created_by: "priya",
      created_at: "2022-09-12T09:05:00+00:00",
    },
    verification: {
      id: 4,
      passed: !failing,
      report: report(failing),
      created_at: "2022-09-12T09:05:00+00:00",
    },
    events: [
      {
        seq: 1,
        type: "case.created",
        actor: "priya",
        payload: {},
        created_at: "2022-09-12T09:00:00+00:00",
        hash: "cd".repeat(32),
        prev_hash: "0".repeat(64),
      },
    ],
    ledger: { valid: true, broken_at: null, reason: null, head: "cd".repeat(32), length: 1 },
    signature: null,
    permissions: {
      edit: true,
      submit: !failing,
      approve: false,
      approve_blockers: ["Only the MLRO approves case files."],
      return: false,
      close: true,
    },
    ...overrides,
  };
}

export const CASE_META = {
  return_reasons: { narrative_unclear: "The narrative needs rewriting" },
  close_reasons: { no_suspicion: "Reviewed: no suspicion after investigation" },
  llm_providers: [],
  offline_only: true,
};

export function job(status: string, id = 5) {
  return {
    id,
    kind: "narrative.draft",
    status,
    attempts: 1,
    progress: status,
    result: null,
    error: status === "failed" ? "RuntimeError: provider down" : null,
    created_at: "2022-09-12T09:00:00+00:00",
    updated_at: "2022-09-12T09:00:01+00:00",
  };
}
