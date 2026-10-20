import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

import type { Sentence, SentenceReport } from "../../api/cases";
import { Button } from "../ui";

import styles from "./Case.module.css";

export const SECTIONS = ["who", "what", "when", "where", "why", "how"] as const;
const SECTION_LABELS: Record<string, string> = {
  who: "Who",
  what: "What",
  when: "When",
  where: "Where",
  why: "Why",
  how: "How",
};

/** Sentence text with every failing claim wrapped in <mark>, so the error is visible in place. */
function highlighted(text: string, report: SentenceReport | undefined): ReactNode {
  const failing = (report?.claims ?? []).filter((c) => !c.passed).map((c) => c.text);
  if (failing.length === 0) return text;
  const parts: ReactNode[] = [];
  let rest = text;
  let key = 0;
  while (rest) {
    const hits = failing
      .map((f) => ({ f, at: rest.indexOf(f) }))
      .filter((h) => h.at >= 0)
      .sort((a, b) => a.at - b.at);
    const hit = hits[0];
    if (!hit) {
      parts.push(rest);
      break;
    }
    if (hit.at > 0) parts.push(rest.slice(0, hit.at));
    parts.push(
      <mark key={key++} className={styles.wrong}>
        {hit.f}
        <span className="srOnly"> (does not match the evidence)</span>
      </mark>,
    );
    rest = rest.slice(hit.at + hit.f.length);
  }
  return parts;
}

export interface NarrativeViewProps {
  sentences: Sentence[];
  reports: SentenceReport[];
  selectedEvidence: string | null;
  onSelectEvidence: (id: string) => void;
  /** The sentence being read (hover or focus), for drawing its evidence threads. */
  onReadSentence?: (index: number | null) => void;
}

export function NarrativeView({
  sentences,
  reports,
  selectedEvidence,
  onSelectEvidence,
  onReadSentence,
}: NarrativeViewProps) {
  // Which sentence is being read (hover or keyboard focus), reported for the evidence threads.
  // Native listeners on the container: the sentences themselves are not interactive elements.
  const box = useRef<HTMLDivElement>(null);
  const report = useRef(onReadSentence);
  useEffect(() => {
    report.current = onReadSentence;
  });
  useEffect(() => {
    const node = box.current;
    if (!node) return undefined;
    const read = (ev: Event) => {
      const li = (ev.target as Element | null)?.closest("[data-sentence]");
      report.current?.(li ? Number(li.getAttribute("data-sentence")) : null);
    };
    const leave = () => {
      report.current?.(null);
    };
    node.addEventListener("mouseover", read);
    node.addEventListener("focusin", read);
    node.addEventListener("mouseleave", leave);
    node.addEventListener("focusout", leave);
    return () => {
      node.removeEventListener("mouseover", read);
      node.removeEventListener("focusin", read);
      node.removeEventListener("mouseleave", leave);
      node.removeEventListener("focusout", leave);
    };
  }, []);
  return (
    <div className={styles.narrative} ref={box}>
      {SECTIONS.map((section) => {
        const rows = sentences
          .map((s, index) => ({ s, index }))
          .filter(({ s }) => s.section === section);
        if (rows.length === 0) return null;
        return (
          <section key={section} aria-labelledby={`sec-${section}`}>
            <h3 id={`sec-${section}`} className={styles.sectionTitle}>
              {SECTION_LABELS[section]}
            </h3>
            <ol className={styles.sentences}>
              {rows.map(({ s, index }) => {
                const report = reports[index];
                const ok = report?.passed;
                return (
                  <li
                    key={index}
                    data-sentence={index}
                    className={ok === false ? styles.failed : undefined}
                  >
                    <span
                      className={ok === false ? styles.markBad : styles.markOk}
                      aria-hidden="true"
                    >
                      {ok === false ? "✗" : ok ? "✓" : "·"}
                    </span>
                    <span className="srOnly">
                      {ok === false ? "Failed verification: " : ok ? "Verified: " : ""}
                    </span>
                    <span>
                      <span className={styles.num}>S{index + 1}</span> {highlighted(s.text, report)}
                    </span>
                    <span className={styles.chips}>
                      {s.evidence_ids.length === 0 ? (
                        <span className={styles.noCite}>no citation</span>
                      ) : (
                        s.evidence_ids.map((id) => (
                          <button
                            key={id}
                            type="button"
                            className={styles.chip}
                            aria-pressed={selectedEvidence === id}
                            onClick={() => {
                              onSelectEvidence(id);
                            }}
                          >
                            {id}
                          </button>
                        ))
                      )}
                    </span>
                  </li>
                );
              })}
            </ol>
          </section>
        );
      })}
    </div>
  );
}

export interface NarrativeEditorProps {
  sentences: Sentence[];
  busy: boolean;
  onSave: (sentences: Sentence[]) => void;
  onCancel: () => void;
}

/** Plain, accessible editing: one text box and one citation box per sentence. */
export function NarrativeEditor({ sentences, busy, onSave, onCancel }: NarrativeEditorProps) {
  const [draft, setDraft] = useState<Sentence[]>(() => sentences.map((s) => ({ ...s })));
  const update = (i: number, patch: Partial<Sentence>) => {
    setDraft((d) => d.map((s, j) => (j === i ? { ...s, ...patch } : s)));
  };
  return (
    <form
      className={styles.editor}
      onSubmit={(e) => {
        e.preventDefault();
        onSave(draft.filter((s) => s.text.trim()));
      }}
    >
      {draft.map((s, i) => (
        <fieldset key={i} className={styles.editRow}>
          <legend>
            Sentence {i + 1} · {SECTION_LABELS[s.section]}
          </legend>
          <label className={styles.editLabel}>
            Text
            <textarea
              value={s.text}
              rows={2}
              onChange={(e) => {
                update(i, { text: e.target.value });
              }}
            />
          </label>
          <label className={styles.editLabel}>
            Evidence IDs (comma separated)
            <input
              value={s.evidence_ids.join(", ")}
              onChange={(e) => {
                update(i, {
                  evidence_ids: e.target.value
                    .split(",")
                    .map((x) => x.trim())
                    .filter(Boolean),
                });
              }}
            />
          </label>
        </fieldset>
      ))}
      <div className={styles.row}>
        <Button type="submit" busy={busy}>
          Save and re-verify
        </Button>
        <Button variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

/** Demo: change the first amount in a "how" sentence by +3% — the verifier must catch it. */
export function injectFault(
  sentences: Sentence[],
): { sentences: Sentence[]; change: string } | null {
  const amount = /\d{1,3}(?:,\d{3})*\.\d{2}(?=\s[A-Z])/;
  const index = sentences.findIndex((s) => s.section === "how" && amount.test(s.text));
  const target = sentences[index];
  if (!target) return null;
  const match = amount.exec(target.text);
  if (!match) return null;
  const old = match[0];
  const value = Number(old.replace(/,/g, "")) * 1.03;
  const next = value.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  const copy = sentences.map((s, i) =>
    i === index ? { ...s, text: s.text.replace(old, next) } : s,
  );
  return { sentences: copy, change: `${old} → ${next} in sentence ${String(index + 1)}` };
}
