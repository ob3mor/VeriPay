import { cn } from "@/lib/utils";

export interface PageHeaderProps extends React.HTMLAttributes<HTMLDivElement> {
  title: string;
  description?: string;
  /** Right-aligned action slot — buttons, buttonVariants links, etc. */
  actions?: React.ReactNode;
}

/**
 * Consistent page header for dashboard screens: title, optional description,
 * optional right-hand actions. Rendered as a <header> landmark so screen
 * readers can jump to it.
 */
export function PageHeader({ title, description, actions, className, ...props }: PageHeaderProps) {
  return (
    <header className={cn("flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between", className)} {...props}>
      <div className="min-w-0">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}
