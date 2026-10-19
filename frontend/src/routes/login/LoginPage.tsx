import { useState } from "react";
import type { FormEvent } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";

import { useLogin, useMe } from "../../api/auth";
import { ApiError } from "../../api/client";
import { Button, Field } from "../../components/ui";

import styles from "./LoginPage.module.css";

/** Only same-app paths are allowed as a post-login redirect (no open redirects). */
export function safeNext(raw: string | null): string {
  if (!raw?.startsWith("/") || raw.startsWith("//") || raw.startsWith("/\\")) return "/queue";
  return raw;
}

const INVALID_CREDENTIALS_MESSAGE =
  "That username and password don't match. After 5 failed attempts the account locks for 15 minutes.";

export default function LoginPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const me = useMe();
  const login = useLogin();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const next = safeNext(params.get("next"));

  if (me.data) return <Navigate to={next} replace />;

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    login.mutate(
      { username, password },
      { onSuccess: () => void navigate(next, { replace: true }) },
    );
  };

  const error = login.error instanceof ApiError ? login.error : null;
  let message: string | undefined;
  if (error) {
    message = error.slug === "invalid-credentials" ? INVALID_CREDENTIALS_MESSAGE : error.message;
  }

  return (
    <main id="main" className={styles.page}>
      <form className={styles.card} onSubmit={onSubmit} noValidate>
        <p className={styles.label}>Verita · Sign in</p>
        <h1 className={styles.title}>Open the case file</h1>
        <Field
          label="Username"
          name="username"
          autoComplete="username"
          value={username}
          onChange={(e) => {
            setUsername(e.target.value);
          }}
          required
        />
        <Field
          label="Password"
          name="password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => {
            setPassword(e.target.value);
          }}
          required
        />
        {message ? (
          <p className={styles.error} role="alert">
            {message}
          </p>
        ) : null}
        <Button type="submit" busy={login.isPending} disabled={!username || !password}>
          {login.isPending ? "Signing in…" : "Sign in"}
        </Button>
      </form>
    </main>
  );
}
