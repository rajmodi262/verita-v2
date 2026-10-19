import { Navigate, useLocation } from "react-router-dom";

import { useMe } from "../api/auth";
import { ErrorState } from "../components/ErrorState";

import { AppShell } from "./layout/AppShell";

/** Gate for the workspace: no session → login (remembering where the user was going). */
export function RequireAuth() {
  const me = useMe();
  const location = useLocation();

  if (me.isPending) {
    return (
      <p role="status" aria-live="polite">
        Checking your session…
      </p>
    );
  }
  if (me.isError) {
    return <ErrorState error={me.error} onRetry={() => void me.refetch()} />;
  }
  if (me.data === null) {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?next=${next}`} replace />;
  }
  return <AppShell user={me.data} />;
}
