"use client";

import { ApiError, ApiNetworkError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export interface ErrorStateProps extends React.HTMLAttributes<HTMLDivElement> {
  /** The thrown value from a query/mutation — classified honestly below. */
  error: unknown;
  /** Heading override; the default names the failure class, not a guess. */
  title?: string;
  /** Show a retry button (call the query's refetch / repeat the action). */
  onRetry?: () => void;
  retryLabel?: string;
}

/**
 * Error-state panel. It never invents a cause: the message shown is the
 * API's user-safe envelope message (docs/API.md §2) when present, the
 * network-failure sentence when fetch itself rejected, or a generic
 * unexpected-error line otherwise. The `request_id` from the envelope is
 * surfaced so a user can quote it against server logs.
 */
export function ErrorState({
  error,
  title,
  onRetry,
  retryLabel = "Try again",
  className,
  ...props
}: ErrorStateProps) {
  let heading = title ?? "Something went wrong";
  let body = "An unexpected error occurred. Please try again.";
  let requestId: string | undefined;

  if (error instanceof ApiNetworkError) {
    heading = title ?? "Could not reach the VeriPay API";
    body =
      "The API did not respond. Check that the backend is running and try again — nothing was changed by this request.";
  } else if (error instanceof ApiError) {
    heading = title ?? "Request failed";
    // ApiError.message is the envelope's `message` — safe to display (API.md §2).
    body = error.message;
    if (error.requestId) requestId = error.requestId;
    if (error.details?.length) {
      const detailText = error.details
        .map((detail) => (detail.field ? `${detail.field}: ${detail.message}` : detail.message))
        .join(" · ");
      if (detailText) body = `${body} (${detailText})`;
    }
  }

  return (
    <div
      role="alert"
      className={cn("rounded-lg border border-destructive/30 bg-destructive/5 px-6 py-8", className)}
      {...props}
    >
      <div className="flex flex-col items-start gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-destructive">{heading}</p>
          <p className="mt-1 max-w-xl break-words text-sm text-foreground/80">{body}</p>
          {requestId && (
            <p className="mt-1 font-mono text-xs text-muted-foreground">Request ID: {requestId}</p>
          )}
        </div>
        {onRetry && (
          <Button variant="outline" size="sm" onClick={onRetry} className="shrink-0">
            {retryLabel}
          </Button>
        )}
      </div>
    </div>
  );
}
