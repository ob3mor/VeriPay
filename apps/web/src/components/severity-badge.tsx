import { cn } from "@/lib/utils";

import type { Severity } from "@veripay/api-contracts";

/**
 * Risk-severity badge for finding/assessment/case severities
 * (core.enums.Severity). This is the *gradation* component — it says how
 * severe a signal is, which is factual; verdict language stays out
 * (docs/ARCHITECTURE.md §8.2). Pair it with StatusBadge for the honest
 * outcome label.
 *
 * Tones (severity → weight):
 *   low      → neutral outline
 *   medium   → warning
 *   high     → danger
 *   critical → danger, solid fill (the strongest visual treatment)
 */
const SEVERITY_PRESENTATION: Record<Severity, { label: string; className: string }> = {
  low: {
    label: "Low",
    className: "bg-muted text-muted-foreground border-border",
  },
  medium: {
    label: "Medium",
    className: "bg-warning/15 text-warning-foreground border-warning/40",
  },
  high: {
    label: "High",
    className: "bg-destructive/10 text-destructive border-destructive/30",
  },
  critical: {
    label: "Critical",
    className: "bg-destructive text-destructive-foreground border-destructive",
  },
};

export interface SeverityBadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  severity: Severity | string;
  /** Render `none` (assessments with no findings) as a quiet neutral chip. */
  noneLabel?: string;
}

export function SeverityBadge({ severity, noneLabel = "None", className, ...props }: SeverityBadgeProps) {
  // `none` is a RiskLevel, not a Severity — assessments with risk "none"
  // still reach this component via the risk_level prop; render it quiet.
  if (severity === "none") {
    return (
      <span
        className={cn(
          "inline-flex items-center whitespace-nowrap rounded-full border bg-muted/60 px-2.5 py-0.5 text-xs font-medium text-muted-foreground",
          className
        )}
        {...props}
      >
        {noneLabel}
      </span>
    );
  }

  const presentation = SEVERITY_PRESENTATION[severity as Severity];
  // Unknown severity values render as-is in a neutral chip — never guessed.
  if (!presentation) {
    return (
      <span
        className={cn(
          "inline-flex items-center whitespace-nowrap rounded-full border bg-muted px-2.5 py-0.5 text-xs font-medium text-foreground",
          className
        )}
        {...props}
      >
        {severity}
      </span>
    );
  }

  return (
    <span
      className={cn(
        "inline-flex items-center whitespace-nowrap rounded-full border px-2.5 py-0.5 text-xs font-medium",
        presentation.className,
        className
      )}
      {...props}
    >
      {presentation.label}
    </span>
  );
}
