import { useId } from "react";
import type { ReactNode } from "react";

import { cx } from "../../lib/cx";

import styles from "./Stat.module.css";

export interface Provenance {
  /** The formula in words or symbols, e.g. "Σ p over reviewed ÷ Σ p over all". */
  formula: string;
  /** API fields (and artifact keys) the figure is read from. */
  source: string;
  /** Optional caveat: what the number does not say. */
  note?: string;
}

export interface StatProps {
  label: string;
  value: ReactNode;
  /** Secondary line under the value: an interval, a denominator, a comparison. */
  detail?: ReactNode;
  tone?: "neutral" | "alert" | "verified";
  provenance: Provenance;
}

/**
 * A figure that testifies (PIVOT §13.6): mono value, interval, and a "how computed" disclosure
 * that names the formula and the API field it came from. Native <details>, so it is keyboard-
 * and screen-reader-operable without script.
 */
export function Stat({ label, value, detail, tone = "neutral", provenance }: StatProps) {
  const labelId = useId();
  return (
    <div className={cx(styles.stat, styles[tone])} role="group" aria-labelledby={labelId}>
      <p id={labelId} className={styles.label}>
        {label}
      </p>
      <p className={styles.value}>{value}</p>
      {detail !== undefined ? <p className={styles.detail}>{detail}</p> : null}
      <details className={styles.how}>
        <summary>How computed</summary>
        <dl>
          <dt>Formula</dt>
          <dd>{provenance.formula}</dd>
          <dt>Source</dt>
          <dd className={styles.mono}>{provenance.source}</dd>
          {provenance.note ? (
            <>
              <dt>Note</dt>
              <dd>{provenance.note}</dd>
            </>
          ) : null}
        </dl>
      </details>
    </div>
  );
}
