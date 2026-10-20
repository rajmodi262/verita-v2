import { useId } from "react";
import type { KeyboardEvent, ReactNode } from "react";
import { useSearchParams } from "react-router-dom";

import { useEvidence } from "../../api/evidence";
import type {
  DataSection,
  DatasetSection,
  DecideSection,
  DefendSection,
  DetectSection,
  Interval,
  MetricsFile,
} from "../../api/evidence";
import { BarCI } from "../../components/charts/BarCI";
import { CoverageChart } from "../../components/charts/CoverageChart";
import { ReliabilityChart } from "../../components/charts/ReliabilityChart";
import { ErrorState } from "../../components/ErrorState";
import { EmptyState, HashText, Panel, Select, Stat, Stamp } from "../../components/ui";
import { integer, percent } from "../../lib/format";

import styles from "./EvidenceRoomPage.module.css";

const TABS = [
  { id: "data", label: "Data" },
  { id: "detect", label: "Detect" },
  { id: "decide", label: "Decide" },
  { id: "defend", label: "Defend" },
  { id: "lineage", label: "Lineage" },
] as const;
type TabId = (typeof TABS)[number]["id"];

function ci(i: Interval | undefined | null, digits = 1): string {
  if (!i) return "—";
  if (i.low == null || i.high == null) return percent(i.value, digits);
  return `${percent(i.value, digits)} (${percent(i.low, digits)}–${percent(i.high, digits)})`;
}

function Download({ name, data }: { name: string; data: unknown }) {
  const href = `data:application/json;charset=utf-8,${encodeURIComponent(JSON.stringify(data, null, 2))}`;
  return (
    <a className={styles.download} href={href} download={`${name}.json`}>
      Download the underlying JSON
    </a>
  );
}

/** A figure: what it shows, what it doesn't, the figure itself, and its data. */
function Figure({
  title,
  shows,
  doesNot,
  name,
  data,
  children,
}: {
  title: string;
  shows: string;
  doesNot: string;
  name: string;
  data: unknown;
  children: ReactNode;
}) {
  return (
    <Panel title={title} label="Exhibit">
      <p className={styles.caption}>
        <strong>Shows:</strong> {shows} <strong>Does not show:</strong> {doesNot}
      </p>
      {children}
      <Download name={name} data={data} />
    </Panel>
  );
}

function Missing({ what }: { what: string }) {
  return (
    <EmptyState title={`No ${what} results for this dataset`}>
      <p>This stage has not been run on it yet; nothing is shown rather than a guess.</p>
    </EmptyState>
  );
}

function DataTab({ d }: { d: DataSection | null }) {
  if (!d) return <Missing what="data" />;
  const splits = Object.entries(d.splits).filter(([k]) => !["method", "fractions"].includes(k)) as [
    string,
    { rows: number; laundering: number; laundering_rate: number; from: string; to: string },
  ][];
  return (
    <div className={styles.stack}>
      <div className={styles.stats}>
        <Stat
          label="Payments"
          value={integer(d.rows)}
          detail={`${d.time_span.from.slice(0, 10)} → ${d.time_span.to.slice(0, 10)}`}
          provenance={{
            formula: "Rows in the source CSV after the data contract.",
            source: "datasets.<ds>.data.rows",
          }}
        />
        <Stat
          label="Laundering"
          value={integer(d.laundering)}
          detail={`${percent(d.laundering_rate, 3)} of payments`}
          provenance={{
            formula: "Payments labelled Is Laundering = 1.",
            source: "datasets.<ds>.data.laundering",
          }}
        />
        <Stat
          label="Data contract"
          tone={d.contract_passed ? "verified" : "alert"}
          value={d.contract_passed ? "✓ Passed" : "✗ Failed"}
          detail={`${String(Object.values(d.violations).reduce((a, b) => a + b, 0))} violations`}
          provenance={{
            formula: "Seven hard checks on schema, values and vocabularies.",
            source: "datasets.<ds>.data.violations",
          }}
        />
        <Stat
          label="Typology coverage"
          value={percent(d.patterns.coverage)}
          detail={`${integer(d.patterns.laundering_unattributed)} laundering payments have no typology`}
          provenance={{
            formula: "Laundering payments linked to a labelled pattern ÷ all laundering payments.",
            source: "datasets.<ds>.data.patterns.coverage",
          }}
        />
      </div>
      <Figure
        title="Temporal splits"
        shows="row counts and laundering rates per split, ordered in time; the test rate is higher than train (label shift)."
        doesNot="any random or account-level split — none is used."
        name="splits"
        data={d.splits}
      >
        <table className={styles.table}>
          <caption className="srOnly">Temporal splits</caption>
          <thead>
            <tr>
              <th scope="col">Split</th>
              <th scope="col">Rows</th>
              <th scope="col">Laundering</th>
              <th scope="col">Rate</th>
              <th scope="col">From</th>
              <th scope="col">To</th>
            </tr>
          </thead>
          <tbody>
            {splits.map(([name, s]) => (
              <tr key={name}>
                <th scope="row">{name}</th>
                <td className={styles.num}>{integer(s.rows)}</td>
                <td className={styles.num}>{integer(s.laundering)}</td>
                <td className={styles.num}>{percent(s.laundering_rate, 3)}</td>
                <td className={styles.mono}>{s.from}</td>
                <td className={styles.mono}>{s.to}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className={styles.note}>
          Method: {d.splits.method}. Sparse tail days (mostly laundering):{" "}
          {d.sparse_tail_days.join(", ") || "none"}.
        </p>
      </Figure>
      <Figure
        title="Labelled patterns by typology"
        shows="how many laundering attempts and payments each typology has in the source's pattern file."
        doesNot="the unattributed laundering, which has no typology label at all."
        name="patterns"
        data={d.patterns_by_typology}
      >
        <table className={styles.table}>
          <caption className="srOnly">Patterns by typology</caption>
          <thead>
            <tr>
              <th scope="col">Typology</th>
              <th scope="col">Attempts</th>
              <th scope="col">Payments</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(d.patterns_by_typology).map(([t, v]) => (
              <tr key={t}>
                <th scope="row">{t}</th>
                <td className={styles.num}>{v.attempts}</td>
                <td className={styles.num}>{integer(v.transactions)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Figure>
      <Panel title="Source files" label="Integrity">
        <ul className={styles.files}>
          {d.files.map((f) => (
            <li key={f.name}>
              {f.ok ? "✓" : "✗"} <code>{f.name}</code>{" "}
              <HashText value={f.sha256} label={`SHA-256 of ${f.name}`} />
            </li>
          ))}
        </ul>
        <p className={styles.note}>
          Known limitation: the data is synthetic. Real typologies, base rates and adversaries
          differ.
        </p>
      </Panel>
    </div>
  );
}

function DetectTab({ d }: { d: DetectSection | null }) {
  if (!d) return <Missing what="detection" />;
  const champ = d.models.lgbm_champion?.test;
  const rules = d.models.rules_incumbent?.test;
  return (
    <div className={styles.stack}>
      <div className={styles.stats}>
        <Stat
          label="Laundering F1, champion"
          value={champ ? percent(champ.f1.value) : "—"}
          detail={champ ? `95% CI ${ci(champ.f1).split(" ")[1] ?? ""}` : undefined}
          provenance={{
            formula:
              "Minority-class F1 at the threshold chosen on the hpo split; 6-hour block bootstrap CI.",
            source: "datasets.<ds>.detect.models.lgbm_champion.test.f1",
          }}
        />
        <Stat
          label="PR-AUC, champion"
          value={champ ? percent(champ.pr_auc.value) : "—"}
          detail={champ ? ci(champ.pr_auc) : undefined}
          provenance={{
            formula: "Area under the precision–recall curve on test.",
            source: "datasets.<ds>.detect.models.lgbm_champion.test.pr_auc",
          }}
        />
        <Stat
          label="Rules incumbent F1"
          value={rules ? percent(rules.f1.value, 2) : "—"}
          detail="six hand-written AML rules"
          provenance={{
            formula: "Same metric for the rules baseline.",
            source: "datasets.<ds>.detect.models.rules_incumbent.test.f1",
          }}
        />
        <Stat
          label="Seed stability"
          value={`± ${percent(d.seeds.f1_std, 2)}`}
          detail={`F1 over seeds ${d.seeds.seeds.join(", ")}`}
          provenance={{
            formula: "Standard deviation of test F1 across training seeds.",
            source: "datasets.<ds>.detect.seeds",
          }}
        />
      </div>
      <Figure
        title="Models and published baselines"
        shows="our models on the test split next to the published minority-class F1 on the same split definition."
        doesNot="a like-for-like feature set: GFP rows use IBM's Graph Feature Preprocessor."
        name="models"
        data={{ models: d.models, published: d.published_baselines }}
      >
        <table className={styles.table}>
          <caption className="srOnly">Models and baselines</caption>
          <thead>
            <tr>
              <th scope="col">Model</th>
              <th scope="col">F1 (95% CI)</th>
              <th scope="col">Bulk days</th>
              <th scope="col">Tail days</th>
              <th scope="col">PR-AUC</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(d.models).map(([name, r]) => (
              <tr key={name}>
                <th scope="row">{name}</th>
                <td className={styles.num}>{ci(r.test.f1)}</td>
                <td className={styles.num}>{ci(r.test_bulk?.f1)}</td>
                <td className={styles.num}>{ci(r.test_tail?.f1)}</td>
                <td className={styles.num}>{ci(r.test.pr_auc)}</td>
              </tr>
            ))}
            {Object.entries(d.published_baselines.rows).map(([name, r]) => (
              <tr key={name} className={styles.published}>
                <th scope="row">{name} (published)</th>
                <td className={styles.num}>
                  {r.mean.toFixed(2)}% ± {r.std.toFixed(2)}
                </td>
                <td colSpan={3}>{d.published_baselines.source}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Figure>
      <Figure
        title="Recall by typology"
        shows="share of each typology's laundering payments the champion flags, with Wilson 95% intervals and support."
        doesNot="precision per typology — the threshold is shared."
        name="per_typology"
        data={d.per_typology}
      >
        <BarCI
          caption="Recall by typology"
          valueLabel="Recall"
          summary={`Recall ranges from ${percent(Math.min(...d.per_typology.map((t) => t.recall.value)))} to ${percent(Math.max(...d.per_typology.map((t) => t.recall.value)))} across typologies.`}
          rows={d.per_typology.map((t) => ({
            label: t.typology,
            value: t.recall.value,
            low: t.recall.low,
            high: t.recall.high,
            note: `n=${String(t.support)}`,
          }))}
        />
      </Figure>
      <Figure
        title="Ablations and sanity checks"
        shows="the F1 lost when each feature group is removed (paired bootstrap), imbalance strategies, and checks that the evaluation cannot be gamed."
        doesNot="interactions between feature groups."
        name="ablation"
        data={{ ablation: d.ablation, imbalance: d.imbalance, sanity: d.sanity }}
      >
        <table className={styles.table}>
          <caption className="srOnly">Feature-group ablation</caption>
          <thead>
            <tr>
              <th scope="col">Without</th>
              <th scope="col">F1</th>
              <th scope="col">Δ F1 vs champion (95% CI)</th>
            </tr>
          </thead>
          <tbody>
            {d.ablation.map((a) => (
              <tr key={a.removed_group}>
                <th scope="row">{a.removed_group}</th>
                <td className={styles.num}>{ci(a.f1)}</td>
                <td className={styles.num}>
                  {a.delta.value.toFixed(3)} ({a.delta.low?.toFixed(3)} to{" "}
                  {a.delta.high?.toFixed(3)})
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <ul className={styles.list}>
          {d.imbalance.map((v) => (
            <li key={v.variant}>
              Imbalance — {v.variant}: F1 {ci(v.f1)}
            </li>
          ))}
          <li>
            Label-shuffled training: PR-AUC {percent(d.sanity.label_shuffle.test_pr_auc, 3)} vs base
            rate {percent(d.sanity.label_shuffle.base_rate, 3)} — the model learns nothing from
            shuffled labels.
          </li>
          <li>
            Random (leaky) split F1 {percent(d.sanity.random_split.random_split_test_f1)} vs
            temporal {champ ? percent(champ.f1.value) : "—"}.
          </li>
          <li>
            Typology head: accuracy {percent(d.typology_head.accuracy)} vs majority class{" "}
            {percent(d.typology_head.majority_class_accuracy)}.
          </li>
        </ul>
      </Figure>
    </div>
  );
}

function DecideTab({ d }: { d: DecideSection | null }) {
  if (!d) return <Missing what="capacity" />;
  const runs = d.coverage.by_alpha["0.05"];
  const staticRun = runs?.static_pooled;
  const aciRun = runs?.aci_pooled;
  return (
    <div className={styles.stack}>
      <Figure
        title="Reliability diagram"
        shows="whether a predicted probability means what it says, in equal-mass bins on the test split."
        doesNot="per-typology calibration."
        name="calibration"
        data={d.calibration}
      >
        <ReliabilityChart
          before={d.calibration.before.reliability}
          after={d.calibration.after.reliability}
          eceBefore={d.calibration.before.ece}
          eceAfter={d.calibration.after.ece}
        />
      </Figure>
      {staticRun && aciRun ? (
        <Figure
          title="Was the 95% recall guarantee kept?"
          shows="realised recall per replay day for the static conformal threshold and adaptive conformal inference."
          doesNot="what the guarantee costs in analysts — see the Capacity planner."
          name="coverage"
          data={d.coverage}
        >
          <CoverageChart
            staticRun={{ alpha: 0.05, mode: "static_pooled", ...staticRun }}
            aciRun={{ alpha: 0.05, mode: "aci_pooled", ...aciRun }}
            targetRecall={0.95}
            tailDays={d.coverage.tail_days}
          />
        </Figure>
      ) : null}
      <Figure
        title="Every guarantee level"
        shows="realised recall for each α under three methods, and how many account-days each reviews."
        doesNot="day-level variation (above)."
        name="coverage_by_alpha"
        data={d.coverage.by_alpha}
      >
        <table className={styles.table}>
          <caption className="srOnly">Coverage by guarantee level</caption>
          <thead>
            <tr>
              <th scope="col">Target</th>
              <th scope="col">Static pooled</th>
              <th scope="col">Static per typology</th>
              <th scope="col">ACI</th>
              <th scope="col">ACI reviews</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(d.coverage.by_alpha).map(([alpha, r]) => (
              <tr key={alpha}>
                <th scope="row">{percent(1 - Number(alpha), 0)}</th>
                <td className={styles.num}>{ci(r.static_pooled?.overall.recall)}</td>
                <td className={styles.num}>{ci(r.static_mondrian?.overall.recall)}</td>
                <td className={styles.num}>{ci(r.aci_pooled?.overall.recall)}</td>
                <td className={styles.num}>
                  {integer(r.aci_pooled?.overall.reviewed ?? 0)} vs{" "}
                  {integer(r.static_pooled?.overall.reviewed ?? 0)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Figure>
      <Figure
        title="Forecast backtest and drift"
        shows="out-of-sample workload forecast accuracy and interval coverage, and population stability per replay day."
        doesNot="time-anchored features (account age, time since activity): they drift with the calendar by construction and are excluded."
        name="forecast_drift"
        data={{ forecast: d.forecast, drift: d.drift }}
      >
        <table className={styles.table}>
          <caption className="srOnly">Forecast models</caption>
          <thead>
            <tr>
              <th scope="col">Model</th>
              <th scope="col">MASE</th>
              <th scope="col">80% band coverage</th>
              <th scope="col">95% band coverage</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(d.forecast.models ?? {}).map(([name, f]) => (
              <tr key={name}>
                <th scope="row">{name}</th>
                <td className={styles.num}>{f.mase?.toFixed(3) ?? "—"}</td>
                <td className={styles.num}>
                  {f.coverage_80 == null ? "—" : percent(f.coverage_80)}
                </td>
                <td className={styles.num}>
                  {f.coverage_95 == null ? "—" : percent(f.coverage_95)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <table className={styles.table}>
          <caption className="srOnly">Drift by day</caption>
          <thead>
            <tr>
              <th scope="col">Day</th>
              <th scope="col">Max PSI</th>
              <th scope="col">Led by</th>
              <th scope="col">Recalibrate</th>
            </tr>
          </thead>
          <tbody>
            {d.drift.by_day.map((r) => (
              <tr key={r.day}>
                <th scope="row" className={styles.mono}>
                  {r.day}
                </th>
                <td className={styles.num}>{r.max_psi.toFixed(2)}</td>
                <td className={styles.mono}>{r.top ?? "—"}</td>
                <td>{r.recalibrate ? "Yes" : "No"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Figure>
      {d.bench ? (
        <Panel title="Interactive latency" label="Benchmarks">
          <p>
            Evidence subgraph p95 <span className={styles.mono}>{d.bench.subgraph.p95_ms} ms</span>{" "}
            over {d.bench.subgraph.n} real alerts (target {d.bench.subgraph.target_p95_ms} ms);
            exact staffing plan p95{" "}
            <span className={styles.mono}>{d.bench.plan.warm.p95_ms} ms</span> warm,{" "}
            <span className={styles.mono}>{d.bench.plan.cold.p95_ms} ms</span> on first load of a
            day.
          </p>
        </Panel>
      ) : null}
    </div>
  );
}

function DefendTab({ d }: { d: DefendSection | null }) {
  if (!d) return <Missing what="verifier" />;
  const faults = Object.entries(d.faults);
  const llmRate = d.llm.run ? d.llm.unsupported_claim_rate : undefined;
  const llmPassing = d.llm.run ? d.llm.drafts_passing_verification : undefined;
  // Keys and providers fail over, so name the models that actually wrote the drafts.
  const llmWriters = Object.entries(d.llm.drafted_by ?? {})
    .map(([model, n]) => `${String(n)} by ${model}`)
    .join(", ");
  const failed = d.llm.provider_failures ?? 0;
  const llmAttempts = `${String((d.llm.drafts ?? 0) + failed)} attempted, ${String(failed)} hit provider quota`;
  return (
    <div className={styles.stack}>
      <div className={styles.stats}>
        <Stat
          label="Planted faults caught"
          tone="verified"
          value={percent(d.overall_detection.value, 2)}
          detail={`${integer(d.overall_detection.hits)} of ${integer(d.overall_detection.total)} · ${ci(d.overall_detection, 2)}`}
          provenance={{
            formula:
              "Variants with one planted fault that the verifier rejects ÷ variants planted; Wilson 95% interval.",
            source: "datasets.<ds>.defend.overall_detection",
          }}
        />
        <Stat
          label="False alarms"
          value={percent(d.clean_false_alarm.value)}
          detail={`${String(d.clean_false_alarm.hits)} of ${String(d.cases)} clean narratives · ${ci(d.clean_false_alarm)}`}
          provenance={{
            formula: "Clean narratives the verifier rejects ÷ clean narratives.",
            source: "datasets.<ds>.defend.clean_false_alarm",
          }}
        />
        <Stat
          label="Claims checked"
          value={integer(d.claims_checked_on_clean)}
          detail={`verifier ${d.verifier_version}`}
          provenance={{
            formula:
              "Claims extracted from the clean narratives and matched against cited evidence.",
            source: "datasets.<ds>.defend.claims_checked_on_clean",
          }}
        />
        <Stat
          label="Raw LLM hallucination"
          value={llmRate ? percent(llmRate.value, 1) : "not run"}
          detail={
            llmRate
              ? `${integer(llmRate.hits)} of ${integer(llmRate.total)} claims unsupported · ${ci(llmRate, 1)} · ${llmWriters}`
              : (d.llm.reason ?? "")
          }
          provenance={{
            formula:
              "Unsupported claims in LLM drafts before verification ÷ all their claims; Wilson 95% interval. The verifier gates every draft, so none of these reach a signed case.",
            source: "datasets.<ds>.defend.llm.unsupported_claim_rate",
          }}
        />
        {llmPassing ? (
          <Stat
            label="LLM drafts passing as written"
            value={percent(llmPassing.value, 1)}
            detail={`${integer(llmPassing.hits)} of ${integer(llmPassing.total)} drafts · ${ci(llmPassing, 1)} · ${llmAttempts}`}
            provenance={{
              formula:
                "LLM drafts the verifier accepts with no edits ÷ drafts written. Attempts that hit provider quota wrote no draft and are not counted.",
              source: "datasets.<ds>.defend.llm.drafts_passing_verification",
            }}
          />
        ) : null}
      </div>
      <Figure
        title="Detection by fault type"
        shows="for each kind of planted error, the share of variants the verifier rejects (Wilson 95% interval)."
        doesNot="errors the fault set does not model, such as a wrong motive in prose."
        name="faults"
        data={d.faults}
      >
        <BarCI
          caption="Detection by fault type"
          valueLabel="Detected"
          summary={`The verifier caught ${percent(d.overall_detection.value, 2)} of ${integer(d.overall_detection.total)} planted faults across ${String(faults.length)} fault types.`}
          rows={faults.map(([name, f]) => ({
            label: name.replace(/_/g, " "),
            value: f.detection.value,
            low: f.detection.low,
            high: f.detection.high,
            note: `${String(f.planted)} planted · localised ${percent(f.localisation.value)}`,
          }))}
        />
      </Figure>
      <Figure
        title="What it missed"
        shows="every undetected variant, verbatim (up to five per type), so the verifier's blind spots are visible."
        doesNot="a fix — misses are reported, not hidden."
        name="misses"
        data={faults.map(([name, f]) => ({ fault: name, misses: f.misses }))}
      >
        {faults.every(([, f]) => f.misses.length === 0) ? (
          <p>No misses.</p>
        ) : (
          <ul className={styles.list}>
            {faults.flatMap(([name, f]) =>
              f.misses.map((m, i) => (
                <li key={`${name}-${String(i)}`}>
                  <strong>{name}</strong> ({m.change}): “{m.sentence.text}”
                </li>
              )),
            )}
          </ul>
        )}
        <p className={styles.note}>
          Why it can miss: claims are matched by value, not by role. A changed amount that happens
          to equal another true figure in the cited evidence passes.
        </p>
      </Figure>
    </div>
  );
}

function LineageTab({ section }: { section: DatasetSection }) {
  if (section.lineage.length === 0) return <Missing what="lineage" />;
  return (
    <Figure
      title="Run manifests"
      shows="each pipeline stage's git revision, configuration hash, duration and the SHA-256 of what it read and wrote."
      doesNot="the raw data itself (hashes only)."
      name="lineage"
      data={section.lineage}
    >
      <table className={styles.table}>
        <caption className="srOnly">Run manifests</caption>
        <thead>
          <tr>
            <th scope="col">Stage</th>
            <th scope="col">Git revision</th>
            <th scope="col">Config hash</th>
            <th scope="col">Duration</th>
            <th scope="col">Outputs</th>
          </tr>
        </thead>
        <tbody>
          {section.lineage.map((r) => (
            <tr key={r.stage}>
              <th scope="row">{r.stage}</th>
              <td className={styles.mono}>{r.git_revision ?? "—"}</td>
              <td>
                {r.config_hash ? (
                  <HashText value={r.config_hash} label={`config hash of ${r.stage}`} />
                ) : (
                  "—"
                )}
              </td>
              <td className={styles.num}>
                {r.duration_s == null ? "—" : `${r.duration_s.toFixed(1)} s`}
              </td>
              <td>
                <ul className={styles.outputs}>
                  {Object.entries(r.outputs).map(([path, sha]) => (
                    <li key={path}>
                      <code>{path}</code>{" "}
                      <HashText value={sha} keep={6} label={`SHA-256 of ${path}`} />
                    </li>
                  ))}
                </ul>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Figure>
  );
}

function TabContent({ tab, section }: { tab: TabId; section: DatasetSection }) {
  switch (tab) {
    case "data":
      return <DataTab d={section.data} />;
    case "detect":
      return <DetectTab d={section.detect} />;
    case "decide":
      return <DecideTab d={section.decide} />;
    case "defend":
      return <DefendTab d={section.defend} />;
    case "lineage":
      return <LineageTab section={section} />;
  }
}

export default function EvidenceRoomPage() {
  const [params, setParams] = useSearchParams();
  const evidence = useEvidence();
  const baseId = useId();
  const tab = (TABS.find((t) => t.id === params.get("tab"))?.id ?? "detect") satisfies TabId;

  if (evidence.isError)
    return <ErrorState error={evidence.error} onRetry={() => void evidence.refetch()} />;
  if (!evidence.data) return <p role="status">Loading the evaluation report…</p>;

  const m: MetricsFile = evidence.data.metrics;
  const datasetKey = params.get("dataset") ?? m.primary_dataset;
  const section = m.datasets[datasetKey] ?? m.datasets[m.primary_dataset];
  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    next.set(key, value);
    setParams(next, { replace: true });
  };
  const onTabKey = (e: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const delta = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!delta) return;
    e.preventDefault();
    const next = TABS[(index + delta + TABS.length) % TABS.length];
    if (next) {
      set("tab", next.id);
      document.getElementById(`${baseId}-${next.id}`)?.focus();
    }
  };

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <p className={styles.kicker}>Evidence Room</p>
          <h1>Challenge the model</h1>
          <p className={styles.sub}>
            Every number here is read from one generated report — nothing is typed by hand.{" "}
            <Stamp tone="assumption">Synthetic data</Stamp> {m.synthetic_data_notice}
          </p>
        </div>
        <Select
          label="Dataset"
          value={datasetKey}
          options={Object.entries(m.datasets).map(([k, v]) => ({ value: k, label: v.label }))}
          onChange={(e) => {
            set("dataset", e.target.value);
          }}
        />
      </header>

      <div role="tablist" aria-label="Evidence" className={styles.tabs}>
        {TABS.map((t, i) => (
          <button
            key={t.id}
            id={`${baseId}-${t.id}`}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            aria-controls={`${baseId}-panel`}
            tabIndex={tab === t.id ? 0 : -1}
            className={styles.tab}
            onClick={() => {
              set("tab", t.id);
            }}
            onKeyDown={(e) => {
              onTabKey(e, i);
            }}
          >
            {t.label}
          </button>
        ))}
      </div>
      {section ? (
        <div
          id={`${baseId}-panel`}
          role="tabpanel"
          aria-labelledby={`${baseId}-${tab}`}
          className={styles.panel}
        >
          <TabContent tab={tab} section={section} />
        </div>
      ) : (
        <Missing what="any" />
      )}

      <footer className={styles.footer}>
        <span>
          reports/metrics.json · schema {m.schema_version} · built at commit{" "}
          <code>{m.git_sha}</code>
        </span>
        <HashText value={evidence.data.sha256} label="SHA-256 of metrics.json" />
      </footer>
    </div>
  );
}
