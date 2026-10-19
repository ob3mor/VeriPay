import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

export interface EmptyStateProps extends React.HTMLAttributes<HTMLDivElement> {
  icon?: LucideIcon;
  title: string;
  description?: string;
  /** Optional call to action — usually a Button or buttonVariants link. */
  action?: React.ReactNode;
}

/**
 * Empty-state panel for lists/tables with no rows yet. The motif is a fine
 * "empty dossier" plate — a dashed scan frame around a quiet document glyph —
 * so an empty queue reads as a prepared instrument waiting for work, not a
 * broken page. Title set in the display serif.
 *
 * Purely informational: it makes no claims about the data and never suggests
 * the system approved, verified, or cleared anything.
 *
 * Accessibility: rendered as a plain region with an accessible name from the
 * title (screen readers announce it as "empty state" region content).
 */
export function EmptyState({ icon: Icon, title, description, action, className, ...props }: EmptyStateProps) {
  return (
    <div
      role="status"
      aria-label={title}
      className={cn(
        "flex flex-col items-center justify-center rounded-lg border border-border/70 bg-card/50 px-6 py-16 text-center",
        className
      )}
      {...props}
    >
      <span
        aria-hidden="true"
        className="relative mb-5 flex h-16 w-14 items-center justify-center"
      >
        {/* The empty-dossier motif: a dashed scan frame over a document plate. */}
        <span className="absolute inset-0 rounded-sm border border-dashed border-border" />
        <span className="absolute inset-x-0 bottom-0 h-[3px] rounded-b-sm bg-primary/70" />
        <span className="flex h-11 w-9 items-center justify-center rounded-[3px] border border-border bg-secondary/60 shadow-raise">
          {Icon ? (
            <Icon className="h-5 w-5 text-muted-foreground" />
          ) : (
            <span className="block h-3.5 w-3.5 rounded-[2px] border border-muted-foreground/40" />
          )}
        </span>
      </span>
      <p className="font-display text-lg font-semibold text-foreground">{title}</p>
      {description && (
        <p className="mt-2 max-w-md text-sm leading-relaxed text-muted-foreground">{description}</p>
      )}
      {action && <div className="mt-6">{action}</div>}
    </div>
  );
}
