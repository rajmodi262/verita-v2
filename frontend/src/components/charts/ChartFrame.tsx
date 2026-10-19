import { useId, useState } from "react";
import type { ReactNode } from "react";

import styles from "./Chart.module.css";

export interface ChartFrameProps {
  /** One-sentence takeaway, read before the chart (and by screen readers). */
  summary: string;
  chart: ReactNode;
  table: ReactNode;
  legend?: ReactNode;
}

/** Every chart has a tabular twin (PIVOT §13.7); the toggle state is per chart. */
export function ChartFrame({ summary, chart, table, legend }: ChartFrameProps) {
  const [view, setView] = useState<"chart" | "table">("chart");
  const summaryId = useId();
  return (
    <figure className={styles.frame} aria-describedby={summaryId}>
      <div className={styles.toolbar}>
        <p id={summaryId} className={styles.summary}>
          {summary}
        </p>
        <div className={styles.toggle} role="group" aria-label="View as">
          <button
            type="button"
            aria-pressed={view === "chart"}
            onClick={() => {
              setView("chart");
            }}
          >
            Chart
          </button>
          <button
            type="button"
            aria-pressed={view === "table"}
            onClick={() => {
              setView("table");
            }}
          >
            Table
          </button>
        </div>
      </div>
      {view === "chart" ? (
        <>
          {chart}
          {legend ? <div className={styles.legend}>{legend}</div> : null}
        </>
      ) : (
        <div className={styles.tableWrap}>{table}</div>
      )}
    </figure>
  );
}

export function LegendItem({ kind, children }: { kind: string; children: string }) {
  return (
    <span className={styles.legendItem}>
      <svg width="24" height="12" aria-hidden="true" className={styles.swatch}>
        {kind.startsWith("band") ? (
          <rect x="0" y="0" width="24" height="12" className={styles[kind]} />
        ) : kind.startsWith("dot") ? (
          <circle cx="12" cy="6" r="4.5" className={styles[kind]} />
        ) : (
          <line x1="0" y1="6" x2="24" y2="6" className={styles[kind]} />
        )}
      </svg>
      {children}
    </span>
  );
}
