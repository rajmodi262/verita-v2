import type { Staffing } from "../../api/capacity";
import { compact, integer } from "../../lib/format";

import { ChartFrame, LegendItem } from "./ChartFrame";
import styles from "./Chart.module.css";

const W = 640;
const ROW = 26;
const M = { top: 8, right: 64, bottom: 8, left: 64 };

export interface StaffingBarsProps {
  staffing: Staffing;
  /** The most analysts the operation can field (configs/operations.yaml). */
  maxAnalysts: number;
  targetLabel: string;
}

/** Analysts each replay day needs to keep the guarantee, on a log scale (it spans 1 to 10³+). */
export function StaffingBars({ staffing, maxAnalysts, targetLabel }: StaffingBarsProps) {
  const days = staffing.days;
  const H = M.top + M.bottom + ROW * days.length;
  const top = Math.max(maxAnalysts, ...days.map((d) => d.analysts_needed), 10);
  const logMax = Math.log10(top);
  const width = (n: number) =>
    ((W - M.left - M.right) * Math.log10(Math.max(n, 1) + 1)) / (logMax + Math.log10(2));
  const capacityX = M.left + width(maxAnalysts);
  const over = days.filter((d) => d.analysts_needed > maxAnalysts);

  const summary = over.length
    ? `On ${String(over.length)} of ${String(days.length)} days the ${targetLabel} guarantee needs more than the ${String(maxAnalysts)} analysts available — up to ${integer(Math.max(...over.map((d) => d.analysts_needed)))}.`
    : `Every day's ${targetLabel} guarantee fits within ${String(maxAnalysts)} analysts.`;

  const chart = (
    <svg
      viewBox={`0 0 ${String(W)} ${String(H)}`}
      className={styles.svg}
      role="img"
      aria-label={`Analysts needed per day. ${summary}`}
    >
      {days.map((d, i) => {
        const yTop = M.top + i * ROW + 4;
        const exceeds = d.analysts_needed > maxAnalysts;
        return (
          <g key={d.day}>
            <text x={M.left - 8} y={yTop + 13} textAnchor="end" className={styles.axisText}>
              {d.day.slice(5)}
            </text>
            <rect
              x={M.left}
              y={yTop}
              width={Math.max(width(d.analysts_needed), 2)}
              height={ROW - 8}
              className={exceeds ? styles.barOver : styles.bar}
            />
            <text
              x={M.left + width(d.analysts_needed) + 6}
              y={yTop + 13}
              className={exceeds ? styles.alertText : styles.barLabel}
            >
              {compact(d.analysts_needed)}
              {exceeds ? " ✗" : " ✓"}
            </text>
          </g>
        );
      })}
      <line
        x1={capacityX}
        x2={capacityX}
        y1={M.top}
        y2={H - M.bottom}
        className={styles.capacity}
      />
    </svg>
  );

  const table = (
    <table className={styles.table}>
      <caption className="srOnly">Analysts needed per day for the guarantee</caption>
      <thead>
        <tr>
          <th scope="col">Day</th>
          <th scope="col">Alerts in queue</th>
          <th scope="col">Alerts the guarantee requires</th>
          <th scope="col">Analysts needed</th>
          <th scope="col">Within capacity</th>
        </tr>
      </thead>
      <tbody>
        {days.map((d) => (
          <tr key={d.day}>
            <th scope="row" className={styles.num}>
              {d.day}
            </th>
            <td className={styles.num}>{integer(d.alerts)}</td>
            <td className={styles.num}>{integer(d.required_alerts)}</td>
            <td className={styles.num}>{integer(d.analysts_needed)}</td>
            <td>{d.analysts_needed <= maxAnalysts ? "Yes" : "No"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );

  return (
    <ChartFrame
      summary={summary}
      chart={chart}
      table={table}
      legend={
        <>
          <LegendItem kind="capacity">{`Capacity: ${String(maxAnalysts)} analysts`}</LegendItem>
          <span>Log scale; ✗ marks a day the guarantee cannot be staffed.</span>
        </>
      }
    />
  );
}
