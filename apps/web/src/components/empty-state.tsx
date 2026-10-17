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
 * Empty-state panel for lists/tables with no rows yet. Purely informational:
 * it makes no claims about the data and never suggests the system approved,
 * verified, or cleared anything.
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
        "flex flex-col items-center justify-center rounded-lg border border-dashed bg-card px-6 py-14 text-center",
        className
      )}
      {...props}
    >
      {Icon && (
        <span
          aria-hidden="true"
          className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-muted"
        >
          <Icon className="h-6 w-6 text-muted-foreground" />
        </span>
      )}
      <p className="text-sm font-semibold text-foreground">{title}</p>
      {description && <p className="mt-1.5 max-w-sm text-sm text-muted-foreground">{description}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}
