import { useState } from "react";

import styles from "./HashText.module.css";

export interface HashTextProps {
  value: string;
  /** Characters kept at each end before the ellipsis. */
  keep?: number;
  label?: string;
}

/** A hash that testifies (Mono Witness Rule): middle-ellipsis, full value for screen readers, copy. */
export function HashText({ value, keep = 8, label = "hash" }: HashTextProps) {
  const [copied, setCopied] = useState(false);
  const short =
    value.length > keep * 2 + 1 ? `${value.slice(0, keep)}…${value.slice(-keep)}` : value;
  return (
    <span className={styles.hash}>
      <code title={value} aria-hidden="true">
        {short}
      </code>
      <span className="srOnly">{value}</span>
      <button
        type="button"
        className={styles.copy}
        aria-label={`Copy ${label}`}
        onClick={() => {
          void navigator.clipboard.writeText(value).then(() => {
            setCopied(true);
          });
        }}
      >
        {copied ? "Copied" : "Copy"}
      </button>
    </span>
  );
}
