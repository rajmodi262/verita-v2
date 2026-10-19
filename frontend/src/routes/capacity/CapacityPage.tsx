import { useMemo, useState } from "react";
import type { FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { useMe } from "../../api/auth";
import {
  useCalibration,
  useCapacityMeta,
  useCoverage,
  useDrift,
  useForecast,
  useFrontier,
  useLatestPlan,
  usePlan,
  useSavePlan,
  useStaffing,
} from "../../api/capacity";
import type { Assumptions, Mode, Objective, Plan, PlanPoint, WhatIf } from "../../api/capacity";
import { ApiError } from "../../api/client";
import { CoverageChart } from "../../components/charts/CoverageChart";
import { ForecastChart } from "../../components/charts/ForecastChart";
import { FrontierChart } from "../../components/charts/FrontierChart";
import { StaffingBars } from "../../components/charts/StaffingBars";
import { ErrorState } from "../../components/ErrorState";
import { Button, EmptyState, Field, Panel, Select, Slider, Stamp, Stat } from "../../components/ui";
import { dateTime, integer, percent, usd, usdShort } from "../../lib/format";
import { useDebounced } from "../../lib/useDebounced";

import styles from "./CapacityPage.module.css";

const MODE_OPTIONS = [
  { value: "pooled", label: "Pooled (one threshold)" },
  { value: "mondrian", label: "Per typology (Mondrian)" },
];

const OBJECTIVE_OPTIONS = [
  { value: "cases", label: "Most laundering cases caught" },
  { value: "value", label: "Most laundered dollars caught" },
];

const DEFAULT_ANALYSTS = 6;

function asMode(v: string | null): Mode {
  return v === "mondrian" ? "mondrian" : "pooled";
}

function asObjective(v: string | null): Objective {
  return v === "value" ? "value" : "cases";
}

function sameSettings(
  plan: Plan | undefined,
  s: { date: string; analysts: number; alpha: number; mode: Mode; objective: Objective },
): plan is Plan {
  return (
    plan?.day === s.date &&
    plan.analysts === s.analysts &&
    Math.abs(plan.alpha - s.alpha) < 1e-9 &&
    plan.mode === s.mode &&
    plan.objective === s.objective
  );
}

function WhatIfForm({
  base,
  active,
  onApply,
}: {
  base: Assumptions;
  active: WhatIf;
  onApply: (w: WhatIf) => void;
}) {
  const [minutes, setMinutes] = useState(String(active.median_minutes ?? base.median_minutes));
  const [hours, setHours] = useState(String(active.productive_hours ?? base.productive_hours));
  const [rate, setRate] = useState(String(active.analyst_hourly_rate ?? base.analyst_hourly_rate));
  const changed = Object.keys(active).length > 0;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const next: WhatIf = {};
    const m = Number(minutes);
    const h = Number(hours);
    const r = Number(rate);
    if (m > 0 && m !== base.median_minutes) next.median_minutes = m;
    if (h > 0 && h !== base.productive_hours) next.productive_hours = h;
    if (r >= 0 && r !== base.analyst_hourly_rate) next.analyst_hourly_rate = r;
    onApply(next);
  };

  return (
    <form className={styles.whatIf} onSubmit={submit}>
      <p>
        <Stamp tone="assumption">Assumption</Stamp> These are operating assumptions from{" "}
        <code>configs/operations.yaml</code>, not measurements. Change them to see how the plan
        moves; a what-if is never saved.
      </p>
      <div className={styles.whatIfFields}>
        <Field
          label="Median handling time (minutes)"
          type="number"
          min={1}
          max={600}
          value={minutes}
          onChange={(e) => {
            setMinutes(e.target.value);
          }}
        />
        <Field
          label="Productive hours per analyst"
          type="number"
          min={0.5}
          max={12}
          step={0.5}
          value={hours}
          onChange={(e) => {
            setHours(e.target.value);
          }}
        />
        <Field
          label="Analyst cost (USD per hour)"
          type="number"
          min={0}
          max={1000}
          value={rate}
          onChange={(e) => {
            setRate(e.target.value);
          }}
        />
      </div>
      <p className={styles.note}>
        Handling time per typology is the median × a multiplier (
        {Object.entries(base.typology_multiplier)
          .map(([t, m]) => `${t.toLowerCase()} ×${String(m)}`)
          .join(", ")}
        ).
      </p>
      <div className={styles.row}>
        <Button type="submit">Apply what-if</Button>
        {changed ? (
          <Button
            variant="ghost"
            onClick={() => {
              setMinutes(String(base.median_minutes));
              setHours(String(base.productive_hours));
              setRate(String(base.analyst_hourly_rate));
              onApply({});
            }}
          >
            Reset to configured
          </Button>
        ) : null}
      </div>
    </form>
  );
}

function Headline({
  point,
  exact,
  targetRecall,
  outsideExpected,
}: {
  point: PlanPoint;
  exact: boolean;
  targetRecall: number;
  outsideExpected: number | null;
}) {
  const g = point.guarantee;
  const more = Math.max(g.analysts_needed - point.analysts, 0);
  return (
    <div className={styles.headline} aria-live="polite">
      <Stat
        label={`${percent(targetRecall, 0)} recall guarantee`}
        tone={g.feasible ? "verified" : "alert"}
        value={g.feasible ? "✓ Holds" : `✗ Needs ${integer(more)} more`}
        detail={`${integer(g.required_alerts)} alerts must be reviewed (${integer(g.required_minutes)} min); ${integer(g.analysts_needed)} analysts needed`}
        provenance={{
          formula:
            "Feasible when Σ handling minutes of alerts scoring ≥ the conformal threshold ≤ analysts × productive hours × 60.",
          source: "plan.guarantee (GET /capacity/plan)",
          note: "The threshold guarantees recall in expectation over exchangeable days; the coverage panel shows whether it held on the replay.",
        }}
      />
      <Stat
        label="Expected recall"
        value={percent(point.expected_recall.value)}
        detail={`95% interval ${percent(point.expected_recall.low)}–${percent(point.expected_recall.high)}`}
        provenance={{
          formula:
            "Σ calibrated p over reviewed alerts ÷ (Σ p over the queue + expected positives below the alert floor). Interval: labels simulated as Bernoulli(p).",
          source: "plan.expected_recall",
          note:
            outsideExpected !== null && outsideExpected > 0
              ? `${outsideExpected.toFixed(1)} expected positives sit below the alert floor and can never be caught.`
              : "Calibration: isotonic regression fitted on the calibration split.",
        }}
      />
      <Stat
        label="Expected cases caught"
        value={point.expected_cases_caught.toFixed(1)}
        detail={`of ${point.expected_cases_total.toFixed(1)} expected laundering alerts`}
        provenance={{
          formula: "Σ calibrated p over reviewed alerts.",
          source: "plan.expected_cases_caught, plan.expected_cases_total",
        }}
      />
      <Stat
        label="Expected missed value"
        value={usdShort(point.expected_missed_value_usd)}
        detail={`${usd(point.expected_missed_value_usd)}; ${percent(point.value_recall)} of expected laundered value caught`}
        provenance={{
          formula: "Σ p × amount (USD) over alerts not reviewed.",
          source: "plan.expected_missed_value_usd, plan.value_recall",
          note: "Amounts converted at a fixed rate table (an assumption); a few very large payments dominate dollar totals.",
        }}
      />
      <Stat
        label="Review cost"
        value={usdShort(point.review_cost_usd)}
        detail={`${integer(point.review_minutes)} of ${integer(point.capacity_minutes)} analyst-minutes`}
        provenance={{
          formula: "Review minutes ÷ 60 × analyst hourly rate.",
          source: "plan.review_cost_usd",
        }}
      />
      <Stat
        label="Alerts reviewed"
        value={`${integer(point.reviewed)} / ${integer(point.alerts)}`}
        detail={
          exact
            ? `Exact plan (${point.solver}); greedy gap ${percent(point.optimality_gap, 2)}`
            : "Estimate from the precomputed greedy frontier — exact plan loading"
        }
        provenance={{
          formula:
            "0/1 knapsack: maximise Σ w over reviewed subject to Σ minutes ≤ capacity and every guaranteed alert reviewed; solved with OR-Tools CP-SAT, greedy ratio as baseline.",
          source: "plan.reviewed, plan.optimality_gap, plan.solver",
        }}
      />
    </div>
  );
}

export default function CapacityPage() {
  const [params, setParams] = useSearchParams();
  const me = useMe();
  const meta = useCapacityMeta();
  const days = meta.data?.days ?? [];
  const ops = meta.data?.operations;
  const date = params.get("date") ?? days[0];
  const alpha = Number(params.get("alpha") ?? meta.data?.default_alpha ?? 0.05);
  const mode = asMode(params.get("mode"));
  const objective = asObjective(params.get("objective"));
  const [analysts, setAnalysts] = useState(Number(params.get("analysts") ?? DEFAULT_ANALYSTS));
  const [whatIf, setWhatIf] = useState<WhatIf>({});
  const settledAnalysts = useDebounced(analysts, 300);

  const frontier = useFrontier(date, alpha, mode, objective);
  const staffing = useStaffing(alpha, mode);
  const forecast = useForecast();
  const coverage = useCoverage(alpha);
  const calibration = useCalibration();
  const drift = useDrift();
  const latest = useLatestPlan(date);
  const save = useSavePlan();
  const planQuery = useMemo(
    () => (date ? { date, analysts: settledAnalysts, alpha, mode, objective, whatIf } : null),
    [date, settledAnalysts, alpha, mode, objective, whatIf],
  );
  const plan = usePlan(planQuery);

  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    next.set(key, value);
    setParams(next, { replace: true });
  };

  if (meta.isError) {
    const missing = meta.error instanceof ApiError && meta.error.slug === "no-decide";
    return missing ? (
      <EmptyState title="Capacity analysis has not been run">
        <p>
          Run <code>verita decide run</code> after loading alerts.
        </p>
      </EmptyState>
    ) : (
      <ErrorState error={meta.error} onRetry={() => void meta.refetch()} />
    );
  }
  if (!meta.data || !ops || !date) {
    return <p aria-busy="true">Loading the capacity analysis…</p>;
  }

  const whatIfActive = Object.keys(whatIf).length > 0;
  const settings = { date, analysts, alpha, mode, objective };
  const exactPlan =
    sameSettings(plan.data, settings) && !plan.isPlaceholderData ? plan.data : undefined;
  const frontierPoint = frontier.data?.points.find((p) => p.analysts === analysts);
  // During a what-if the precomputed frontier is at the configured assumptions: wait for exact.
  const shown: PlanPoint | undefined = exactPlan ?? (whatIfActive ? undefined : frontierPoint);
  const targetRecall = 1 - alpha;
  const driftDay = drift.data?.by_day.find((d) => d.day === date);
  const isMlro = me.data?.role === "mlro";
  const runs = coverage.data?.runs;
  const staticRun = runs?.[mode === "mondrian" ? "static_mondrian" : "static_pooled"];
  const aciRun = runs?.aci_pooled;
  const realised = frontierPoint?.realised;
  const realisedRecall = typeof realised?.recall === "number" ? realised.recall : null;

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <p className={styles.kicker}>Decide · replay day {date}</p>
          <h1>Capacity planner</h1>
          <p className={styles.sub}>
            How many laundering alerts will we miss with the analysts we have — and how many
            analysts would a recall guarantee need?
          </p>
        </div>
        {latest.data ? (
          <p className={styles.saved}>
            <Stamp tone="verified">Plan saved</Stamp> #{latest.data.id}: {latest.data.analysts}{" "}
            analysts at {percent(1 - latest.data.alpha, 0)} ·{" "}
            <span className={styles.mono}>{dateTime(latest.data.created_at)}</span>
          </p>
        ) : null}
      </header>

      {driftDay?.recalibrate ? (
        <div className={styles.banner} role="status">
          <Stamp tone="alert">Drift</Stamp>
          <p>
            Population stability on {date} is outside the 0.25 band (max PSI{" "}
            <span className={styles.mono}>{driftDay.max_psi.toFixed(2)}</span>, led by{" "}
            <code>{driftDay.features[0]?.feature ?? "score"}</code>). Recalibration is recommended;
            see <a href="#coverage">whether the guarantee held</a>.
          </p>
        </div>
      ) : null}

      <Panel title="Controls" label="Settings">
        <div className={styles.controls}>
          <Slider
            label="Analysts on duty"
            min={ops.min_analysts}
            max={ops.max_analysts}
            value={analysts}
            unit="analysts"
            onChange={(v) => {
              setAnalysts(v);
              set("analysts", String(v));
            }}
          />
          <Select
            label="Recall guarantee"
            value={String(alpha)}
            options={meta.data.alphas.map((a) => ({
              value: String(a),
              label: `${percent(1 - a, 0)} (α = ${String(a)})`,
            }))}
            onChange={(e) => {
              set("alpha", e.target.value);
            }}
          />
          <Select
            label="Replay day"
            value={date}
            options={days.map((d) => ({ value: d, label: d }))}
            onChange={(e) => {
              set("date", e.target.value);
            }}
          />
          <Select
            label="Guarantee mode"
            value={mode}
            options={MODE_OPTIONS}
            onChange={(e) => {
              set("mode", e.target.value);
            }}
          />
          <Select
            label="Spare capacity goes to"
            value={objective}
            options={OBJECTIVE_OPTIONS}
            onChange={(e) => {
              set("objective", e.target.value);
            }}
          />
        </div>
      </Panel>

      {plan.isError ? <ErrorState error={plan.error} onRetry={() => void plan.refetch()} /> : null}
      {shown ? (
        <Headline
          point={shown}
          exact={exactPlan !== undefined}
          targetRecall={targetRecall}
          outsideExpected={exactPlan?.outside_expected ?? null}
        />
      ) : (
        <p aria-busy="true">Computing the exact plan…</p>
      )}

      {realised && realisedRecall !== null && !whatIfActive ? (
        <p className={styles.backtest}>
          <strong>Replay check:</strong> on this day the plan at {analysts} analysts actually caught{" "}
          <span className={styles.mono}>{integer(realised.caught)}</span> of{" "}
          <span className={styles.mono}>{integer(realised.positives)}</span> laundering alerts (
          <span className={styles.mono}>{percent(realisedRecall)}</span>) against an expected{" "}
          <span className={styles.mono}>{percent(frontierPoint.expected_recall.value)}</span>.
          Labels are never used to plan; this is the after-the-fact audit.
        </p>
      ) : null}

      <div className={styles.saveRow}>
        <Button
          onClick={() => {
            save.mutate({ date, analysts: settledAnalysts, alpha, mode, objective });
          }}
          disabled={!isMlro || whatIfActive || exactPlan === undefined}
          busy={save.isPending}
          aria-describedby="save-why"
        >
          Save plan
        </Button>
        <p id="save-why" className={styles.note}>
          {!isMlro
            ? "Only the MLRO can save a staffing plan; saved plans are part of the audit trail."
            : whatIfActive
              ? "Reset the what-if first: only plans at the configured assumptions are saved."
              : save.isSuccess
                ? `Saved as plan #${String(save.data.id)} and recorded in the audit log.`
                : "Saves this plan and its selected alerts to the audit trail."}
        </p>
        {save.isError ? <ErrorState error={save.error} /> : null}
      </div>

      <Panel
        title="Staffing frontier"
        label="Exhibit D-1"
        actions={
          frontier.data ? (
            <span className={styles.note}>
              {whatIfActive ? "At configured assumptions · " : ""}greedy, precomputed
            </span>
          ) : undefined
        }
      >
        {frontier.data ? (
          <FrontierChart
            points={frontier.data.points}
            analysts={analysts}
            targetRecall={targetRecall}
          />
        ) : frontier.isError ? (
          <ErrorState error={frontier.error} onRetry={() => void frontier.refetch()} />
        ) : (
          <p aria-busy="true">Loading the frontier…</p>
        )}
      </Panel>

      <details className={styles.drawer}>
        <summary>
          Assumptions {whatIfActive ? <Stamp tone="assumption">What-if active</Stamp> : null}
        </summary>
        <WhatIfForm base={ops} active={whatIf} onApply={setWhatIf} />
      </details>

      <div className={styles.twoUp}>
        <Panel title="Workload forecast" label="Exhibit D-2">
          {forecast.data ? (
            <ForecastChart forecast={forecast.data} />
          ) : forecast.isError ? (
            <ErrorState error={forecast.error} />
          ) : (
            <p aria-busy="true">Loading the forecast…</p>
          )}
          {staffing.data ? (
            <div className={styles.subChart}>
              <h3 className={styles.subTitle}>Analysts needed for the guarantee, per day</h3>
              <StaffingBars
                staffing={staffing.data}
                maxAnalysts={ops.max_analysts}
                targetLabel={percent(targetRecall, 0)}
              />
            </div>
          ) : null}
        </Panel>

        <section id="coverage" className={styles.anchor} aria-label="Coverage">
          <Panel title="Was the guarantee kept?" label="Exhibit D-3">
            {staticRun && aciRun && coverage.data ? (
              <CoverageChart
                staticRun={staticRun}
                aciRun={aciRun}
                targetRecall={targetRecall}
                tailDays={coverage.data.tail_days}
              />
            ) : coverage.isError ? (
              <ErrorState error={coverage.error} />
            ) : (
              <p aria-busy="true">Loading the replay…</p>
            )}
            {calibration.data ? (
              <p className={styles.note}>
                Calibration (isotonic, fitted on {calibration.data.fitted_on.split}; evaluated on{" "}
                {calibration.data.evaluated_on.split}): ECE{" "}
                <span className={styles.mono}>{calibration.data.before.ece.toFixed(4)}</span> →{" "}
                <span className={styles.mono}>{calibration.data.after.ece.toFixed(4)}</span>. The
                Evidence Room has the full reliability diagram.{" "}
                <Link to="/evidence-room">Open the Evidence Room</Link>.
              </p>
            ) : null}
          </Panel>
        </section>
      </div>

      {exactPlan && exactPlan.selected_alert_ids.length > 0 ? (
        <Panel title="Alerts in this plan" label="Review list">
          <p className={styles.note}>
            Highest-priority first. {integer(exactPlan.selected_alert_ids.length)} alerts; showing
            the first 24.
          </p>
          <ul className={styles.ids}>
            {exactPlan.selected_alert_ids.slice(0, 24).map((id) => (
              <li key={id}>
                <Link to={`/alerts/${String(id)}`} className={styles.mono}>
                  A-{id}
                </Link>
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}
    </div>
  );
}
