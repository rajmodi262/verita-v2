import { lazy, Suspense, useCallback, useRef } from "react";
import { Link } from "react-router-dom";

import { useHeadline } from "../../api/evidence";
import { applyStageSignal } from "../../components/hero/stageSignal";
import type { StageSignal } from "../../components/hero/VaultScene";
import { GuillocheSeal } from "../../components/seal/GuillocheSeal";
import type { Headline, HeadlineResponse } from "../../api/evidence";
import { percent } from "../../lib/format";

import styles from "./LandingPage.module.css";

const VaultScene = lazy(() => import("../../components/hero/VaultScene"));

/** A fixed root for the decorative landing seal (any hex string seeds a valid rosette). */
const SEAL_ROOT = "5e7a11fe9e3779b97f4a7c15f39cc0605cedc834";

function hasWebGL(): boolean {
  try {
    return Boolean(document.createElement("canvas").getContext("webgl2"));
  } catch {
    return false;
  }
}

interface Pillar {
  name: string;
  question: string;
  body: string;
  /** The measured figure that backs the claim, by metrics.json headline key. */
  metric: string;
  context?: string;
}

const PILLARS: Pillar[] = [
  {
    name: "Detect",
    question: "Why is this an alert?",
    body: "Laundering patterns found in the transaction graph — fan-in, cycles, pass-through — with the money path drawn and the reasons in plain English.",
    metric: "detect.f1",
    context: "detect.rules_f1",
  },
  {
    name: "Decide",
    question: "With my team size, what will we miss?",
    body: "A statistical recall guarantee, the expected missed value, and the analysts needed to keep the guarantee — tested on future data, including where it breaks.",
    metric: "decide.recall_aci_pooled",
  },
  {
    name: "Defend",
    question: "Can I prove this report?",
    body: "Every sentence cites evidence and is machine-checked. Approved case files are signed, and anyone can verify them offline.",
    metric: "defend.detection",
    context: "defend.false_alarm",
  },
];

function figure(h: Headline): string {
  const digits = h.value > 0.99 || h.value < 0.01 ? 2 : 1;
  const main = percent(h.value, digits);
  if (h.low == null || h.high == null) return main;
  return `${main} (95% CI ${percent(h.low, digits)}–${percent(h.high, digits)})`;
}

function Measured({ data, pillar }: { data: HeadlineResponse | undefined; pillar: Pillar }) {
  const find = (key: string | undefined) => data?.headline.find((h) => h.key === key);
  const main = find(pillar.metric);
  const context = find(pillar.context);
  if (!main) return null;
  return (
    <div className={styles.measured}>
      <p className={styles.metricLabel}>{main.label}</p>
      <p className={styles.metric}>{figure(main)}</p>
      {context ? (
        <p className={styles.context}>
          {context.label}: {figure(context)}
        </p>
      ) : null}
      <p className={styles.source}>
        {main.dataset}, {main.split} split · <code>{main.source}</code>
      </p>
    </div>
  );
}

export default function LandingPage() {
  const headline = useHeadline();
  const data = headline.data;
  const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  // The 3D stage is for wide screens with WebGL; phones get the engraved 2D seal (no 3D download).
  const cinematic = window.matchMedia("(min-width: 900px)").matches && hasWebGL();
  // The scene reports, every frame, how squarely the coin faces the viewer and which laundering
  // pattern the money is performing; written straight to the DOM (no re-render per frame).
  const stage = useRef<HTMLElement>(null);
  const caption = useRef<HTMLParagraphElement>(null);
  const onSignal = useCallback((signal: StageSignal) => {
    applyStageSignal(stage.current, caption.current, signal);
  }, []);
  return (
    <main id="main" className={styles.page} data-landing>
      <header className={styles.stage} ref={stage}>
        <nav className={styles.nav} aria-label="Site">
          <span className={styles.navLinks}>
            <a href="#measured">Detect</a>
            <a href="#measured">Decide</a>
            <a href="#measured">Defend</a>
          </span>
          <Link to="/login" className={styles.navCta}>
            Sign in
          </Link>
        </nav>
        {/* The words flank the coin and glint in only while its face catches the light. */}
        <p className={styles.wordLeft} aria-hidden="true">
          Follow
        </p>
        <p className={styles.wordRight} aria-hidden="true">
          <span className={styles.wordSmall}>the</span>
          money
        </p>
        <div className={styles.scene} aria-hidden="true">
          {cinematic ? (
            <Suspense fallback={null}>
              <VaultScene still={still} onSignal={onSignal} />
            </Suspense>
          ) : (
            <div className={styles.flatSeal}>
              <GuillocheSeal root={SEAL_ROOT} leaves={[]} serial="Verita" size={260} />
            </div>
          )}
        </div>
        <p className={styles.caption} ref={caption} aria-hidden="true" />
        <div className={styles.band}>
          <h1 className={styles.headline}>
            Every alert explained · Every miss quantified · Every report provable
          </h1>
        </div>
        <div className={styles.cta}>
          <Link to="/login" className={styles.enter}>
            Enter the case room <span className={styles.arrow}>→</span>
          </Link>
          <a href="#measured" className={styles.evidence}>
            See the evidence ↓
          </a>
        </div>
        <span className={styles.scrollCue} aria-hidden="true" />
      </header>
      <section id="measured" aria-labelledby="pillars" className={styles.pillars}>
        <h2 id="pillars" className="srOnly">
          What Verita does, and how well
        </h2>
        {PILLARS.map((p) => (
          <article key={p.name} className={styles.pillar}>
            <p className={styles.kicker}>{p.name}</p>
            <h3>{p.question}</h3>
            <p>{p.body}</p>
            <Measured data={data} pillar={p} />
          </article>
        ))}
      </section>
      <footer className={styles.note}>
        {data ? (
          <>
            <p>{data.synthetic_data_notice}</p>
            <p>
              Every figure above is read live from <code>reports/metrics.json</code> (commit{" "}
              <code>{data.git_sha}</code>, SHA-256 <code>{data.sha256.slice(0, 16)}…</code>); none
              is typed by hand. The full evidence is in the Evidence Room after signing in.
            </p>
          </>
        ) : (
          <p>
            Results appear here after the first evaluation run. Every number on this site is
            generated by the pipeline, and all models are trained on synthetic data.
          </p>
        )}
      </footer>
    </main>
  );
}
