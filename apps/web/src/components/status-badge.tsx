import { cn } from "@/lib/utils";
import type { BadgeTone, StatusPresentation } from "@/lib/status";

/**
 * Tone → class registry for every badge in the design system. Tones come
 * from src/lib/status.ts; the raw owner palette is behind the CSS variables
 * (globals.css), so badges stay theme-consistent.
 *
 * Accessible by construction: color is never the only carrier of meaning —
 * every badge renders its full text label. Decorative dot plus text.
 */
const TONE_CLASSES: Record<BadgeTone, string> = {
  neutral: "bg-muted text-foreground border-border",
  info: "bg-primary/10 text-primary border-primary/20",
  success: "bg-success/10 text-success-foreground border-success/30",
  warning: "bg-warning/15 text-warning-foreground border-warning/40",
  danger: "bg-destructive/10 text-destructive border-destructive/30",
  muted: "bg-muted text-muted-foreground border-border",
};

/** Dot color per tone — a redundant visual cue on top of the label text. */
const TONE_DOT_CLASSES: Record<BadgeTone, string> = {
  neutral: "bg-slate-400",
  info: "bg-primary",
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-destructive",
  muted: "bg-slate-400",
};

export interface StatusBadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  /** The presentation (label + tone) from a mapping in src/lib/status.ts. */
  presentation: StatusPresentation;
  /** Hide the leading dot (e.g. in dense tables). */
  hideDot?: boolean;
}

/**
 * The honest status badge. It renders ONLY labels supplied by the mappings in
 * src/lib/status.ts — the honest vocabulary ("No material discrepancies",
 * "Manual review required", "High-risk discrepancy", "Processing failed") and
 * neutral factual workflow labels. There is deliberately no variant that
 * could render "Payment Approved" or "Genuine" (docs/ARCHITECTURE.md §8.1–8.2).
 */
export function StatusBadge({ presentation, hideDot = false, className, ...props }: StatusBadgeProps) {
  const { label, tone } = presentation;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-xs font-medium",
        TONE_CLASSES[tone],
        className
      )}
      {...props}
    >
      {!hideDot && <span aria-hidden="true" className={cn("h-1.5 w-1.5 rounded-full", TONE_DOT_CLASSES[tone])} />}
      {label}
    </span>
  );
}
