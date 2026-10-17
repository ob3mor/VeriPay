/**
 * Presentation-only formatters for the invoices list.
 *
 * Honesty rules: an unknown currency or a missing value renders as a
 * placeholder ("—"), never as a guessed number; amounts are Decimal strings
 * from the API (Numeric(14,2) — docs/DATABASE.md §1) and stay decimal here.
 */

export function formatAmount(totalAmount: string | null, currency: string | null): string {
  if (totalAmount === null || totalAmount === "") return "—";
  let formatted = totalAmount;
  try {
    // Decimal string → Number is safe for display at invoice scale
    // (≤ 10^14 by the column type); the API keeps full precision.
    formatted = new Intl.NumberFormat("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(Number(totalAmount));
  } catch {
    formatted = totalAmount; // never fabricate a number
  }
  return currency ? `${currency} ${formatted}` : formatted;
}

/** `invoice_date` is an ISO date string (date only) — format without timezone shifts. */
export function formatDate(isoDate: string | null): string {
  if (!isoDate) return "—";
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(isoDate);
  if (!match) return isoDate; // unknown format: show as-is, don't guess
  const [, year, month, day] = match;
  return `${year}-${month}-${day}`;
}

export { formatBytes } from "@/components/upload/upload-client";
