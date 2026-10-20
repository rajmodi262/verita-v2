import { useLayoutEffect, useState } from "react";
import type { RefObject } from "react";

import styles from "./EvidenceThreads.module.css";

export interface EvidenceThreadsProps {
  /** The case grid; threads are drawn over it. */
  root: RefObject<HTMLDivElement | null>;
  /** Index of the sentence being read (hover or keyboard focus), or null. */
  sentence: number | null;
  /** The evidence IDs that sentence cites. */
  ids: string[];
  /** The sentence failed verification: its threads are inked red. */
  failed: boolean;
}

interface Thread {
  id: string;
  d: string;
  ring: { x: number; y: number; w: number; h: number };
}

/**
 * Ink threads from a narrative sentence to every exhibit it cites, so the reader sees the
 * evidence behind each claim without hunting for it. Purely presentational: the citations are
 * the sentence's own evidence_ids; an exhibit inside a collapsed group threads to the group.
 */
export function EvidenceThreads({ root, sentence, ids, failed }: EvidenceThreadsProps) {
  const [threads, setThreads] = useState<Thread[]>([]);
  const [size, setSize] = useState({ w: 0, h: 0 });

  useLayoutEffect(() => {
    const grid = root.current;
    if (!grid || sentence === null) return undefined;
    const measure = () => {
      const base = grid.getBoundingClientRect();
      const from = grid.querySelector<HTMLElement>(`[data-sentence="${String(sentence)}"]`);
      if (!from) return;
      const a = from.getBoundingClientRect();
      const out: Thread[] = [];
      const exhibits = [...grid.querySelectorAll<HTMLElement>("[data-ev]")];
      for (const id of ids) {
        let target = exhibits.find((el) => el.dataset.ev === id) ?? null;
        // An exhibit inside a collapsed group threads to the group's heading.
        const closed = target?.closest("details:not([open])");
        if (closed) target = closed.querySelector("summary");
        if (!target) continue;
        const b = target.getBoundingClientRect();
        const x1 = a.left - base.left;
        const y1 = a.top - base.top + Math.min(a.height / 2, 14);
        const x2 = b.right - base.left;
        const y2 = b.top - base.top + b.height / 2;
        const bend = Math.max((x1 - x2) * 0.5, 40);
        out.push({
          id,
          d: `M${x1.toFixed(1)} ${y1.toFixed(1)}C${(x1 - bend).toFixed(1)} ${y1.toFixed(1)} ${(x2 + bend).toFixed(1)} ${y2.toFixed(1)} ${x2.toFixed(1)} ${y2.toFixed(1)}`,
          ring: {
            x: b.left - base.left - 3,
            y: b.top - base.top - 3,
            w: b.width + 6,
            h: b.height + 6,
          },
        });
      }
      setSize({ w: base.width, h: base.height });
      setThreads(out);
    };
    const frame = window.requestAnimationFrame(measure);
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [root, sentence, ids]);

  if (sentence === null || threads.length === 0) return null;
  return (
    <svg
      className={failed ? styles.overlayBad : styles.overlay}
      width={size.w}
      height={size.h}
      aria-hidden="true"
    >
      {threads.map((t) => (
        <g key={`${String(sentence)}-${t.id}`}>
          <path className={styles.thread} d={t.d} pathLength={1} />
          <rect
            className={styles.ring}
            x={t.ring.x}
            y={t.ring.y}
            width={t.ring.w}
            height={t.ring.h}
          />
        </g>
      ))}
    </svg>
  );
}
