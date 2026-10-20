import styles from "./RiskTape.module.css";

export interface RiskTapeProps {
  days: { date: string; alerts: number }[];
  selected: string | undefined;
  onSelect: (date: string | undefined) => void;
}

/**
 * The queue's risk tape: one engraved stroke per day, its height the number of alerts that day
 * (square-root scale, so quiet days stay visible next to busy ones). Click a day to filter the
 * queue to it; click it again to clear. The counts are the queue's own (queue meta endpoint).
 */
export function RiskTape({ days, selected, onSelect }: RiskTapeProps) {
  if (days.length === 0) return null;
  const sorted = [...days].sort((a, b) => a.date.localeCompare(b.date));
  const max = Math.max(...sorted.map((d) => d.alerts), 1);
  const peak = sorted.reduce((m, d) => (d.alerts > m.alerts ? d : m));
  const total = sorted.reduce((sum, d) => sum + d.alerts, 0);
  return (
    <figure className={styles.tape}>
      <figcaption className={styles.caption}>
        <span className={styles.title}>Risk tape</span>
        <span>
          {total.toLocaleString()} alerts over {sorted.length} days · busiest {peak.date} (
          {peak.alerts.toLocaleString()})
        </span>
      </figcaption>
      <ol className={styles.days}>
        {sorted.map((d) => {
          const h = Math.max(Math.sqrt(d.alerts / max) * 100, 3);
          const on = d.date === selected;
          return (
            <li key={d.date} className={styles.day}>
              <button
                type="button"
                className={on ? styles.barOn : styles.bar}
                aria-pressed={on}
                aria-label={`${d.date}: ${d.alerts.toLocaleString()} alerts`}
                title={`${d.date} · ${d.alerts.toLocaleString()} alerts`}
                onClick={() => {
                  onSelect(on ? undefined : d.date);
                }}
              >
                <svg viewBox="0 0 10 100" preserveAspectRatio="none" aria-hidden="true">
                  <defs>
                    <linearGradient id={`tape-${d.date}`} x1="0" y1="1" x2="0" y2="0">
                      <stop offset="0" className={styles.stopLow} />
                      <stop offset="1" className={styles.stopHigh} />
                    </linearGradient>
                  </defs>
                  <rect
                    x="2"
                    y={100 - h}
                    width="6"
                    height={h}
                    rx="1.5"
                    fill={`url(#tape-${d.date})`}
                  />
                </svg>
              </button>
              <span className={styles.label} aria-hidden="true">
                {d.date.slice(8)}
              </span>
            </li>
          );
        })}
      </ol>
    </figure>
  );
}
