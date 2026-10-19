import { cn } from "@/lib/utils";
import type { BadgeTone, StatusPresentation } from "@/lib/status";

/**
 * Tone → class registry for every status badge in the design system. Tones
 * come from src/lib/status.ts; the palette lives behind the CSS variables
 * (globals.css), so badges stay theme-consistent.
 *
 * One system: info is the brand cyan (the instrument light reporting),
 * success/warning/danger are the judgment colors, neutral/muted are slate.
 * Text always uses the bright color token on a low-alpha tint of the same
 * hue — ≥ 4.5:1 against the plate on every tone.
 *
 * Accessible by construction: color is never the only carrier of meaning —
 * every badge renders its full text label. Decorative dot plus text.
 */
const TONE_CLASSES: Record<BadgeTone, string> = {
  neutral: "bg-secondary/70 text-secondary-foreground border-border",
  info: "bg-primary/15 text-primary border-primary/30",
  success: "bg-success/15 text-success border-success/30",
  warning: "bg-warning/15 text-warning border-warning/40",
  danger: "bg-destructive/15 text-destructive border-destructive/40",
  muted: "bg-muted/60 text-muted-foreground border-border/70",
};

/** Dot color per tone — a redundant visual cue on top of the label text. */
const TONE_DOT_CLASSES: Record<BadgeTone, string> = {
  neutral: "bg-slate-400",
  info: "bg-primary",
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-destructive",
  muted: "bg-slate-500",
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
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-sm border px-2 py-0.5 text-xs font-medium tracking-wide",
        TONE_CLASSES[tone],
        className
      )}
      {...props}
    >
      {!hideDot && <span aria-hidden="true" className={cn("h-1.5 w-1.5 shrink-0 rounded-full", TONE_DOT_CLASSES[tone])} />}
      {label}
    </span>
  );
}
