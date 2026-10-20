import { percent } from "../../lib/format";
import { linear, ticks } from "../../lib/scale";

import { ChartFrame } from "./ChartFrame";
import styles from "./Chart.module.css";

export interface BarRow {
  label: string;
  value: number;
  low?: number | null | undefined;
  high?: number | null | undefined;
  /** Shown after the label, e.g. the support "n=137". */
  note?: string;
}

export interface BarCIProps {
  rows: BarRow[];
  summary: string;
  caption: string;
  valueLabel: string;
  /** Optional reference line, e.g. a target. */
  reference?: { value: number; label: string };
}

const W = 640;
const ROW = 26;
const M = { top: 8, right: 72, bottom: 28, left: 170 };

/** Proportions with their 95% intervals, one bar per row (0–100%). */
export function BarCI({ rows, summary, caption, valueLabel, reference }: BarCIProps) {
  const H = M.top + M.bottom + ROW * rows.length;
  const x = linear([0, 1], [M.left, W - M.right]);
  const chart = (
    <svg
      viewBox={`0 0 ${String(W)} ${String(H)}`}
      className={styles.svg}
      role="img"
      aria-label={`${caption}. ${summary}`}
    >
      {ticks(0, 1, 5).map((t) => (
        <g key={t}>
          <line x1={x(t)} x2={x(t)} y1={M.top} y2={H - M.bottom} className={styles.grid} />
          <text x={x(t)} y={H - 8} textAnchor="middle" className={styles.axisText}>
            {percent(t, 0)}
          </text>
        </g>
      ))}
      {reference ? (
        <g>
          <line
            x1={x(reference.value)}
            x2={x(reference.value)}
            y1={M.top}
            y2={H - M.bottom}
            className={styles.target}
          />
          <text x={x(reference.value) + 4} y={M.top + 10} className={styles.alertText}>
            {reference.label}
          </text>
        </g>
      ) : null}
      {rows.map((r, i) => {
        const y = M.top + i * ROW + 4;
        const mid = y + (ROW - 8) / 2;
        return (
          <g key={r.label}>
            <text x={M.left - 8} y={mid + 4} textAnchor="end" className={styles.barLabel}>
              {r.label}
            </text>
            <rect
              x={M.left}
              y={y}
              width={Math.max(x(r.value) - M.left, 1)}
              height={ROW - 8}
              className={styles.bar}
            />
            {r.low != null && r.high != null ? (
              <line
                x1={x(r.low)}
                x2={x(r.high)}
                y1={mid}
                y2={mid}
                className={styles.whiskerOnBar}
              />
            ) : null}
            <text x={x(Math.max(r.value, r.high ?? 0)) + 6} y={mid + 4} className={styles.barLabel}>
              {percent(r.value)}
            </text>
          </g>
        );
      })}
    </svg>
  );
  const table = (
    <table className={styles.table}>
      <caption className="srOnly">{caption}</caption>
      <thead>
        <tr>
          <th scope="col">Row</th>
          <th scope="col">{valueLabel}</th>
          <th scope="col">95% interval</th>
          <th scope="col">Note</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.label}>
            <th scope="row">{r.label}</th>
            <td className={styles.num}>{percent(r.value)}</td>
            <td className={styles.num}>
              {r.low != null && r.high != null ? `${percent(r.low)}–${percent(r.high)}` : "—"}
            </td>
            <td>{r.note ?? ""}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
  return <ChartFrame summary={summary} chart={chart} table={table} />;
}
