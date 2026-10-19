import { useId } from "react";

import styles from "./Slider.module.css";

export interface SliderProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  /** Visible unit after the numeric twin, e.g. "analysts". */
  unit?: string;
  onChange: (value: number) => void;
}

/** Range input with a numeric twin (PIVOT §13): drag for feel, type for precision. */
export function Slider({ label, value, min, max, step = 1, unit, onChange }: SliderProps) {
  const id = useId();
  const clamp = (v: number) => Math.min(max, Math.max(min, v));
  return (
    <div className={styles.slider}>
      <label htmlFor={id} className={styles.label}>
        {label}
      </label>
      <div className={styles.row}>
        <input
          id={id}
          type="range"
          className={styles.range}
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={(e) => {
            onChange(clamp(Number(e.target.value)));
          }}
        />
        <input
          type="number"
          className={styles.number}
          aria-label={`${label} (exact)`}
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={(e) => {
            const next = Number(e.target.value);
            if (e.target.value !== "" && Number.isFinite(next)) onChange(clamp(next));
          }}
        />
        {unit ? <span className={styles.unit}>{unit}</span> : null}
      </div>
    </div>
  );
}
