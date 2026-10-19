import type { AlertDetail, AlertSummary, QueueMeta, Subgraph } from "../api/alerts";

export function alertSummary(id: number, overrides: Partial<AlertSummary> = {}): AlertSummary {
  return {
    id,
    account_id: `11:8000${String(id).padStart(5, "0")}`,
    alert_date: "2022-09-09",
    score: 0.9 - id * 0.01,
    score_top3_mean: 0.8,
    calibrated_prob: null,
    typology_pred: "FAN-OUT",
    typology_conf: 0.62,
    top_txn_id: 1000 + id,
    top_amount: 12345.67,
    top_currency: "US Dollar",
    n_transactions: 4,
    n_flagged: 2,
    status: "open",
    ...overrides,
  };
}

export const META: QueueMeta = {
  model: { id: 1, name: "lgbm_champion", dataset: "hi_small", threshold: 0.42, alert_floor: 0.01 },
  days: [
    { date: "2022-09-09", alerts: 3 },
    { date: "2022-09-10", alerts: 1 },
  ],
  by_status: { open: 4 },
  typologies: ["FAN-OUT", "CYCLE"],
  dismiss_reasons: { known_counterparty: "Known, verified counterparty relationship" },
  escalate_reasons: { typology_match: "Matches a known laundering typology" },
};

export function alertDetail(id: number, overrides: Partial<AlertDetail> = {}): AlertDetail {
  return {
    ...alertSummary(id),
    reasons: [
      {
        rank: 1,
        feature: "s_payees_24h",
        value: 9,
        shap: 1.2,
        text: "Sender paid 9 different accounts in the previous 24 hours — raises the risk score",
        evidence_id: `EV-REASON-${String(id)}-1`,
      },
      {
        rank: 2,
        feature: "cross_bank",
        value: 1,
        shap: -0.3,
        text: "Payment crosses banks — lowers the risk score",
        evidence_id: `EV-REASON-${String(id)}-2`,
      },
    ],
    dispositions: [],
    ...overrides,
  };
}

export function subgraph(id: number): Subgraph {
  const edge = (txn: number, from: string, to: string, ts: string, path: boolean) => ({
    evidence_id: `EV-TXN-${String(txn)}`,
    txn_id: txn,
    from,
    to,
    ts,
    amount_paid: 500,
    currency_paid: "Euro",
    amount_received: 500,
    currency_received: "Euro",
    payment_format: "ACH",
    score: path ? 0.9 : 0.1,
    flagged: path,
    on_dominant_path: path,
  });
  return {
    alert_id: id,
    window: { from: "2022-09-03T00:00:00", to: "2022-09-10T00:00:00" },
    center: "11:800000001",
    nodes: [
      { id: "11:800000001", is_center: true, max_score: 0.9, degree: 2 },
      { id: "11:800000002", is_center: false, max_score: 0.9, degree: 1 },
      { id: "12:800000003", is_center: false, max_score: 0.1, degree: 1 },
    ],
    edges: [
      edge(1001, "11:800000002", "11:800000001", "2022-09-09T01:00:00", true),
      edge(1002, "11:800000001", "12:800000003", "2022-09-09T02:00:00", false),
    ],
    dominant_path: {
      evidence_id: `EV-PATH-${String(id)}`,
      txn_ids: [1001],
      evidence_ids: ["EV-TXN-1001"],
    },
    motif: {
      evidence_id: `EV-MOTIF-${String(id)}`,
      signals: ["sender fanned out to 9 payees in 24 h"],
    },
    truncated: false,
  };
}
