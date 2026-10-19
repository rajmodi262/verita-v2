import { useId } from "react";
import type { TextareaHTMLAttributes } from "react";

import styles from "./Field.module.css";

export interface TextAreaProps extends Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "id"> {
  label: string;
}

export function TextArea({ label, ...area }: TextAreaProps) {
  const id = useId();
  return (
    <div className={styles.field}>
      <label htmlFor={id} className={styles.label}>
        {label}
      </label>
      <textarea {...area} id={id} className={styles.input} />
    </div>
  );
}
