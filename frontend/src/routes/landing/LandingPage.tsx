import { Link } from "react-router-dom";

import styles from "./LandingPage.module.css";

const PILLARS = [
  {
    name: "Detect",
    question: "Why is this an alert?",
    body: "Laundering patterns found in the transaction graph — fan-in, cycles, pass-through — with the money path drawn and the reasons in plain English.",
  },
  {
    name: "Decide",
    question: "With my team size, what will we miss?",
    body: "A statistical recall guarantee, the expected missed value, and the analysts needed to keep the guarantee — tested on future data, including where it breaks.",
  },
  {
    name: "Defend",
    question: "Can I prove this report?",
    body: "Every sentence cites evidence and is machine-checked. Approved case files are signed, and anyone can verify them offline.",
  },
] as const;

export default function LandingPage() {
  return (
    <main id="main" className={styles.page}>
      <header className={styles.hero}>
        <p className={styles.kicker}>Verita · anti-money-laundering</p>
        <h1 className={styles.headline}>
          Every alert explained. Every miss quantified. Every report provable.
        </h1>
        <div className={styles.cta}>
          <Link to="/login" className={styles.primary}>
            Sign in
          </Link>
        </div>
      </header>
      <section aria-labelledby="pillars" className={styles.pillars}>
        <h2 id="pillars" className="srOnly">
          What Verita does
        </h2>
        {PILLARS.map((p) => (
          <article key={p.name} className={styles.pillar}>
            <p className={styles.kicker}>{p.name}</p>
            <h3>{p.question}</h3>
            <p>{p.body}</p>
          </article>
        ))}
      </section>
      <p className={styles.note}>
        Results appear here after the first evaluation run. Every number on this site is generated
        by the pipeline, and all models are trained on synthetic data.
      </p>
    </main>
  );
}
