import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { useAlert, useSubgraph } from "../../api/alerts";
import type { DispositionAction, GraphEdge } from "../../api/alerts";
import { useMe } from "../../api/auth";
import { DispositionDialog } from "../../components/DispositionDialog";
import { ErrorState } from "../../components/ErrorState";
import { MoneyFlowGraph } from "../../components/graph/MoneyFlowGraph";
import { Button, Panel, Stamp } from "../../components/ui";
import { cx } from "../../lib/cx";
import { dateTime, money, percent, score, splitAccount, typologyLabel } from "../../lib/format";

import styles from "./InvestigationPage.module.css";

function EdgeTable({
  edges,
  selected,
  onSelect,
  caption,
}: {
  edges: GraphEdge[];
  selected: number | null;
  onSelect: (id: number) => void;
  caption: string;
}) {
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <caption className="srOnly">{caption}</caption>
        <thead>
          <tr>
            <th scope="col">Time</th>
            <th scope="col">From</th>
            <th scope="col">To</th>
            <th scope="col">Amount</th>
            <th scope="col">Format</th>
            <th scope="col">Score</th>
            <th scope="col">Evidence</th>
          </tr>
        </thead>
        <tbody>
          {edges.map((e) => (
            <tr
              key={e.txn_id}
              className={cx(
                e.on_dominant_path && styles.onPath,
                selected === e.txn_id && styles.selected,
              )}
            >
              <td className={styles.mono}>{dateTime(e.ts)}</td>
              <td className={styles.mono}>{splitAccount(e.from).account}</td>
              <td className={styles.mono}>{splitAccount(e.to).account}</td>
              <td className={styles.mono}>{money(e.amount_paid, e.currency_paid)}</td>
              <td>{e.payment_format}</td>
              <td className={styles.mono}>
                {score(e.score)}
                {e.flagged ? <span className="srOnly"> (flagged)</span> : null}
              </td>
              <td>
                <button
                  type="button"
                  className={styles.evidence}
                  onClick={() => {
                    onSelect(e.txn_id);
                  }}
                  aria-pressed={selected === e.txn_id}
                >
                  {e.evidence_id}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function InvestigationPage() {
  const { id = "" } = useParams();
  const alertId = Number(id);
  const alert = useAlert(alertId);
  const graph = useSubgraph(alertId);
  const me = useMe();
  const [view, setView] = useState<"graph" | "table">("graph");
  const [selected, setSelected] = useState<number | null>(null);
  const [dialog, setDialog] = useState<DispositionAction | null>(null);

  const timeline = useMemo(
    () => [...(graph.data?.edges ?? [])].sort((a, b) => a.ts.localeCompare(b.ts)),
    [graph.data],
  );
  const pathEdges = timeline.filter((e) => e.on_dominant_path);
  const canDecide = me.data?.role === "analyst" || me.data?.role === "mlro";

  if (!Number.isInteger(alertId) || alertId <= 0) {
    return <ErrorState error={new Error("Invalid alert id")} />;
  }
  if (alert.isError) return <ErrorState error={alert.error} onRetry={() => void alert.refetch()} />;
  if (alert.isPending) {
    return (
      <p role="status" aria-live="polite">
        Loading alert…
      </p>
    );
  }

  const a = alert.data;
  const { bank, account } = splitAccount(a.account_id);
  return (
    <div className={styles.page}>
      <nav aria-label="Breadcrumb" className={styles.crumbs}>
        <Link to="/queue">Alert queue</Link> / <span aria-current="page">Alert {a.id}</span>
      </nav>
      <header className={styles.header}>
        <div>
          <p className={styles.kicker}>
            Alert {a.id} · {a.alert_date}
          </p>
          <h1 className={styles.title}>
            <span className={styles.mono}>{account}</span>{" "}
            <span className={styles.muted}>bank {bank}</span>
          </h1>
        </div>
        <div className={styles.actions}>
          {a.status === "open" ? (
            <>
              <Button
                disabled={!canDecide}
                title={canDecide ? undefined : "Only analysts and MLROs can decide on alerts"}
                onClick={() => {
                  setDialog("escalate");
                }}
              >
                Escalate
              </Button>
              <Button
                variant="danger"
                disabled={!canDecide}
                title={canDecide ? undefined : "Only analysts and MLROs can decide on alerts"}
                onClick={() => {
                  setDialog("dismiss");
                }}
              >
                Dismiss
              </Button>
            </>
          ) : (
            <>
              <Stamp tone={a.status === "dismissed" ? "verified" : "alert"}>
                {a.status.replace("_", " ")}
              </Stamp>
              {canDecide && a.status !== "in_case" ? (
                <Button
                  variant="ghost"
                  onClick={() => {
                    setDialog("reopen");
                  }}
                >
                  Reopen
                </Button>
              ) : null}
            </>
          )}
        </div>
      </header>

      <div className={styles.grid}>
        <div className={styles.side}>
          <Panel title="Why this is an alert" label="Detect">
            <dl className={styles.stats}>
              <div>
                <dt>Model score</dt>
                <dd className={styles.big}>{score(a.score)}</dd>
              </div>
              <div>
                <dt>Predicted typology</dt>
                <dd>
                  {typologyLabel(a.typology_pred)}{" "}
                  <span className={styles.muted}>({percent(a.typology_conf, 0)} confident)</span>
                </dd>
              </div>
              <div>
                <dt>Riskiest payment</dt>
                <dd className={styles.mono}>{money(a.top_amount, a.top_currency)}</dd>
              </div>
              <div>
                <dt>Payments that day</dt>
                <dd className={styles.mono}>
                  {a.n_flagged} flagged of {a.n_transactions}
                </dd>
              </div>
            </dl>
            <h3 className={styles.subhead}>Top reasons (SHAP)</h3>
            <ol className={styles.reasons}>
              {a.reasons.map((r) => (
                <li key={r.rank}>
                  <span>{r.text}</span>
                  <span className={styles.reasonMeta}>
                    <meter
                      className={cx(styles.meter, r.shap > 0 ? styles.raises : styles.lowers)}
                      min={0}
                      max={Math.max(...a.reasons.map((x) => Math.abs(x.shap)), 1e-9)}
                      value={Math.abs(r.shap)}
                      aria-label={`Contribution ${r.shap.toFixed(3)}`}
                    />
                    <code>{r.evidence_id}</code>
                  </span>
                </li>
              ))}
            </ol>
            <p className={styles.note}>
              SHAP values are the model&apos;s additive contributions for the riskiest payment; a
              reason that raises the score is not proof of laundering.
            </p>
          </Panel>
          {graph.data && graph.data.motif.signals.length > 0 ? (
            <Panel title="Structural signals" label={graph.data.motif.evidence_id}>
              <ul className={styles.signals}>
                {graph.data.motif.signals.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ul>
            </Panel>
          ) : null}
          {a.dispositions.length > 0 ? (
            <Panel title="Decisions" label="Audit trail">
              <ol className={styles.history}>
                {a.dispositions.map((d) => (
                  <li key={d.id}>
                    <span className={styles.mono}>{dateTime(d.created_at)}</span> {d.action} ·{" "}
                    {d.reason_code.replaceAll("_", " ")}
                    {d.note ? <> — {d.note}</> : null}
                  </li>
                ))}
              </ol>
            </Panel>
          ) : null}
        </div>

        <div className={styles.main}>
          <div className={styles.viewToggle} role="group" aria-label="Evidence view">
            <Button
              variant={view === "graph" ? "primary" : "ghost"}
              aria-pressed={view === "graph"}
              onClick={() => {
                setView("graph");
              }}
            >
              Graph
            </Button>
            <Button
              variant={view === "table" ? "primary" : "ghost"}
              aria-pressed={view === "table"}
              onClick={() => {
                setView("table");
              }}
            >
              Table
            </Button>
          </div>
          {graph.isError ? (
            <ErrorState error={graph.error} onRetry={() => void graph.refetch()} />
          ) : null}
          {graph.isPending ? (
            <p role="status" aria-live="polite">
              Building the money-flow graph…
            </p>
          ) : null}
          {graph.data ? (
            <>
              <p className={styles.window}>
                Evidence window {dateTime(graph.data.window.from)} →{" "}
                {dateTime(graph.data.window.to)} (nothing after the alert day is used) ·{" "}
                {graph.data.nodes.length} accounts · {graph.data.edges.length} payments
                {graph.data.truncated ? " · trimmed to the riskiest" : ""}
              </p>
              {view === "graph" ? (
                <MoneyFlowGraph
                  graph={graph.data}
                  selectedTxn={selected}
                  onSelectTxn={setSelected}
                />
              ) : (
                <EdgeTable
                  edges={timeline}
                  selected={selected}
                  onSelect={setSelected}
                  caption="Every payment in the evidence graph, oldest first"
                />
              )}
              <Panel title="Dominant path" label={graph.data.dominant_path.evidence_id}>
                {pathEdges.length > 0 ? (
                  <EdgeTable
                    edges={pathEdges}
                    selected={selected}
                    onSelect={setSelected}
                    caption="Payments on the dominant path, oldest first"
                  />
                ) : (
                  <p>No connected path found around the riskiest payment.</p>
                )}
              </Panel>
            </>
          ) : null}
        </div>
      </div>

      <DispositionDialog
        alertId={dialog ? a.id : null}
        action={dialog ?? "dismiss"}
        onClose={() => {
          setDialog(null);
        }}
      />
    </div>
  );
}
