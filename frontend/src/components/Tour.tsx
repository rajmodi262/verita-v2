import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { Button } from "./ui";

import styles from "./Tour.module.css";

export interface TourStep {
  path: string;
  title: string;
  body: string;
}

/** Eight stops across the demo path (PIVOT §13.6). Each names what to look at on its page. */
export const TOUR: TourStep[] = [
  {
    path: "/queue",
    title: "1 · The alert queue",
    body: "Account-days ranked by risk on the out-of-sample test window. J/K moves, Enter opens. Open the top alert.",
  },
  {
    path: "/queue",
    title: "2 · Why is this an alert?",
    body: "On an alert: the model's top reasons in plain English, each with an evidence ID, and the money-flow graph with the dominant path highlighted.",
  },
  {
    path: "/capacity",
    title: "3 · What will we miss?",
    body: "Drag the analysts slider. The guarantee stamp says whether a 95% recall guarantee holds or how many analysts it needs.",
  },
  {
    path: "/capacity",
    title: "4 · Was the guarantee kept?",
    body: "The coverage panel replays the guarantee day by day against the true labels: static conformal vs adaptive conformal.",
  },
  {
    path: "/cases",
    title: "5 · A case file",
    body: "Open a case: every narrative sentence cites evidence, and the verifier checks each amount, date and account against what it cites.",
  },
  {
    path: "/cases",
    title: "6 · Catch a fault",
    body: "On a draft case, “Inject a fault” changes one amount. The verifier marks the claim and blocks submission.",
  },
  {
    path: "/cases",
    title: "7 · Prove it",
    body: "On a signed case, download the tampered copy and drop it on “Verify a file”: the browser names the changed evidence item.",
  },
  {
    path: "/evidence-room",
    title: "8 · Challenge the model",
    body: "The Evidence Room shows every evaluation with intervals, baselines, failures and lineage — all read from one generated report.",
  },
];

const KEY = "verita.tour";

function load(): number | null {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw === "done") return null;
    return raw === null ? 0 : Math.min(Math.max(Number(raw) || 0, 0), TOUR.length - 1);
  } catch {
    return 0;
  }
}

function save(value: number | "done") {
  try {
    localStorage.setItem(KEY, String(value));
  } catch {
    // private mode: the tour simply does not remember
  }
}

/** A skippable, non-modal walkthrough for reviewers. */
export function Tour() {
  const [step, setStep] = useState<number | null>(load);
  const navigate = useNavigate();
  const location = useLocation();
  if (step === null) {
    return (
      <button
        type="button"
        className={styles.restart}
        onClick={() => {
          save(0);
          setStep(0);
        }}
      >
        Restart the tour
      </button>
    );
  }
  const current = TOUR[step];
  if (!current) return null;
  const go = (next: number) => {
    const target = TOUR[next];
    if (!target) return;
    save(next);
    setStep(next);
    if (!location.pathname.startsWith(target.path)) void navigate(target.path);
  };
  return (
    <aside className={styles.tour} aria-label="Guided tour" aria-live="polite">
      <p className={styles.kicker}>
        Guided tour · {step + 1} of {TOUR.length}
      </p>
      <h2 className={styles.title}>{current.title}</h2>
      <p>{current.body}</p>
      <div className={styles.row}>
        {step > 0 ? (
          <Button
            variant="ghost"
            onClick={() => {
              go(step - 1);
            }}
          >
            Back
          </Button>
        ) : null}
        {step < TOUR.length - 1 ? (
          <Button
            onClick={() => {
              go(step + 1);
            }}
          >
            Next
          </Button>
        ) : (
          <Button
            onClick={() => {
              save("done");
              setStep(null);
            }}
          >
            Finish
          </Button>
        )}
        <Button
          variant="ghost"
          onClick={() => {
            save("done");
            setStep(null);
          }}
        >
          Skip tour
        </Button>
      </div>
    </aside>
  );
}
