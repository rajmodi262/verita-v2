import { useState } from "react";
import type { FormEvent } from "react";

import { useDisposition, useQueueMeta } from "../api/alerts";
import type { DispositionAction } from "../api/alerts";
import { ApiError } from "../api/client";

import { Button, Dialog, Select, TextArea } from "./ui";

export interface DispositionDialogProps {
  alertId: number | null;
  action: DispositionAction;
  onClose: () => void;
  onDone?: () => void;
}

const TITLES: Record<DispositionAction, string> = {
  escalate: "Escalate alert",
  dismiss: "Dismiss alert",
  reopen: "Reopen alert",
};

const REOPEN_REASONS = {
  reopen_error: "Disposition made in error",
  new_information: "New information received",
};

/** Every decision needs a reason code from a closed list — free text alone isn't auditable. */
export function DispositionDialog(props: DispositionDialogProps) {
  // A fresh form (and mutation state) for every alert/action pair.
  return <DispositionForm key={`${String(props.alertId)}-${props.action}`} {...props} />;
}

function DispositionForm({ alertId, action, onClose, onDone }: DispositionDialogProps) {
  const meta = useQueueMeta();
  const disposition = useDisposition();
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");

  const reasons =
    action === "dismiss"
      ? meta.data?.dismiss_reasons
      : action === "escalate"
        ? meta.data?.escalate_reasons
        : REOPEN_REASONS;
  const options = Object.entries(reasons ?? {}).map(([value, label]) => ({ value, label }));

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (alertId === null || !reason) return;
    disposition.mutate(
      { alertId, action, reasonCode: reason, note },
      {
        onSuccess: () => {
          onDone?.();
          onClose();
        },
      },
    );
  };

  const error = disposition.error instanceof ApiError ? disposition.error.message : null;
  return (
    <Dialog title={TITLES[action]} open={alertId !== null} onClose={onClose}>
      <form onSubmit={submit}>
        <Select
          label="Reason"
          placeholder="Choose a reason"
          options={options}
          value={reason}
          onChange={(e) => {
            setReason(e.target.value);
          }}
          required
        />
        <TextArea
          label="Note (optional)"
          rows={3}
          maxLength={2000}
          value={note}
          onChange={(e) => {
            setNote(e.target.value);
          }}
        />
        {error ? <p role="alert">{error}</p> : null}
        <div>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>{" "}
          <Button
            type="submit"
            variant={action === "dismiss" ? "danger" : "primary"}
            disabled={!reason}
            busy={disposition.isPending}
          >
            {TITLES[action]}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
