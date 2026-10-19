import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { useAlertQueue, useQueueMeta } from "../../api/alerts";
import { useLatestPlan } from "../../api/capacity";
import type { AlertSummary, DispositionAction } from "../../api/alerts";
import { ApiError } from "../../api/client";
import { DispositionDialog } from "../../components/DispositionDialog";
import { ErrorState } from "../../components/ErrorState";
import { KeyboardHelp } from "../../components/KeyboardHelp";
import { Button, EmptyState, Select, Stamp } from "../../components/ui";
import { cx } from "../../lib/cx";
import { money, percent, score, splitAccount, typologyLabel } from "../../lib/format";

import styles from "./QueuePage.module.css";

const STATUS_OPTIONS = [
  { value: "open", label: "Open" },
  { value: "escalated", label: "Escalated" },
  { value: "dismissed", label: "Dismissed" },
  { value: "in_case", label: "In a case" },
];

export const QUEUE_SHORTCUTS = [
  ["J / ↓", "Next alert"],
  ["K / ↑", "Previous alert"],
  ["Enter", "Open the investigation"],
  ["E", "Escalate"],
  ["D", "Dismiss"],
  ["?", "Show this help"],
] as const;

/** The MLRO's saved staffing plan for the filtered day, so analysts work to the same plan. */
function DayPlan({ date }: { date: string }) {
  const latest = useLatestPlan(date);
  if (!latest.data) return null;
  const p = latest.data;
  return (
    <p className={styles.plan}>
      <Stamp tone="verified">Plan</Stamp> {date}: {p.analysts} analysts reviewing the top{" "}
      {p.selected_alert_ids.length.toLocaleString("en-US")} alerts at a {percent(1 - p.alpha, 0)}{" "}
      recall guarantee (plan #{p.id}).{" "}
      <Link to={`/capacity?date=${date}&analysts=${String(p.analysts)}&alpha=${String(p.alpha)}`}>
        Open in the planner
      </Link>
    </p>
  );
}

export default function QueuePage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const filters = {
    date: params.get("date") ?? undefined,
    status: params.get("status") ?? "open",
    typology: params.get("typology") ?? undefined,
  };
  const meta = useQueueMeta();
  const queue = useAlertQueue(filters);
  const rows = useMemo(() => queue.data?.pages.flatMap((p) => p.items) ?? [], [queue.data]);
  const total = queue.data?.pages[0]?.total ?? 0;
  const [selected, setSelected] = useState(0);
  const [dialog, setDialog] = useState<{ id: number; action: DispositionAction } | null>(null);
  const [help, setHelp] = useState(false);
  const linkRefs = useRef<(HTMLAnchorElement | null)[]>([]);
  const dialogOpen = dialog !== null || help;

  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
    setSelected(0);
  };

  const focusRow = useCallback((index: number) => {
    setSelected(index);
    linkRefs.current[index]?.focus();
  }, []);

  const current: AlertSummary | undefined = rows[selected];

  // Page-level shortcuts (like a mail client): active unless typing in a field or a dialog is open.
  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing = target?.closest("input, select, textarea, [contenteditable]") !== null;
      if (typing || dialogOpen || event.metaKey || event.ctrlKey || event.altKey) return;
      const key = event.key;
      if (key === "j" || key === "ArrowDown") {
        event.preventDefault();
        focusRow(Math.min(selected + 1, rows.length - 1));
      } else if (key === "k" || key === "ArrowUp") {
        event.preventDefault();
        focusRow(Math.max(selected - 1, 0));
      } else if (
        key === "Enter" &&
        current &&
        target.tagName !== "A" &&
        target.tagName !== "BUTTON"
      ) {
        void navigate(`/alerts/${String(current.id)}`);
      } else if ((key === "e" || key === "d") && current?.status === "open") {
        setDialog({ id: current.id, action: key === "e" ? "escalate" : "dismiss" });
      } else if (key === "?") {
        setHelp(true);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
    };
  }, [current, dialogOpen, focusRow, navigate, rows.length, selected]);

  if (meta.isError) {
    const noModel = meta.error instanceof ApiError && meta.error.slug === "no-model";
    return noModel ? (
      <EmptyState title="No alerts loaded yet">
        <p>
          Train the detector and load alerts with <code>verita detect alerts</code>.
        </p>
      </EmptyState>
    ) : (
      <ErrorState error={meta.error} onRetry={() => void meta.refetch()} />
    );
  }

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <h1>Alert queue</h1>
          <p className={styles.sub}>
            {meta.data ? (
              <>
                Model <code>{meta.data.model.name}</code> on {meta.data.model.dataset} · flagged at
                score ≥ <code>{score(meta.data.model.threshold)}</code> · out-of-sample test window
              </>
            ) : (
              "Loading model…"
            )}
          </p>
        </div>
        <Button
          variant="ghost"
          onClick={() => {
            setHelp(true);
          }}
        >
          Shortcuts (?)
        </Button>
      </header>
      {filters.date ? <DayPlan date={filters.date} /> : null}

      <div className={styles.filters}>
        <Select
          label="Day"
          placeholder="All days"
          options={(meta.data?.days ?? []).map((d) => ({
            value: d.date,
            label: `${d.date} (${d.alerts.toLocaleString()})`,
          }))}
          value={filters.date ?? ""}
          onChange={(e) => {
            setFilter("date", e.target.value);
          }}
        />
        <Select
          label="Status"
          placeholder="Any status"
          options={STATUS_OPTIONS}
          value={filters.status}
          onChange={(e) => {
            setFilter("status", e.target.value);
          }}
        />
        <Select
          label="Predicted typology"
          placeholder="Any typology"
          options={(meta.data?.typologies ?? []).map((t) => ({
            value: t,
            label: typologyLabel(t),
          }))}
          value={filters.typology ?? ""}
          onChange={(e) => {
            setFilter("typology", e.target.value);
          }}
        />
      </div>

      {queue.isError ? (
        <ErrorState error={queue.error} onRetry={() => void queue.refetch()} />
      ) : null}
      {queue.isPending ? (
        <p role="status" aria-live="polite">
          Loading alerts…
        </p>
      ) : null}
      {queue.isSuccess && rows.length === 0 ? (
        <EmptyState title="No alerts match">
          <p>Change the day, status or typology filter.</p>
        </EmptyState>
      ) : null}

      {rows.length > 0 ? (
        <>
          <p className={styles.count} aria-live="polite">
            Showing {rows.length.toLocaleString()} of {total.toLocaleString()} alerts, riskiest
            first
          </p>
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <caption className="srOnly">
                Alert queue. Use J and K to move, Enter to open, E to escalate, D to dismiss.
              </caption>
              <thead>
                <tr>
                  <th scope="col">#</th>
                  <th scope="col">Score</th>
                  <th scope="col">Account</th>
                  <th scope="col">Day</th>
                  <th scope="col">Typology (predicted)</th>
                  <th scope="col">Riskiest payment</th>
                  <th scope="col">Flagged / payments</th>
                  <th scope="col">Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((a, i) => {
                  const { bank, account } = splitAccount(a.account_id);
                  return (
                    <tr
                      key={a.id}
                      aria-selected={i === selected}
                      className={cx(styles.row, i === selected && styles.selected)}
                    >
                      <td className={styles.mono}>{i + 1}</td>
                      <td>
                        <span className={styles.scoreCell}>
                          <span className={styles.mono}>{score(a.score)}</span>
                          <meter
                            className={styles.meter}
                            min={0}
                            max={1}
                            value={a.score}
                            aria-label={`Score ${score(a.score)}`}
                          />
                        </span>
                      </td>
                      <td className={styles.mono}>
                        <Link
                          ref={(el) => {
                            linkRefs.current[i] = el;
                          }}
                          to={`/alerts/${String(a.id)}`}
                          className={styles.link}
                          onFocus={() => {
                            setSelected(i);
                          }}
                        >
                          {account}
                        </Link>
                        <span className={styles.bank}> bank {bank}</span>
                      </td>
                      <td className={styles.mono}>{a.alert_date}</td>
                      <td>
                        {typologyLabel(a.typology_pred)}{" "}
                        <span className={styles.muted}>{percent(a.typology_conf, 0)}</span>
                      </td>
                      <td className={styles.mono}>{money(a.top_amount, a.top_currency)}</td>
                      <td className={styles.mono}>
                        {a.n_flagged} / {a.n_transactions}
                      </td>
                      <td>{a.status.replace("_", " ")}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {queue.hasNextPage ? (
            <Button
              variant="ghost"
              busy={queue.isFetchingNextPage}
              onClick={() => void queue.fetchNextPage()}
            >
              Load the next {Math.min(100, total - rows.length)} alerts
            </Button>
          ) : null}
        </>
      ) : null}

      <DispositionDialog
        alertId={dialog?.id ?? null}
        action={dialog?.action ?? "dismiss"}
        onClose={() => {
          setDialog(null);
        }}
      />
      <KeyboardHelp
        open={help}
        onClose={() => {
          setHelp(false);
        }}
        shortcuts={QUEUE_SHORTCUTS}
      />
    </div>
  );
}
