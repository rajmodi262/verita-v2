import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useParams } from "react-router-dom";

import { useMe } from "../../api/auth";
import {
  exportUrl,
  useApprove,
  useCase,
  useCaseMeta,
  useClose,
  useDraft,
  useEditNarrative,
  useJob,
  usePublicKeys,
  useReturn,
  useCaseExport,
  useSignatureCheck,
  useSubmit,
  useVerify,
} from "../../api/cases";
import type { CaseDetail } from "../../api/cases";
import { injectFault, NarrativeEditor, NarrativeView } from "../../components/case/Narrative";
import {
  EvidencePanel,
  LedgerPanel,
  VerifierPanel,
  VerifyDropzone,
} from "../../components/case/Panels";
import { ErrorState } from "../../components/ErrorState";
import { GuillocheSeal } from "../../components/seal/GuillocheSeal";
import {
  Button,
  Dialog,
  EmptyState,
  HashText,
  Panel,
  Select,
  Stamp,
  TextArea,
} from "../../components/ui";
import { dateTime } from "../../lib/format";

import styles from "./CaseFilePage.module.css";

const STATE_LABELS: Record<string, { label: string; tone: "alert" | "verified" | null }> = {
  draft: { label: "Draft", tone: null },
  verified: { label: "Verified", tone: "verified" },
  submitted: { label: "Awaiting approval", tone: "alert" },
  signed: { label: "Signed", tone: "verified" },
  returned: { label: "Returned", tone: "alert" },
  closed: { label: "Closed — no filing", tone: null },
};

function StateMark({ state }: { state: string }) {
  const s = STATE_LABELS[state] ?? { label: state, tone: null };
  return s.tone ? (
    <Stamp tone={s.tone}>{s.label}</Stamp>
  ) : (
    <span className={styles.plainState}>{s.label}</span>
  );
}

function ReasonDialog({
  title,
  reasons,
  open,
  busy,
  onClose,
  onSubmit,
}: {
  title: string;
  reasons: Record<string, string>;
  open: boolean;
  busy: boolean;
  onClose: () => void;
  onSubmit: (reason: string, note: string) => void;
}) {
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (reason) onSubmit(reason, note);
  };
  return (
    <Dialog
      title={title}
      open={open}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="reason-form" busy={busy} disabled={!reason}>
            {title}
          </Button>
        </>
      }
    >
      <form id="reason-form" onSubmit={submit} className={styles.dialogForm}>
        <Select
          label="Reason"
          placeholder="Choose a reason"
          required
          value={reason}
          options={Object.entries(reasons).map(([value, label]) => ({ value, label }))}
          onChange={(e) => {
            setReason(e.target.value);
          }}
        />
        <TextArea
          label="Note (optional)"
          value={note}
          onChange={(e) => {
            setNote(e.target.value);
          }}
        />
      </form>
    </Dialog>
  );
}

function SignedPanel({ detail }: { detail: CaseDetail }) {
  const sig = detail.signature;
  const check = useSignatureCheck(detail.id, sig !== null);
  const keys = usePublicKeys();
  const signed = useCaseExport(detail.id, sig !== null);
  if (!sig) return null;
  return (
    <Panel title="Signed case file" label="Seal">
      <div className={styles.sealRow}>
        {signed.data ? (
          <GuillocheSeal
            root={sig.merkle_root}
            leaves={Object.keys(signed.data.leaves).sort()}
            broken={check.data?.changed_leaves ?? []}
            serial={String(detail.id).padStart(6, "0")}
            size={300}
          />
        ) : (
          <div className={styles.sealPending} aria-hidden="true" />
        )}
        <dl className={styles.sigList}>
          <div>
            <dt>Merkle root</dt>
            <dd>
              <HashText value={sig.merkle_root} label="Merkle root" />
            </dd>
          </div>
          <div>
            <dt>Key ID</dt>
            <dd className={styles.mono}>{sig.key_id} · Ed25519</dd>
          </div>
          <div>
            <dt>Signed</dt>
            <dd>
              by {sig.signed_by} at <span className={styles.mono}>{dateTime(sig.signed_at)}</span>
            </dd>
          </div>
          <div>
            <dt>Server check</dt>
            <dd>
              {check.data
                ? check.data.valid
                  ? "✓ signature, root and ledger verified"
                  : `✗ ${check.data.changed_leaves.join(", ") || "signature or root mismatch"}`
                : "checking…"}
            </dd>
          </div>
        </dl>
      </div>
      <div className={styles.row}>
        <a className={styles.download} href={exportUrl(detail.id, "json")} download>
          Download signed JSON
        </a>
        <a className={styles.download} href={exportUrl(detail.id, "pdf")} download>
          Download PDF
        </a>
        <a className={styles.downloadGhost} href={exportUrl(detail.id, "tampered")} download>
          Download a tampered copy (demo)
        </a>
      </div>
      <h3 className={styles.subTitle}>Verify a file</h3>
      <VerifyDropzone publicKeyPem={keys.data?.keys[0]?.public_key_pem} />
      <p className={styles.note}>
        Offline: <code>verita-verify case-{detail.id}.json --pubkey keys/verita-pub.pem</code>
      </p>
    </Panel>
  );
}

export default function CaseFilePage() {
  const { id = "" } = useParams();
  const caseId = Number(id);
  const me = useMe();
  const meta = useCaseMeta();
  const detail = useCase(caseId);
  const draft = useDraft(caseId);
  const [jobId, setJobId] = useState<number | null>(null);
  const job = useJob(jobId, caseId);
  const edit = useEditNarrative(caseId);
  const verify = useVerify(caseId);
  const submit = useSubmit(caseId);
  const approve = useApprove(caseId);
  const ret = useReturn(caseId);
  const close = useClose(caseId);
  const [editing, setEditing] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [dialog, setDialog] = useState<"return" | "close" | null>(null);
  const [injected, setInjected] = useState<string | null>(null);
  const [mode, setMode] = useState<"auto" | "offline">("auto");

  if (!Number.isInteger(caseId) || caseId <= 0)
    return <ErrorState error={new Error("Invalid case id")} />;
  if (detail.isError)
    return <ErrorState error={detail.error} onRetry={() => void detail.refetch()} />;
  if (detail.isPending) {
    return (
      <p role="status" aria-live="polite">
        Loading case file…
      </p>
    );
  }

  const d = detail.data;
  const p = d.permissions;
  const reports = d.verification?.report.sentences ?? [];
  const running =
    jobId !== null &&
    (job.data === undefined || job.data.status === "queued" || job.data.status === "running");
  const actionError = [draft, edit, verify, submit, approve, ret, close].find(
    (m) => m.isError,
  )?.error;
  const offlineOnly = meta.data?.offline_only ?? true;

  const startDraft = () => {
    setInjected(null);
    draft.mutate(offlineOnly ? "offline" : mode, {
      onSuccess: (j) => {
        setJobId(j.id);
      },
    });
  };

  return (
    <div className={styles.page}>
      <nav aria-label="Breadcrumb" className={styles.crumbs}>
        <Link to="/cases">Case files</Link> / <span aria-current="page">Case {d.id}</span>
      </nav>
      <header className={styles.header}>
        <div>
          <p className={styles.kicker}>
            Case file C-{d.id} · opened by {d.created_by} · {d.alert_ids.length} alert
            {d.alert_ids.length === 1 ? "" : "s"}
          </p>
          <h1 className={styles.title}>{d.title}</h1>
        </div>
        <StateMark state={d.state} />
      </header>

      <div className={styles.actions} role="group" aria-label="Case actions">
        {p.edit ? (
          <>
            {!offlineOnly ? (
              <Select
                label="Writer"
                value={mode}
                options={[
                  {
                    value: "auto",
                    label: `LLM (${meta.data?.llm_providers.join(" → ") ?? ""}), offline fallback`,
                  },
                  { value: "offline", label: "Offline template" },
                ]}
                onChange={(e) => {
                  setMode(e.target.value === "offline" ? "offline" : "auto");
                }}
              />
            ) : null}
            <Button onClick={startDraft} busy={draft.isPending || running} disabled={editing}>
              {d.narrative ? "Redraft narrative" : "Draft narrative"}
            </Button>
            {d.narrative ? (
              <>
                <Button
                  variant="ghost"
                  disabled={editing}
                  onClick={() => {
                    setEditing(true);
                  }}
                >
                  Edit narrative
                </Button>
                <Button
                  variant="ghost"
                  busy={verify.isPending}
                  onClick={() => {
                    verify.mutate({});
                  }}
                >
                  Re-run verifier
                </Button>
                <Button
                  variant="ghost"
                  disabled={editing || edit.isPending}
                  onClick={() => {
                    if (!d.narrative) return;
                    const fault = injectFault(d.narrative.sentences);
                    if (!fault) return;
                    setInjected(fault.change);
                    edit.mutate({ sentences: fault.sentences });
                  }}
                >
                  Inject a fault (demo)
                </Button>
              </>
            ) : null}
          </>
        ) : null}
        {d.state === "verified" || d.state === "draft" ? (
          <Button
            onClick={() => {
              submit.mutate({});
            }}
            disabled={!p.submit}
            busy={submit.isPending}
            aria-describedby="submit-why"
          >
            Submit for approval
          </Button>
        ) : null}
        {d.state === "submitted" ? (
          <>
            <Button
              onClick={() => {
                approve.mutate({});
              }}
              disabled={!p.approve}
              busy={approve.isPending}
              aria-describedby="approve-why"
            >
              Approve and sign
            </Button>
            {p.return ? (
              <Button
                variant="ghost"
                onClick={() => {
                  setDialog("return");
                }}
              >
                Return to analyst
              </Button>
            ) : null}
          </>
        ) : null}
        {p.close ? (
          <Button
            variant="danger"
            onClick={() => {
              setDialog("close");
            }}
          >
            Close without filing
          </Button>
        ) : null}
      </div>
      {d.state === "draft" && d.narrative && !p.submit ? (
        <p id="submit-why" className={styles.why}>
          Submission is blocked until every sentence passes the verifier.
        </p>
      ) : null}
      {d.state === "submitted" && !p.approve ? (
        <p id="approve-why" className={styles.why}>
          {p.approve_blockers.join(" ")}
        </p>
      ) : null}
      <div aria-live="polite" className={styles.status}>
        {running ? <p>Drafting… ({job.data?.progress ?? "queued"})</p> : null}
        {job.data?.status === "failed" ? (
          <p className={styles.bad}>Drafting failed: {job.data.error}</p>
        ) : null}
        {injected ? (
          <p>Injected a fault: {injected}. The verifier re-ran on the edited narrative.</p>
        ) : null}
      </div>
      {actionError ? <ErrorState error={actionError} /> : null}

      <div className={styles.grid}>
        <Panel title="Evidence" label="Exhibits">
          <EvidencePanel evidence={d.evidence} selected={selected} onSelect={setSelected} />
        </Panel>
        <Panel
          title="Narrative"
          label={
            d.narrative
              ? `v${String(d.narrative.version)} · ${d.narrative.mode === "llm" ? `LLM: ${d.narrative.provider} ${d.narrative.model}` : d.narrative.mode === "edit" ? `edited by ${d.narrative.created_by}` : "offline template"}`
              : "Not drafted"
          }
        >
          {!d.narrative ? (
            <EmptyState title="No narrative yet">
              <p>
                Draft one from the evidence. Every sentence must cite evidence, and every number in
                it is checked against what it cites.
              </p>
            </EmptyState>
          ) : editing ? (
            <NarrativeEditor
              sentences={d.narrative.sentences}
              busy={edit.isPending}
              onCancel={() => {
                setEditing(false);
              }}
              onSave={(sentences) => {
                edit.mutate(
                  { sentences },
                  {
                    onSuccess: () => {
                      setEditing(false);
                    },
                  },
                );
              }}
            />
          ) : (
            <NarrativeView
              sentences={d.narrative.sentences}
              reports={reports}
              selectedEvidence={selected}
              onSelectEvidence={setSelected}
            />
          )}
        </Panel>
        <Panel title="Verifier" label="Claim by claim">
          <VerifierPanel detail={d} />
        </Panel>
      </div>

      <SignedPanel detail={d} />

      <Panel title="Ledger" label="Hash chain">
        <LedgerPanel detail={d} />
      </Panel>

      <ReasonDialog
        key={`return-${String(dialog === "return")}`}
        title="Return to analyst"
        reasons={meta.data?.return_reasons ?? {}}
        open={dialog === "return"}
        busy={ret.isPending}
        onClose={() => {
          setDialog(null);
        }}
        onSubmit={(reason, note) => {
          ret.mutate(
            { reason, note },
            {
              onSuccess: () => {
                setDialog(null);
              },
            },
          );
        }}
      />
      <ReasonDialog
        key={`close-${String(dialog === "close")}`}
        title="Close without filing"
        reasons={meta.data?.close_reasons ?? {}}
        open={dialog === "close"}
        busy={close.isPending}
        onClose={() => {
          setDialog(null);
        }}
        onSubmit={(reason, note) => {
          close.mutate(
            { reason, note },
            {
              onSuccess: () => {
                setDialog(null);
              },
            },
          );
        }}
      />
      {me.data?.role === "reviewer" ? (
        <p className={styles.note}>
          Reviewer access is read-only; the signed file and its verification are yours to check.
        </p>
      ) : null}
    </div>
  );
}
