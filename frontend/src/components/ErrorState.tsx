import { ApiError } from "../api/client";

import styles from "./ErrorState.module.css";
import { Button } from "./ui";

export interface ErrorStateProps {
  error: unknown;
  onRetry?: () => void;
}

/** Shows what failed and the request ID to quote — never a raw stack trace. */
export function ErrorState({ error, onRetry }: ErrorStateProps) {
  const apiError = error instanceof ApiError ? error : null;
  const title = apiError?.message ?? "Something went wrong";
  return (
    <div className={styles.error} role="alert">
      <h2 className={styles.title}>{title}</h2>
      {apiError?.detail ? <p>{apiError.detail}</p> : null}
      {apiError?.requestId ? (
        <p className={styles.meta}>
          Request ID <code>{apiError.requestId}</code>
        </p>
      ) : null}
      {onRetry ? (
        <Button variant="ghost" onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </div>
  );
}
