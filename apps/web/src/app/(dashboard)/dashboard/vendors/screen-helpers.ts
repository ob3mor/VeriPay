/** Small helpers shared by the vendor screens (kept inside this folder —
 *  no shared-file conflicts with other builders' work). */
import { ApiError } from "@/lib/api";

/** User-safe message from a failed mutation: the envelope `message` when the
 *  API answered (docs/API.md §2 — safe to display), the caller's fallback
 *  otherwise. Never a raw error string. */
export function mutationMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    return error.message || fallback;
  }
  return fallback;
}

/** Field-level error text from a 422 envelope, if the API named the field. */
export function fieldError(error: unknown, field: string): string | null {
  if (!(error instanceof ApiError)) return null;
  const match = (error.details ?? []).find((detail) => detail.field === field);
  return match?.message ?? null;
}

/** Show a full YYYY-MM-DD (ISO strings on the wire; rendered client-side
 *  only, so there is no hydration concern). */
export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toISOString().slice(0, 10);
}
