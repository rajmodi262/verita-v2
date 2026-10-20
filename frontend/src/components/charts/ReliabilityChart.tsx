import { percent } from "../../lib/format";
import { linear, linePath, niceMax, ticks } from "../../lib/scale";

import { ChartFrame, LegendItem } from "./ChartFrame";
import styles from "./Chart.module.css";

export interface ReliabilityBin {
  mean_predicted: number;
  observed_rate: number;
  low: number;
  high: number;
  n: number;
}

const W = 640;
const H = 300;
const M = { top: 16, right: 16, bottom: 40, left: 56 };

/** Predicted vs observed laundering rate in equal-mass bins, before and after calibration. */
export function ReliabilityChart({
  before,
  after,
  eceBefore,
  eceAfter,
}: {
  before: ReliabilityBin[];
  after: ReliabilityBin[];
  eceBefore: number;
  eceAfter: number;
}) {
  // Rates are tiny at fraud base rates; zoom the axes to the data instead of 0–1.
  const top = niceMax(
    Math.max(0.001, ...[...before, ...after].flatMap((b) => [b.mean_predicted, b.high])),
    4,
  );
  const x = linear([0, top], [M.left, W - M.right]);
  const y = linear([0, top], [H - M.bottom, M.top]);
  const summary = `Isotonic calibration moves the points onto the diagonal: expected calibration error falls from ${eceBefore.toFixed(4)} to ${eceAfter.toFixed(4)} on the test split.`;
  const dots = (bins: ReliabilityBin[], cls: string | undefined) =>
    bins.map((b, i) => (
      <g key={i}>
        <line
          x1={x(b.mean_predicted)}
          x2={x(b.mean_predicted)}
          y1={y(b.low)}
          y2={y(b.high)}
          className={styles.whisker}
        />
        <circle cx={x(b.mean_predicted)} cy={y(b.observed_rate)} r={4.5} className={cls} />
      </g>
    ));
  const chart = (
    <svg
      viewBox={`0 0 ${String(W)} ${String(H)}`}
      className={styles.svg}
      role="img"
      aria-label={`Reliability diagram. ${summary}`}
    >
      {ticks(0, top, 4).map((t) => (
        <g key={t}>
          <line x1={M.left} x2={W - M.right} y1={y(t)} y2={y(t)} className={styles.grid} />
          <text x={M.left - 8} y={y(t) + 4} textAnchor="end" className={styles.axisText}>
            {percent(t, 2)}
          </text>
          <text x={x(t)} y={H - M.bottom + 16} textAnchor="middle" className={styles.axisText}>
            {percent(t, 2)}
          </text>
        </g>
      ))}
      <text
        x={(M.left + W - M.right) / 2}
        y={H - 4}
        textAnchor="middle"
        className={styles.axisTitle}
      >
        Predicted probability
      </text>
      <path
        d={linePath([
          [x(0), y(0)],
          [x(top), y(top)],
        ])}
        className={styles.target}
      />
      {dots(before, styles.dotAci)}
      {dots(after, styles.dotStatic)}
    </svg>
  );
  const table = (
    <table className={styles.table}>
      <caption className="srOnly">Reliability bins before and after calibration</caption>
      <thead>
        <tr>
          <th scope="col">Bin</th>
          <th scope="col">Raw: predicted → observed</th>
          <th scope="col">Calibrated: predicted → observed (95% CI)</th>
          <th scope="col">n</th>
        </tr>
      </thead>
      <tbody>
        {after.map((b, i) => {
          const raw = before[i];
          return (
            <tr key={i}>
              <th scope="row">{i + 1}</th>
              <td className={styles.num}>
                {raw ? `${percent(raw.mean_predicted, 3)} → ${percent(raw.observed_rate, 3)}` : "—"}
              </td>
              <td className={styles.num}>
                {percent(b.mean_predicted, 3)} → {percent(b.observed_rate, 3)} ({percent(b.low, 3)}–
                {percent(b.high, 3)})
              </td>
              <td className={styles.num}>{b.n.toLocaleString("en-US")}</td>
            </tr>
          );
        })}
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
          <LegendItem kind="dotAci">Raw model score</LegendItem>
          <LegendItem kind="dotStatic">After isotonic calibration</LegendItem>
          <LegendItem kind="target">Perfect calibration</LegendItem>
        </>
      }
    />
  );
}
