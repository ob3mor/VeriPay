"use client";

import { CircleAlert, Clock, WifiOff } from "lucide-react";

import { ApiError, ApiNetworkError, getApiRoot } from "@/lib/api";
import { cn } from "@/lib/utils";

export interface FormAlertProps extends React.HTMLAttributes<HTMLDivElement> {
  /** The caught value from a mutation — classified honestly below. */
  error: unknown;
  /** Heading for the generic/unclassified case, e.g. "Sign-in failed". */
  fallbackTitle?: string;
}

/**
 * Compact form-error alert for the auth screens (Prompt 05: rate-limit error
 * surfacing). It never invents a cause:
 *
 * - 429 `rate_limited` (docs/API.md §2; the backend throttles login/register
 *   per IP and locks out failed attempts per IP+email, apps/api/app/core/
 *   ratelimit.py) gets its OWN treatment — amber, with the honest instruction
 *   that waiting is the only fix. Retrying immediately cannot succeed.
 * - other `ApiError` renders the envelope's user-safe `message` (API.md §2),
 *   plus the `request_id` so a user can quote it against server logs.
 * - `ApiNetworkError` (fetch itself rejected) renders the offline guidance —
 *   the page never crashes when the backend is down.
 * - anything else gets the fallback title and a generic line.
 *
 * `role="alert"` makes screen readers announce the failure the moment the
 * state flips (implicit aria-live="assertive").
 */
export function FormAlert({ error, fallbackTitle = "Something went wrong", className, ...props }: FormAlertProps) {
  // Rate limiting: code `rate_limited` per the envelope, or a bare 429 from a
  // proxy. Amber, not red — nothing failed, the user must simply wait.
  if (error instanceof ApiError && (error.code === "rate_limited" || error.status === 429)) {
    return (
      <div
        role="alert"
        className={cn("rounded-md border border-warning/50 bg-warning/10 px-3 py-2.5 text-sm", className)}
        {...props}
      >
        <p className="flex items-center gap-2 font-medium text-warning-foreground">
          <Clock className="h-4 w-4 shrink-0" aria-hidden="true" />
          Too many attempts — please wait
        </p>
        <p className="mt-1 leading-relaxed text-warning-foreground/90">{error.message}</p>
        <p className="mt-1 text-xs leading-relaxed text-warning-foreground/70">
          The limit is in place for your protection and lifts on its own shortly. Retrying sooner
          will not go through and can extend the wait.
        </p>
      </div>
    );
  }

  if (error instanceof ApiNetworkError) {
    return (
      <div
        role="alert"
        className={cn("rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2.5 text-sm text-destructive", className)}
        {...props}
      >
        <p className="flex items-center gap-2 font-medium">
          <WifiOff className="h-4 w-4 shrink-0" aria-hidden="true" />
          Can&apos;t reach the VeriPay API
        </p>
        <p className="mt-1 leading-relaxed">
          The API at <span className="font-mono text-xs">{getApiRoot()}</span> did not respond. Start
          the backend and try again — your data was not sent anywhere.
        </p>
      </div>
    );
  }

  if (error instanceof ApiError) {
    return (
      <div
        role="alert"
        className={cn("rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2.5 text-sm text-destructive", className)}
        {...props}
      >
        <p className="flex items-center gap-2 font-medium">
          <CircleAlert className="h-4 w-4 shrink-0" aria-hidden="true" />
          {fallbackTitle}
        </p>
        {/* ApiError.message is the envelope's `message` — safe to display (API.md §2). */}
        <p className="mt-1 leading-relaxed">{error.message}</p>
        {error.requestId && (
          <p className="mt-1 font-mono text-xs text-destructive/70">Request ID: {error.requestId}</p>
        )}
      </div>
    );
  }

  return (
    <div
      role="alert"
      className={cn("rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2.5 text-sm text-destructive", className)}
      {...props}
    >
      <p className="flex items-center gap-2 font-medium">
        <CircleAlert className="h-4 w-4 shrink-0" aria-hidden="true" />
        {fallbackTitle}
      </p>
      <p className="mt-1 leading-relaxed">An unexpected error occurred. Please try again.</p>
    </div>
  );
}
