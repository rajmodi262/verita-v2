import type { PlanPoint } from "../../api/capacity";
import { compact, integer, percent, usd } from "../../lib/format";
import { bandPath, linePath, linear, ticks } from "../../lib/scale";

import { ChartFrame, LegendItem } from "./ChartFrame";
import styles from "./Chart.module.css";

const W = 640;
const H = 260;
const M = { top: 24, right: 16, bottom: 40, left: 52 };

export interface FrontierChartProps {
  points: PlanPoint[];
  analysts: number;
  targetRecall: number;
}

/** Expected recall (band) and value recall against analysts on duty, one replay day. */
export function FrontierChart({ points, analysts, targetRecall }: FrontierChartProps) {
  const first = points[0];
  const last = points[points.length - 1];
  if (!first || !last) return null;
  const x = linear([first.analysts, last.analysts], [M.left, W - M.right]);
  const y = linear([0, 1], [H - M.bottom, M.top]);
  const xs = points.map((p) => x(p.analysts));
  const needed = first.guarantee.analysts_needed;
  const feasibleInRange = needed <= last.analysts;
  const current = points.find((p) => p.analysts === analysts);

  const summary = feasibleInRange
    ? `The ${percent(targetRecall, 0)} recall guarantee becomes feasible at ${String(needed)} analysts.`
    : `The ${percent(targetRecall, 0)} recall guarantee needs ${integer(needed)} analysts on this day — beyond the ${String(last.analysts)} this chart covers. Expected recall at ${String(last.analysts)} analysts is ${percent(last.expected_recall.value)}.`;

  const chart = (
    <svg
      viewBox={`0 0 ${String(W)} ${String(H)}`}
      className={styles.svg}
      role="img"
      aria-label={`Staffing frontier. ${summary}`}
    >
      {ticks(0, 1, 5).map((t) => (
        <g key={t}>
          <line x1={M.left} x2={W - M.right} y1={y(t)} y2={y(t)} className={styles.grid} />
          <text x={M.left - 8} y={y(t) + 4} textAnchor="end" className={styles.axisText}>
            {percent(t, 0)}
          </text>
        </g>
      ))}
      {points.map((p) => (
        <text
          key={p.analysts}
          x={x(p.analysts)}
          y={H - M.bottom + 16}
          textAnchor="middle"
          className={styles.axisText}
        >
          {p.analysts % 2 === 1 || points.length <= 12 ? String(p.analysts) : ""}
        </text>
      ))}
      <text
        x={(M.left + W - M.right) / 2}
        y={H - 4}
        textAnchor="middle"
        className={styles.axisTitle}
      >
        Analysts on duty
      </text>
      <line
        x1={M.left}
        x2={W - M.right}
        y1={y(targetRecall)}
        y2={y(targetRecall)}
        className={styles.target}
      />
      <text x={W - M.right} y={y(targetRecall) - 6} textAnchor="end" className={styles.alertText}>
        TARGET {percent(targetRecall, 0)}
      </text>
      <path
        d={bandPath(
          xs,
          points.map((p) => y(p.expected_recall.high)),
          points.map((p) => y(p.expected_recall.low)),
        )}
        className={styles.band80}
      />
      <path
        d={linePath(points.map((p, i) => [xs[i] ?? 0, y(p.expected_recall.value)] as const))}
        className={styles.primary}
      />
      <path
        d={linePath(points.map((p, i) => [xs[i] ?? 0, y(p.value_recall)] as const))}
        className={styles.secondary}
      />
      {feasibleInRange ? (
        <g>
          <line
            x1={x(needed)}
            x2={x(needed)}
            y1={M.top}
            y2={H - M.bottom}
            className={styles.feasible}
          />
          <text x={x(needed) + 6} y={M.top + 12} className={styles.feasibleText}>
            GUARANTEE HOLDS
          </text>
        </g>
      ) : (
        <text x={M.left + 8} y={y(0.75)} className={styles.alertText}>
          GUARANTEE NEEDS {compact(needed)} ANALYSTS
        </text>
      )}
      {current ? (
        <g>
          <line
            x1={x(current.analysts)}
            x2={x(current.analysts)}
            y1={M.top}
            y2={H - M.bottom}
            className={styles.marker}
          />
          <circle
            cx={x(current.analysts)}
            cy={y(current.expected_recall.value)}
            r={6}
            className={styles.markerDot}
          />
        </g>
      ) : null}
    </svg>
  );

  const table = (
    <table className={styles.table}>
      <caption className="srOnly">Staffing frontier by analysts on duty</caption>
      <thead>
        <tr>
          <th scope="col">Analysts</th>
          <th scope="col">Reviewed</th>
          <th scope="col">Expected recall (95% interval)</th>
          <th scope="col">Value recall</th>
          <th scope="col">Expected missed value</th>
          <th scope="col">Review cost</th>
          <th scope="col">Guarantee</th>
        </tr>
      </thead>
      <tbody>
        {points.map((p) => (
          <tr key={p.analysts} className={p.analysts === analysts ? styles.current : undefined}>
            <td className={styles.num}>{p.analysts}</td>
            <td className={styles.num}>
              {integer(p.reviewed)} / {integer(p.alerts)}
            </td>
            <td className={styles.num}>
              {percent(p.expected_recall.value)} ({percent(p.expected_recall.low)}–
              {percent(p.expected_recall.high)})
            </td>
            <td className={styles.num}>{percent(p.value_recall)}</td>
            <td className={styles.num}>{usd(p.expected_missed_value_usd)}</td>
            <td className={styles.num}>{usd(p.review_cost_usd)}</td>
            <td>{p.guarantee.feasible ? "Holds" : "Infeasible"}</td>
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
          <LegendItem kind="primary">Expected recall (cases), with 95% band</LegendItem>
          <LegendItem kind="secondary">Value recall (USD)</LegendItem>
          <LegendItem kind="target">Recall target</LegendItem>
        </>
      }
    />
  );
}
