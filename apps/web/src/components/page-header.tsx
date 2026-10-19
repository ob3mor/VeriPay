import { cn } from "@/lib/utils";

export interface PageHeaderProps extends React.HTMLAttributes<HTMLDivElement> {
  title: string;
  description?: string;
  /** Right-aligned action slot — buttons, buttonVariants links, etc. */
  actions?: React.ReactNode;
}

/**
 * Consistent page header for dashboard screens: title set in the display
 * serif (the charter voice), optional description, optional right-hand
 * actions, closed by a hairline that starts the page's rhythm. Rendered as a
 * <header> landmark so screen readers can jump to it.
 */
export function PageHeader({ title, description, actions, className, ...props }: PageHeaderProps) {
  return (
    <header
      className={cn(
        "flex flex-col gap-4 border-b border-border/70 pb-6 sm:flex-row sm:items-start sm:justify-between",
        className
      )}
      {...props}
    >
      <div className="min-w-0">
        <h1 className="font-display text-2xl font-semibold tracking-tight text-foreground sm:text-[1.75rem]">
          {title}
        </h1>
        {description && <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}
