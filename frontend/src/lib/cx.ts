/** Join class names, skipping falsy values (CSS-module lookups may be undefined). */
export function cx(...names: (string | false | null | undefined)[]): string {
  return names.filter(Boolean).join(" ");
}
