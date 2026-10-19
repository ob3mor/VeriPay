import { cn } from "@/lib/utils";

import type { Severity } from "@veripay/api-contracts";

/**
 * Risk-severity badge for finding/assessment/case severities
 * (core.enums.Severity). This is the *gradation* component — it says how
 * severe a signal is, which is factual; verdict language stays out
 * (docs/ARCHITECTURE.md §8.2). Pair it with StatusBadge for the honest
 * outcome label.
 *
 * The judgment ladder (one system across the whole product — the four tones
 * are the only severity colors anywhere):
 *   low      → quiet neutral chip (slate)
 *   medium   → amber chip
 *   high     → red chip
 *   critical → solid red plate with navy ink (the strongest treatment)
 */
const SEVERITY_PRESENTATION: Record<Severity, { label: string; className: string }> = {
  low: {
    label: "Low",
    className: "bg-secondary/80 text-secondary-foreground border-border",
  },
  medium: {
    label: "Medium",
    className: "bg-warning/15 text-warning border-warning/40",
  },
  high: {
    label: "High",
    className: "bg-destructive/15 text-destructive border-destructive/40",
  },
  critical: {
    label: "Critical",
    className: "bg-destructive text-destructive-foreground border-destructive shadow-[0_1px_2px_hsl(214_56%_4%/0.5)]",
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
          "inline-flex items-center whitespace-nowrap rounded-sm border bg-muted/60 px-2 py-0.5 text-xs font-medium text-muted-foreground",
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
          "inline-flex items-center whitespace-nowrap rounded-sm border bg-secondary/80 px-2 py-0.5 text-xs font-medium text-secondary-foreground",
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
        "inline-flex items-center whitespace-nowrap rounded-sm border px-2 py-0.5 text-xs font-medium tracking-wide",
        presentation.className,
        className
      )}
      {...props}
    >
      {presentation.label}
    </span>
  );
}
