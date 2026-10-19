/**
 * Guards the accessibility promise in PIVOT §13.7: every text token meets WCAG AAA (7:1) on
 * every ground it can appear on, and every non-text mark meets 3:1 (WCAG 1.4.11), in both themes.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

// Vitest stubs CSS imports, so read the source file directly (tests run from the package root).
const css = readFileSync(join(process.cwd(), "src", "styles", "tokens.css"), "utf8");

function block(selector: string): Record<string, string> {
  const start = css.indexOf(selector);
  if (start < 0) throw new Error(`selector ${selector} not found`);
  const body = css.slice(css.indexOf("{", start) + 1, css.indexOf("}", start));
  const out: Record<string, string> = {};
  for (const match of body.matchAll(/--(color-[a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;/g)) {
    out[match[1]!] = match[2]!;
  }
  return out;
}

function luminance(hex: string): number {
  const channels = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const [r, g, b] = channels.map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!;
}

export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi! + 0.05) / (lo! + 0.05);
}

const GROUNDS = ["color-bg", "color-surface", "color-surface-2"];
const TEXT = [
  "color-ink",
  "color-ink-muted",
  "color-alert-text",
  "color-verified-text",
  "color-link",
];
const MARKS = ["color-border", "color-alert", "color-verified", "color-focus"];

describe.each([
  ["paper", ":root,"],
  ["night", '[data-theme="night"]'],
])("%s theme", (_name, selector) => {
  const tokens = block(selector);

  it.each(TEXT.flatMap((t) => GROUNDS.map((g) => [t, g] as const)))(
    "%s on %s is AAA (>= 7:1)",
    (text, ground) => {
      expect(contrast(tokens[text]!, tokens[ground]!)).toBeGreaterThanOrEqual(7);
    },
  );

  it.each(MARKS.flatMap((m) => GROUNDS.map((g) => [m, g] as const)))(
    "%s on %s is visible (>= 3:1)",
    (mark, ground) => {
      expect(contrast(tokens[mark]!, tokens[ground]!)).toBeGreaterThanOrEqual(3);
    },
  );

  it("primary button text on ink is AAA", () => {
    expect(contrast(tokens["color-on-ink"]!, tokens["color-border"]!)).toBeGreaterThanOrEqual(7);
  });
});

it("contrast() matches the WCAG reference values", () => {
  expect(contrast("#000000", "#ffffff")).toBeCloseTo(21, 5);
  expect(contrast("#777777", "#ffffff")).toBeCloseTo(4.48, 2);
});
