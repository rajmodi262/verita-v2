import { EmptyState } from "../components/ui";

import styles from "./Placeholder.module.css";

export interface PlaceholderProps {
  title: string;
  milestone: string;
  description: string;
}

/** Honest stand-in for a screen that isn't built yet — no fake data. */
export function Placeholder({ title, milestone, description }: PlaceholderProps) {
  return (
    <div className={styles.page}>
      <h1>{title}</h1>
      <EmptyState title={`Arrives in ${milestone}`}>
        <p>{description}</p>
      </EmptyState>
    </div>
  );
}
