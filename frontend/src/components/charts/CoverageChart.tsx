import type { ReplayRun } from "../../api/capacity";
import { integer, percent } from "../../lib/format";
import { linear, ticks } from "../../lib/scale";

import { ChartFrame, LegendItem } from "./ChartFrame";
import styles from "./Chart.module.css";

const W = 640;
const H = 240;
const M = { top: 16, right: 16, bottom: 36, left: 52 };

export interface CoverageChartProps {
  staticRun: ReplayRun;
  aciRun: ReplayRun;
  targetRecall: number;
  tailDays: string[];
}

/** "Was the guarantee kept?" — realised recall per replay day, static vs adaptive conformal. */
export function CoverageChart({ staticRun, aciRun, targetRecall, tailDays }: CoverageChartProps) {
  const days = staticRun.by_day.filter((d) => d.positives > 0).map((d) => d.day);
  const aciByDay = new Map(aciRun.by_day.map((d) => [d.day, d]));
  const lows = [
    ...staticRun.by_day.map((d) => d.recall.low),
    ...aciRun.by_day.map((d) => d.recall.low),
    targetRecall,
  ].filter((v) => v > 0);
  const floor = Math.max(0, Math.floor((Math.min(...lows) - 0.02) * 20) / 20);
  const step = (W - M.left - M.right) / Math.max(days.length, 1);
  const x = (i: number) => M.left + step * (i + 0.5);
  const y = linear([floor, 1], [H - M.bottom, M.top]);
  const s = staticRun.overall;
  const a = aciRun.overall;
  const saved = s.reviewed > 0 ? 1 - a.reviewed / s.reviewed : 0;
  const holds = (r: { recall: { value: number } }) => r.recall.value >= targetRecall;

  const summary = `Over the test replay, the static guarantee realised ${percent(s.recall.value)} recall (target ${percent(targetRecall, 0)}, ${holds(s) ? "kept" : "missed"}); adaptive conformal realised ${percent(a.recall.value)} (${holds(a) ? "kept" : "missed"}) while reviewing ${percent(Math.abs(saved))} ${saved >= 0 ? "fewer" : "more"} alerts.`;

  const chart = (
    <svg
      viewBox={`0 0 ${String(W)} ${String(H)}`}
      className={styles.svg}
      role="img"
      aria-label={`Guarantee coverage by day. ${summary}`}
    >
      {ticks(floor, 1, 4).map((t) => (
        <g key={t}>
          <line x1={M.left} x2={W - M.right} y1={y(t)} y2={y(t)} className={styles.grid} />
          <text x={M.left - 8} y={y(t) + 4} textAnchor="end" className={styles.axisText}>
            {percent(t, 0)}
          </text>
        </g>
      ))}
      <line
        x1={M.left}
        x2={W - M.right}
        y1={y(targetRecall)}
        y2={y(targetRecall)}
        className={styles.target}
      />
      {days.map((day, i) => {
        const st = staticRun.by_day.find((d) => d.day === day);
        const ac = aciByDay.get(day);
        const cx = x(i);
        return (
          <g key={day}>
            {st ? (
              <>
                <line
                  x1={cx - 6}
                  x2={cx - 6}
                  y1={y(st.recall.low)}
                  y2={y(st.recall.high)}
                  className={styles.whisker}
                />
                <circle cx={cx - 6} cy={y(st.recall.value)} r={4.5} className={styles.dotStatic} />
              </>
            ) : null}
            {ac ? (
              <>
                <line
                  x1={cx + 6}
                  x2={cx + 6}
                  y1={y(ac.recall.low)}
                  y2={y(ac.recall.high)}
                  className={styles.whisker}
                />
                <circle cx={cx + 6} cy={y(ac.recall.value)} r={4.5} className={styles.dotAci} />
              </>
            ) : null}
            <text x={cx} y={H - M.bottom + 16} textAnchor="middle" className={styles.axisText}>
              {day.slice(5)}
              {tailDays.includes(day) ? "*" : ""}
            </text>
          </g>
        );
      })}
    </svg>
  );

  const table = (
    <table className={styles.table}>
      <caption className="srOnly">Realised recall by day, static and adaptive conformal</caption>
      <thead>
        <tr>
          <th scope="col">Day</th>
          <th scope="col">Laundering alerts</th>
          <th scope="col">Static recall (95% CI)</th>
          <th scope="col">Static reviewed</th>
          <th scope="col">ACI recall (95% CI)</th>
          <th scope="col">ACI reviewed</th>
        </tr>
      </thead>
      <tbody>
        {staticRun.by_day.map((st) => {
          const ac = aciByDay.get(st.day);
          return (
            <tr key={st.day}>
              <th scope="row" className={styles.num}>
                {st.day}
                {tailDays.includes(st.day) ? " (tail)" : ""}
              </th>
              <td className={styles.num}>{integer(st.positives)}</td>
              <td className={styles.num}>
                {st.positives
                  ? `${percent(st.recall.value)} (${percent(st.recall.low)}–${percent(st.recall.high)})`
                  : "no positives"}
              </td>
              <td className={styles.num}>{integer(st.reviewed)}</td>
              <td className={styles.num}>
                {ac?.positives
                  ? `${percent(ac.recall.value)} (${percent(ac.recall.low)}–${percent(ac.recall.high)})`
                  : "no positives"}
              </td>
              <td className={styles.num}>{ac ? integer(ac.reviewed) : "—"}</td>
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
          <LegendItem kind="dotStatic">Static conformal (with 95% CI)</LegendItem>
          <LegendItem kind="dotAci">Adaptive conformal (ACI)</LegendItem>
          <LegendItem kind="target">Target recall</LegendItem>
          {tailDays.length ? (
            <span>* sparse tail day (few payments, mostly laundering)</span>
          ) : null}
        </>
      }
    />
  );
}
