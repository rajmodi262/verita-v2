import { cx } from "../../lib/cx";

import styles from "./Stamp.module.css";

export interface StampProps {
  /**
   * Stamps are declarations (DESIGN.md): alert = flagged/needs action, verified = proven,
   * assumption = a number we chose rather than measured (PIVOT §13 AssumptionStamp).
   */
  tone: "alert" | "verified" | "assumption";
  children: string;
}

export function Stamp({ tone, children }: StampProps) {
  return <span className={cx(styles.stamp, styles[tone])}>{children}</span>;
}
