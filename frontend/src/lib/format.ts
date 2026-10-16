const usd = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const ratio = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 4 });

/**
 * Accounting style: negatives in parentheses. Non-numbers pass through.
 * Return lines are whole dollars, except ratios (e.g. the 540NR deduction percentage 0.6347 or a tax
 * rate 0.0766). A fractional number below 1 is never a whole-dollar amount, so it keeps its precision
 * instead of rounding to 0 or 1.
 */
export function money(v: unknown, opts: { sign?: boolean } = {}): string {
  if (typeof v !== "number" || Number.isNaN(v)) return v == null ? "—" : String(v);
  const isRatio = !Number.isInteger(v) && Math.abs(v) < 1;
  const s = (isRatio ? ratio : usd).format(Math.abs(v));
  if (v < 0) return `(${s})`;
  return opts.sign && v > 0 ? `+${s}` : s;
}

export function pct(v: number | null | undefined): string {
  if (v == null) return "new";
  return `${v > 0 ? "+" : ""}${v.toFixed(1)}%`;
}

export function date(v: string | null | undefined): string {
  if (!v) return "—";
  const d = new Date(v.length === 10 ? `${v}T00:00:00Z` : v);
  return d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" });
}

export function dateTime(v: string | null | undefined): string {
  if (!v) return "—";
  return new Date(v).toLocaleString("en-US", {
    year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "UTC",
  }) + " UTC";
}

export const humanize = (s: string) => s.replace(/_/g, " ").replace(/\b\w/, (c) => c.toUpperCase());
