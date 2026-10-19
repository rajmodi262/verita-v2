/** Formatting for figures that testify (DESIGN.md "Mono Witness Rule"). */

export function money(amount: number, currency: string): string {
  const value = amount.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return `${value} ${currency}`;
}

export function score(value: number): string {
  return value.toFixed(3);
}

export function percent(value: number, digits = 1): string {
  return `${(value * 100).toFixed(digits)}%`;
}

export function dateTime(iso: string): string {
  return iso.replace("T", " ").slice(0, 16);
}

/** "123:8000ABCDE" → bank 123, account 8000ABCDE. */
export function splitAccount(id: string): { bank: string; account: string } {
  const [bank = "", account = ""] = id.split(":");
  return { bank, account };
}

export function typologyLabel(t: string): string {
  return t === "UNATTRIBUTED" ? "Unattributed" : t.charAt(0) + t.slice(1).toLowerCase();
}

/** Whole US dollars with thousands separators: "$1,234,567". */
export function usd(amount: number): string {
  return `$${Math.round(amount).toLocaleString("en-US")}`;
}

/** Large counts stay readable: 950 → "950", 12_400 → "12.4k", 3_100_000 → "3.1M". */
export function compact(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1e6) return `${(value / 1e6).toFixed(1)}M`;
  if (abs >= 1e4) return `${(value / 1e3).toFixed(1)}k`;
  return Math.round(value).toLocaleString("en-US");
}

export function integer(value: number): string {
  return Math.round(value).toLocaleString("en-US");
}

/** Headline money: "$2,145", "$354.3M", "$1.90B" — the exact figure goes in a detail line. */
export function usdShort(amount: number): string {
  const abs = Math.abs(amount);
  if (abs >= 1e9) return `$${(amount / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `$${(amount / 1e6).toFixed(1)}M`;
  return usd(amount);
}
