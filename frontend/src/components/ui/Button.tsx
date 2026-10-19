import type { ButtonHTMLAttributes } from "react";

import { cx } from "../../lib/cx";

import styles from "./Button.module.css";

export type ButtonVariant = "primary" | "ghost" | "danger";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  busy?: boolean;
}

/** Square, ink-bordered, mono-labelled — "stamped and certain" (DESIGN.md §5). */
export function Button({
  variant = "primary",
  busy = false,
  type = "button",
  className,
  disabled,
  children,
  ...rest
}: ButtonProps) {
  return (
    <button
      {...rest}
      type={type}
      className={cx(styles.button, styles[variant], className)}
      disabled={disabled === true || busy}
      aria-busy={busy || undefined}
    >
      {children}
    </button>
  );
}
