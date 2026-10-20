import { useState } from "react";

import { useMe } from "../../api/auth";
import { useModel, useModelAction, useModels } from "../../api/models";
import type { Gate, ModelDetail } from "../../api/models";
import { ErrorState } from "../../components/ErrorState";
import { Button, Panel, Stamp } from "../../components/ui";
import { cx } from "../../lib/cx";
import { dateTime } from "../../lib/format";

import styles from "./GovernancePage.module.css";

/** Plain-language names for the policy gates (gate names from verita/ml/validation.py). */
const GATE_LABELS: Record<string, string> = {
  f1_ci_low: "Detects laundering — lower bound of the F1 interval",
  beats_incumbent: "Beats the rules incumbent outright",
  seed_stability: "Stable across training seeds",
  calibration: "Calibrated probabilities",
  leakage_label_shuffle: "No leakage — shuffled labels collapse",
  drift: "Feature drift within tolerance",
  typology_coverage: "Every common typology measured",
};

function show(v: unknown): string {
  if (typeof v === "number") return Number.isInteger(v) ? v.toLocaleString() : v.toFixed(4);
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (v === null || v === undefined) return "—";
  return typeof v === "string" ? v : JSON.stringify(v);
}

function Lifecycle({ m }: { m: ModelDetail }) {
  const validated = m.validation !== null;
  const stages = [
    {
      key: "candidate",
      title: "Candidate",
      detail: `Proposed ${dateTime(m.created_at)}`,
      done: true,
    },
    {
      key: "validated",
      title: "Validated",
      detail: validated
        ? m.validation?.passed
          ? "All gates passed"
          : `${String(m.validation?.failed_gates.length)} gate(s) failed`
        : "Awaiting the validator",
      done: validated,
      bad: validated && m.validation?.passed === false,
    },
    {
      key: "approved",
      title: "Approved",
      detail: m.approved_at
        ? `Validator #${String(m.approved_by_id)} · ${dateTime(m.approved_at)}`
        : "Needs a validator",
      done: m.approved_at !== null,
    },
    {
      key: "champion",
      title: "In service",
      detail: m.is_champion
        ? m.promoted_at
          ? `MLRO #${String(m.promoted_by_id)} · ${dateTime(m.promoted_at)}`
          : "Seated by the pipeline"
        : "Needs a different MLRO",
      done: m.is_champion,
    },
  ];
  return (
    <ol className={styles.lane} aria-label="Model lifecycle">
      {stages.map((s) => (
        <li key={s.key} className={cx(styles.stage, s.done && styles.done, s.bad && styles.bad)}>
          <span className={styles.node} aria-hidden="true" />
          <span className={styles.stageTitle}>{s.title}</span>
          <span className={styles.stageDetail}>{s.detail}</span>
        </li>
      ))}
    </ol>
  );
}

function Certificate({ g }: { g: Gate }) {
  return (
    <li className={g.passed ? styles.cert : styles.certBad}>
      <p className={styles.certTitle}>{GATE_LABELS[g.gate] ?? g.gate}</p>
      <p className={styles.certFigures}>
        <span>
          measured <strong>{show(g.value)}</strong>
        </span>
        <span>limit {show(g.limit)}</span>
      </p>
      <p className={styles.certRule}>{g.rule}</p>
      <span className={styles.certStamp}>
        <Stamp tone={g.passed ? "verified" : "alert"}>{g.passed ? "Passed" : "Failed"}</Stamp>
      </span>
    </li>
  );
}

function Actions({ m }: { m: ModelDetail }) {
  const me = useMe();
  const validate = useModelAction(m.id, "validate");
  const approve = useModelAction(m.id, "approve");
  const promote = useModelAction(m.id, "promote");
  const role = me.data?.role;
  const busy = validate.isPending || approve.isPending || promote.isPending;
  const error = validate.error ?? approve.error ?? promote.error;
  return (
    <div className={styles.actions}>
      <Button
        disabled={role !== "validator" || busy}
        onClick={() => {
          validate.mutate(null);
        }}
      >
        Run validation
      </Button>
      <Button
        disabled={role !== "validator" || busy || m.status !== "candidate" || !m.validation?.passed}
        onClick={() => {
          approve.mutate(null);
        }}
      >
        Approve
      </Button>
      <Button
        disabled={role !== "mlro" || busy || m.status !== "approved"}
        onClick={() => {
          promote.mutate(null);
        }}
      >
        Promote to service
      </Button>
      <p className={styles.duty}>
        Separation of duties: a validator validates and approves; a <em>different</em> MLRO puts the
        model into service. The database refuses a champion that skipped either step.
      </p>
      {error ? <ErrorState error={error} /> : null}
    </div>
  );
}

export default function GovernancePage() {
  const models = useModels();
  const [picked, setPicked] = useState<number | null>(null);
  const id = picked ?? models.data?.items[0]?.id ?? null;
  const detail = useModel(id);

  if (models.isError)
    return <ErrorState error={models.error} onRetry={() => void models.refetch()} />;
  const m = detail.data;
  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h1>Model governance</h1>
        <p className={styles.lede}>
          No model reaches the alert queue on a data scientist&apos;s say-so: it passes the written
          policy gates, then an independent validator approves it and a different MLRO promotes it.
        </p>
      </header>
      <div className={styles.layout}>
        <Panel title="Versions" label="Register">
          <ul className={styles.versions}>
            {(models.data?.items ?? []).map((v) => (
              <li key={v.id}>
                <button
                  type="button"
                  className={styles.version}
                  aria-pressed={v.id === id}
                  onClick={() => {
                    setPicked(v.id);
                  }}
                >
                  <span className={styles.versionName}>
                    #{v.id} {v.name}
                  </span>
                  <span className={styles.versionMeta}>
                    {v.dataset} · {v.status}
                    {v.governance === "bypassed" ? " · bypassed" : ""}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </Panel>
        {m ? (
          <div className={styles.detail}>
            <Panel title={`${m.name} · ${m.dataset}`} label={`Model version #${String(m.id)}`}>
              <Lifecycle m={m} />
              {m.bypass_reason ? (
                <p className={styles.bypass}>
                  <Stamp tone="alert">Not independently reviewed</Stamp> {m.bypass_reason}
                </p>
              ) : null}
              <dl className={styles.facts}>
                <div>
                  <dt>Artifact SHA-256</dt>
                  <dd className={styles.mono}>{m.champion_sha256.slice(0, 24)}…</dd>
                </div>
                <div>
                  <dt>Validation report SHA-256</dt>
                  <dd className={styles.mono}>
                    {m.validation?.sha256 ? `${m.validation.sha256.slice(0, 24)}…` : "—"}
                  </dd>
                </div>
                <div>
                  <dt>Alert threshold</dt>
                  <dd className={styles.mono}>{m.threshold.toFixed(3)}</dd>
                </div>
              </dl>
              <Actions m={m} />
            </Panel>
            <Panel title="Policy gates" label="Certificates">
              {m.report ? (
                <ul className={styles.certs}>
                  {m.report.gates.map((g) => (
                    <Certificate key={g.gate} g={g} />
                  ))}
                </ul>
              ) : (
                <p>
                  Not validated yet — a validator runs the gates from the pipeline&apos;s own
                  artifacts.
                </p>
              )}
            </Panel>
          </div>
        ) : (
          <p aria-busy="true">Loading…</p>
        )}
      </div>
    </div>
  );
}
