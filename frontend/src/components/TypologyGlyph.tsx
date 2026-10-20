import styles from "./TypologyGlyph.module.css";

/**
 * A small engraved pictogram of each laundering typology's shape (IBM AML patterns): how money
 * moves in it, at a glance. Purely a reading aid; the typology name is always printed beside it.
 */
const SHAPES: Record<string, string> = {
  "FAN-IN": "M2 3L11 9M2 9H11M2 15L11 9M11 9H16",
  "FAN-OUT": "M2 9H7M7 9L16 3M7 9H16M7 9L16 15",
  CYCLE: "M9 2A7 7 0 1 1 3.5 5.2M3.5 1.5V5.2H7.2",
  "SCATTER-GATHER": "M2 9L9 3L16 9L9 15ZM2 9H16",
  "GATHER-SCATTER": "M2 3L9 9L2 15M16 3L9 9L16 15",
  BIPARTITE: "M3 3L15 3M3 3L15 15M3 15L15 3M3 15L15 15",
  STACK: "M2 3L9 9L16 3M2 9L9 15L16 9",
  RANDOM: "M2 12L6 4L10 14L14 6L16 9",
};

export function TypologyGlyph({ typology }: { typology: string }) {
  const d = SHAPES[typology];
  return (
    <svg className={styles.glyph} viewBox="0 0 18 18" aria-hidden="true">
      {d ? <path d={d} /> : <circle cx="9" cy="9" r="6" className={styles.unknown} />}
    </svg>
  );
}
