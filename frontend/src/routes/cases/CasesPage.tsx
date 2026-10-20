import { Link } from "react-router-dom";

import { useCases } from "../../api/cases";
import { ErrorState } from "../../components/ErrorState";
import { EmptyState, Stamp } from "../../components/ui";
import { dateTime } from "../../lib/format";

import styles from "./CasesPage.module.css";

const STAMPS: Record<string, { label: string; tone: "alert" | "verified" } | undefined> = {
  verified: { label: "Verified", tone: "verified" },
  submitted: { label: "Awaiting approval", tone: "alert" },
  signed: { label: "Signed", tone: "verified" },
  returned: { label: "Returned", tone: "alert" },
};

export default function CasesPage() {
  const cases = useCases();
  if (cases.isError) return <ErrorState error={cases.error} onRetry={() => void cases.refetch()} />;
  const items = cases.data?.items ?? [];
  return (
    <div className={styles.page}>
      <header>
        <h1>Case files</h1>
        <p className={styles.sub}>
          Evidence-cited narratives, verified claim by claim, approved by a second person and
          signed.
        </p>
      </header>
      {cases.isPending ? (
        <p role="status">Loading cases…</p>
      ) : items.length === 0 ? (
        <EmptyState title="No case files yet">
          <p>
            Open an alert from the <Link to="/queue">queue</Link> and choose “Open a case file”.
          </p>
        </EmptyState>
      ) : (
        <table className={styles.table}>
          <caption className="srOnly">Case files, most recently updated first</caption>
          <thead>
            <tr>
              <th scope="col">Case</th>
              <th scope="col">Title</th>
              <th scope="col">State</th>
              <th scope="col">Alerts</th>
              <th scope="col">Opened by</th>
              <th scope="col">Updated</th>
            </tr>
          </thead>
          <tbody>
            {items.map((c) => {
              const stamp = STAMPS[c.state];
              return (
                <tr key={c.id}>
                  <td className={styles.mono}>
                    <Link to={`/cases/${String(c.id)}`}>C-{c.id}</Link>
                  </td>
                  <td>{c.title}</td>
                  <td>{stamp ? <Stamp tone={stamp.tone}>{stamp.label}</Stamp> : c.state}</td>
                  <td className={styles.mono}>{c.alerts}</td>
                  <td>{c.created_by}</td>
                  <td className={styles.mono}>{dateTime(c.updated_at)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
