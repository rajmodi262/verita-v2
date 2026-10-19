import type { Forecast } from "../../api/capacity";
import { compact, dateTime, integer, percent } from "../../lib/format";
import { bandPath, linePath, linear, niceMax, ticks } from "../../lib/scale";

import { ChartFrame, LegendItem } from "./ChartFrame";
import styles from "./Chart.module.css";

const W = 640;
const H = 240;
const M = { top: 16, right: 16, bottom: 36, left: 56 };

/**
 * Hourly workload with the ensemble's out-of-sample forecast: each hour's band was issued
 * from a rolling origin before that hour, so the bands are an honest test, not a fit.
 */
export function ForecastChart({ forecast }: { forecast: Forecast }) {
  const series = forecast.series;
  const index = new Map(series.map((s, i) => [s.hour, i]));
  const bands = forecast.bands.filter((b) => index.has(b.hour));
  const top = niceMax(Math.max(1, ...series.map((s) => s.alerts), ...bands.map((b) => b.q975)));
  const x = linear([0, Math.max(series.length - 1, 1)], [M.left, W - M.right]);
  const y = linear([0, top], [H - M.bottom, M.top]);
  const bx = bands.map((b) => x(index.get(b.hour) ?? 0));
  const testStart = index.get(forecast.test_start) ?? 0;
  const ensemble = forecast.models.ensemble;
  const covered = bands.filter((b) => {
    const actual = series[index.get(b.hour) ?? 0]?.alerts ?? 0;
    return actual >= b.q025 && actual <= b.q975;
  }).length;
  const dayTicks = series
    .map((s, i) => ({ i, hour: s.hour }))
    .filter((s) => s.hour.slice(11, 13) === "00");

  const summary = `Out-of-sample, the ensemble's 95% band covered ${percent(bands.length ? covered / bands.length : 0, 0)} of test hours (it should cover 95%); MASE ${ensemble?.mase?.toFixed(2) ?? "—"} against the seasonal-naive scale.`;

  const chart = (
    <svg
      viewBox={`0 0 ${String(W)} ${String(H)}`}
      className={styles.svg}
      role="img"
      aria-label={`Alert workload forecast. ${summary}`}
    >
      {ticks(0, top, 4).map((t) => (
        <g key={t}>
          <line x1={M.left} x2={W - M.right} y1={y(t)} y2={y(t)} className={styles.grid} />
          <text x={M.left - 8} y={y(t) + 4} textAnchor="end" className={styles.axisText}>
            {compact(t)}
          </text>
        </g>
      ))}
      {dayTicks.map((d) => (
        <text
          key={d.hour}
          x={x(d.i)}
          y={H - M.bottom + 16}
          textAnchor="middle"
          className={styles.axisText}
        >
          {d.hour.slice(5, 10)}
        </text>
      ))}
      <path
        d={bandPath(
          bx,
          bands.map((b) => y(b.q975)),
          bands.map((b) => y(b.q025)),
        )}
        className={styles.band95}
      />
      <path
        d={bandPath(
          bx,
          bands.map((b) => y(b.q90)),
          bands.map((b) => y(b.q10)),
        )}
        className={styles.band80}
      />
      <path
        d={linePath(bands.map((b, i) => [bx[i] ?? 0, y(b.q50)] as const))}
        className={styles.median}
      />
      <path
        d={linePath(series.map((s, i) => [x(i), y(s.alerts)] as const))}
        className={styles.actual}
      />
      <line
        x1={x(testStart)}
        x2={x(testStart)}
        y1={M.top}
        y2={H - M.bottom}
        className={styles.testStart}
      />
      <text x={x(testStart) + 4} y={M.top + 10} className={styles.axisText}>
        test period →
      </text>
    </svg>
  );

  const table = (
    <table className={styles.table}>
      <caption className="srOnly">Forecast backtest by model</caption>
      <thead>
        <tr>
          <th scope="col">Model</th>
          <th scope="col">MASE</th>
          <th scope="col">Pinball 50%</th>
          <th scope="col">80% interval coverage</th>
          <th scope="col">95% interval coverage</th>
        </tr>
      </thead>
      <tbody>
        {Object.entries(forecast.models).map(([name, m]) => (
          <tr key={name}>
            <th scope="row">{name.replace("_", " ")}</th>
            <td className={styles.num}>{m.mase?.toFixed(3) ?? "—"}</td>
            <td className={styles.num}>{m.pinball_50?.toFixed(1) ?? "—"}</td>
            <td className={styles.num}>{m.coverage_80 === null ? "—" : percent(m.coverage_80)}</td>
            <td className={styles.num}>{m.coverage_95 === null ? "—" : percent(m.coverage_95)}</td>
          </tr>
        ))}
      </tbody>
      <tfoot>
        <tr>
          <td colSpan={5}>
            {integer(forecast.origins)} rolling origins every {forecast.step_hours} h,{" "}
            {forecast.horizon_hours} h horizon; test starts {dateTime(forecast.test_start)}.
          </td>
        </tr>
      </tfoot>
    </table>
  );

  return (
    <ChartFrame
      summary={summary}
      chart={chart}
      table={table}
      legend={
        <>
          <LegendItem kind="actual">Actual alerts per hour</LegendItem>
          <LegendItem kind="median">Forecast median</LegendItem>
          <LegendItem kind="band80">80% band</LegendItem>
          <LegendItem kind="band95">95% band</LegendItem>
        </>
      }
    />
  );
}
