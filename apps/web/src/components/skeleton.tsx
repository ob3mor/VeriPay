import { cn } from "@/lib/utils";

/**
 * Loading skeleton — a shimmering placeholder block for content that has not
 * arrived yet. The bare primitive is visual-only (aria-hidden); use
 * <SkeletonList> (or set label) when a skeleton stands alone so screen
 * readers get one polite "Loading" announcement.
 */
export interface SkeletonProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Render as an accessible "Loading" status region. Default false — the
   *  composed skeletons own the announcement to avoid duplicates. */
  label?: boolean;
}

export function Skeleton({ label = false, className, ...props }: SkeletonProps) {
  return (
    <div
      aria-hidden={!label ? true : undefined}
      role={label ? "status" : undefined}
      aria-label={label ? "Loading" : undefined}
      className={cn("animate-pulse rounded-md bg-muted", className)}
      {...props}
    />
  );
}

/** One skeleton row matching the list/table rows used across screens. */
export function SkeletonRow({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("flex items-center justify-between gap-4 border-b border-border/60 py-3", className)} {...props}>
      <div className="flex min-w-0 items-center gap-3">
        <Skeleton className="h-9 w-9 rounded-full" />
        <Skeleton className="h-4 w-40" />
      </div>
      <Skeleton className="h-5 w-24 rounded-full" />
    </div>
  );
}

/** Skeleton for a list of rows (cards/tables) — e.g. while a list query loads. */
export function SkeletonList({ rows = 5, labeled = true }: { rows?: number; labeled?: boolean }) {
  return (
    <div role={labeled ? "status" : undefined} aria-label={labeled ? "Loading" : undefined}>
      {Array.from({ length: rows }, (_, index) => (
        <SkeletonRow key={index} />
      ))}
    </div>
  );
}
