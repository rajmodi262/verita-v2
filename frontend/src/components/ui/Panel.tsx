import { useId } from "react";
import type { ReactNode } from "react";

import styles from "./Panel.module.css";

export interface PanelProps {
  title: string;
  /** Mono micro-label above the title, e.g. "EXHIBIT A". */
  label?: string;
  actions?: ReactNode;
  children: ReactNode;
}

export function Panel({ title, label, actions, children }: PanelProps) {
  const headingId = useId();
  return (
    <section className={styles.panel} aria-labelledby={headingId}>
      <header className={styles.header}>
        <div>
          {label ? <p className={styles.label}>{label}</p> : null}
          <h2 id={headingId} className={styles.title}>
            {title}
          </h2>
        </div>
        {actions ? <div className={styles.actions}>{actions}</div> : null}
      </header>
      <div className={styles.body}>{children}</div>
    </section>
  );
}
