/** Minimal chart maths: linear scales and "nice" ticks (no charting library needed). */

export interface Scale {
  (value: number): number;
  domain: readonly [number, number];
  range: readonly [number, number];
}

export function linear(domain: readonly [number, number], range: readonly [number, number]): Scale {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  const span = d1 - d0 || 1;
  const scale = (value: number) => r0 + ((value - d0) / span) * (r1 - r0);
  return Object.assign(scale, { domain, range });
}

/** Round step (1, 2 or 5 × 10ⁿ) giving about ``count`` ticks across [lo, hi]. */
export function niceStep(lo: number, hi: number, count = 5): number {
  const raw = (hi - lo) / Math.max(count, 1);
  if (raw <= 0 || !Number.isFinite(raw)) return 1;
  const power = 10 ** Math.floor(Math.log10(raw));
  const unit = raw / power;
  const nice = unit < 1.5 ? 1 : unit < 3.5 ? 2 : unit < 7.5 ? 5 : 10;
  return nice * power;
}

export function ticks(lo: number, hi: number, count = 5): number[] {
  const step = niceStep(lo, hi, count);
  const out: number[] = [];
  const start = Math.ceil(lo / step) * step;
  for (let v = start; v <= hi + step * 1e-9; v += step) out.push(Number(v.toPrecision(12)));
  return out;
}

/** Upper bound rounded up to a nice step, so the top tick sits at or above the data. */
export function niceMax(value: number, count = 5): number {
  if (value <= 0) return 1;
  const step = niceStep(0, value, count);
  return Math.ceil(value / step) * step;
}

/** SVG path through points, skipping none (callers filter missing values first). */
export function linePath(points: readonly (readonly [number, number])[]): string {
  return points
    .map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`)
    .join("");
}

/** Closed band between an upper and a lower line sharing x positions. */
export function bandPath(
  xs: readonly number[],
  upper: readonly number[],
  lower: readonly number[],
): string {
  if (xs.length === 0) return "";
  const top = xs.map((x, i) => [x, upper[i] ?? 0] as const);
  const bottom = xs.map((x, i) => [x, lower[i] ?? 0] as const).reverse();
  return `${linePath([...top, ...bottom])}Z`;
}
