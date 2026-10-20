import { useEffect, useRef, useState } from "react";
import type { ChangeEvent } from "react";

import type { CaseDetail, EvidenceItem } from "../../api/cases";
import { parseCaseFile, verifyCaseFile } from "../../lib/caseFile";
import type { CaseExport, FileCheck } from "../../lib/caseFile";
import { dateTime } from "../../lib/format";
import { GuillocheSeal } from "../seal/GuillocheSeal";
import { HashText, Stamp } from "../ui";

import styles from "./Case.module.css";

const KIND_LABELS: Record<string, string> = {
  case: "Case summary",
  alert: "Alerts",
  path: "Dominant paths",
  txn: "Payments",
  reason: "Model reasons",
  motif: "Structural signals",
};
const KIND_ORDER = ["case", "alert", "path", "txn", "reason", "motif"];

function value(v: unknown): string {
  if (Array.isArray(v)) return v.map(value).join(", ");
  if (v !== null && typeof v === "object") return JSON.stringify(v);
  return String(v);
}

export function EvidencePanel({
  evidence,
  selected,
  onSelect,
}: {
  evidence: EvidenceItem[];
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const item = evidence.find((e) => e.id === selected);
  return (
    <div className={styles.evidence}>
      {KIND_ORDER.map((kind) => {
        const items = evidence.filter((e) => e.kind === kind);
        if (items.length === 0) return null;
        return (
          <details key={kind} open={kind !== "txn" || items.some((i) => i.id === selected)}>
            <summary>
              {KIND_LABELS[kind] ?? kind} <span className={styles.count}>{items.length}</span>
            </summary>
            <ul className={styles.evList}>
              {items.map((e) => (
                <li key={e.id}>
                  <button
                    type="button"
                    className={styles.evButton}
                    aria-pressed={selected === e.id}
                    onClick={() => {
                      onSelect(e.id);
                    }}
                  >
                    {e.id}
                  </button>
                </li>
              ))}
            </ul>
          </details>
        );
      })}
      {item ? (
        <section className={styles.preview} aria-label={`Evidence ${item.id}`} aria-live="polite">
          <h3 className={styles.previewTitle}>{item.id}</h3>
          <dl>
            {Object.entries(item.payload).map(([k, v]) => (
              <div key={k} className={styles.kv}>
                <dt>{k}</dt>
                <dd>{value(v)}</dd>
              </div>
            ))}
          </dl>
        </section>
      ) : (
        <p className={styles.note}>
          Select an evidence ID — in this list or on any sentence — to see what it establishes.
        </p>
      )}
    </div>
  );
}

export function VerifierPanel({ detail }: { detail: CaseDetail }) {
  const report = detail.verification?.report;
  if (!report)
    return (
      <p className={styles.note}>The verifier runs automatically after every draft or edit.</p>
    );
  const failing = report.sentences.filter((s) => !s.passed);
  const claims = report.sentences.reduce((n, s) => n + s.claims.length, 0);
  return (
    <div className={styles.verifier} aria-live="polite">
      <p className={styles.verdict}>
        {report.passed ? (
          <Stamp tone="verified">Verified</Stamp>
        ) : (
          <Stamp tone="alert">Failed</Stamp>
        )}{" "}
        {claims} claims checked in {report.sentences.length} sentences · verifier{" "}
        <code>{report.verifier_version}</code>
      </p>
      <ul className={styles.coverage} aria-label="Coverage">
        {Object.entries(report.coverage).map(([k, ok]) => (
          <li key={k}>
            <span aria-hidden="true">{ok ? "✓" : "✗"}</span> {ok ? "States" : "Missing"} the {k}
          </li>
        ))}
      </ul>
      {report.errors.length ? (
        <ul className={styles.errors}>
          {report.errors.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      ) : null}
      {(failing.length ? failing : report.sentences).map((s) => (
        <section
          key={s.index}
          className={styles.claimGroup}
          aria-label={`Sentence ${String(s.index + 1)}`}
        >
          <h4>
            S{s.index + 1} · {s.section} {s.passed ? "✓" : "✗"}
          </h4>
          {s.errors.map((e) => (
            <p key={e} className={styles.bad}>
              {e}
            </p>
          ))}
          <ul className={styles.claims}>
            {s.claims.map((c, i) => (
              <li key={i} className={c.passed ? styles.good : styles.bad}>
                <span aria-hidden="true">{c.passed ? "✓" : "✗"}</span> <code>{c.text}</code> —{" "}
                {c.passed ? `matches ${c.expected ?? ""}` : c.detail}
              </li>
            ))}
            {s.claims.length === 0 ? <li className={styles.note}>No checkable claims.</li> : null}
          </ul>
        </section>
      ))}
    </div>
  );
}

export function LedgerPanel({ detail }: { detail: CaseDetail }) {
  return (
    <div>
      <p className={styles.verdict}>
        {detail.ledger.valid ? (
          <Stamp tone="verified">Chain intact</Stamp>
        ) : (
          <Stamp tone="alert">Chain broken</Stamp>
        )}{" "}
        {detail.events.length} events, append-only (the database rejects UPDATE and DELETE)
      </p>
      <ol className={styles.ledger}>
        {detail.events.map((e) => (
          <li key={e.seq}>
            <span className={styles.mono}>#{e.seq}</span> <strong>{e.type}</strong>{" "}
            {e.actor ? `by ${e.actor}` : ""} ·{" "}
            <span className={styles.mono}>{dateTime(e.created_at)}</span>
            <div>
              <HashText value={e.hash} label={`hash of event ${String(e.seq)}`} />
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

/** Drop or choose a downloaded case file; it is verified here, in the browser. */
export function VerifyDropzone({ publicKeyPem }: { publicKeyPem: string | undefined }) {
  const [result, setResult] = useState<FileCheck | null>(null);
  const [file, setFile] = useState<CaseExport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [over, setOver] = useState(false);

  const check = async (file: File) => {
    setName(file.name);
    setResult(null);
    setError(null);
    try {
      const parsed = parseCaseFile(await file.text());
      setFile(parsed);
      setResult(await verifyCaseFile(parsed, publicKeyPem));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not read the file.");
    }
  };

  // Drag-and-drop is an enhancement on top of the (keyboard-accessible) file input, so the
  // listeners are attached to the drop target directly rather than as JSX props.
  const zone = useRef<HTMLLabelElement>(null);
  const checkRef = useRef(check);
  useEffect(() => {
    checkRef.current = check;
  });
  useEffect(() => {
    const node = zone.current;
    if (!node) return undefined;
    const over = (e: DragEvent) => {
      e.preventDefault();
      setOver(true);
    };
    const leave = () => {
      setOver(false);
    };
    const drop = (e: DragEvent) => {
      e.preventDefault();
      setOver(false);
      const file = e.dataTransfer?.files[0];
      if (file) void checkRef.current(file);
    };
    node.addEventListener("dragover", over);
    node.addEventListener("dragleave", leave);
    node.addEventListener("drop", drop);
    return () => {
      node.removeEventListener("dragover", over);
      node.removeEventListener("dragleave", leave);
      node.removeEventListener("drop", drop);
    };
  }, []);
  const onPick = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) void check(file);
  };

  return (
    <div className={styles.verify}>
      <label ref={zone} className={over ? styles.dropOver : styles.drop}>
        <span>Drop a case-file JSON here, or choose one</span>
        <input type="file" accept="application/json,.json" onChange={onPick} />
      </label>
      <p className={styles.note}>
        Checked with the published key (
        {publicKeyPem ? "loaded" : "not loaded — using the key in the file"}). Nothing is uploaded.
      </p>
      <div aria-live="polite">
        {error ? <p className={styles.bad}>{error}</p> : null}
        {result ? (
          <div className={styles.verifyResult}>
            {file ? (
              <GuillocheSeal
                key={`${name}-${String(result.valid)}`}
                root={file.merkle_root}
                leaves={Object.keys(file.leaves).sort()}
                broken={result.changedLeaves}
                serial={String(file.case_id).padStart(6, "0")}
                size={220}
              />
            ) : null}
            <p>
              {result.valid ? (
                <Stamp tone="verified">Valid</Stamp>
              ) : (
                <Stamp tone="alert">Invalid</Stamp>
              )}{" "}
              <span className={styles.mono}>{name}</span>
            </p>
            <ul>
              <li>
                Signature: {result.signatureValid ? "✓ valid" : "✗ invalid"} (key {result.keyId})
              </li>
              <li>
                Merkle root: {result.rootMatches ? "✓ matches" : "✗ does not match the signed root"}
              </li>
              {result.changedLeaves.map((leaf) => (
                <li key={leaf} className={styles.bad}>
                  ✗ <code>{leaf}</code> changed since signing
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </div>
  );
}
