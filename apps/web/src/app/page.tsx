import Link from "next/link";
import {
  ArrowRight,
  Eye,
  FileSearch,
  Landmark,
  ScanSearch,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";

import { AppLogo } from "@/components/app-logo";
import { SeverityBadge } from "@/components/severity-badge";
import { StatusBadge } from "@/components/status-badge";
import { buttonVariants } from "@/components/ui/button";
import { HONEST_OUTCOME_LABELS } from "@/lib/status";
import { cn } from "@/lib/utils";

/**
 * Landing page — a pure server component. It renders no data, so it is
 * identical with or without a running API (static-export friendly).
 *
 * The Persuade surface of the "examiner's bench" world: a deep navy plate
 * under a faint ledger grid, the hero claim set in the display serif, and the
 * product's own honest components (severity chips + the outcome vocabulary
 * from src/lib/status.ts) arranged as the dossier plate a visitor would meet
 * inside the product. Copy deliberately mirrors the product's non-negotiable
 * invariants (docs/ARCHITECTURE.md §8): VeriPay never authorizes payments
 * automatically, never claims an invoice is genuine, and treats uncertain or
 * missing evidence as exactly that — never as confident fraud.
 */

const PRINCIPLES = [
  {
    icon: ShieldCheck,
    title: "Human review is mandatory",
    body: "Critical inconsistencies always route to a person. VeriPay never authorizes a payment on its own — the decision stays with your team.",
  },
  {
    icon: FileSearch,
    title: "Evidence, not verdicts",
    body: "Missing records are not proof of fraud, and uncertain OCR output is labeled uncertain. VeriPay surfaces evidence; it never renders confident accusations from guesses.",
  },
  {
    icon: Landmark,
    title: "New account? Verify independently.",
    body: "A changed bank account is a red flag, not a green light. New pay-to accounts require independent, human verification before they can be trusted.",
  },
] as const;

/**
 * The charter — one line per normative rule from docs/ARCHITECTURE.md §2/§8
 * (R1–R4), phrased for a landing page. R5/R6 are covered by the third
 * principle and the review-queue plate.
 */
const INVARIANTS = [
  { icon: ShieldCheck, rule: "R1", text: "Never authorizes a payment" },
  { icon: Eye, rule: "R2", text: "Never declares an invoice genuine" },
  { icon: ScanSearch, rule: "R3", text: "Uncertain OCR stays uncertain" },
  { icon: TriangleAlert, rule: "R4", text: "Missing records ≠ fraud" },
] as const;

const SIGNALS = [
  {
    icon: TriangleAlert,
    title: "Bank account changed",
    severity: "high" as const,
    body: "The remittance account on INV-2041 does not match any verified trusted account for this vendor.",
  },
  {
    icon: TriangleAlert,
    title: "No matching purchase order",
    severity: "medium" as const,
    body: "No PO found for this invoice. A missing record is not proof of fraud — it is flagged for human review.",
  },
  {
    icon: FileSearch,
    title: "Low OCR confidence",
    severity: "low" as const,
    body: "The extracted total is uncertain. Uncertain extractions never become confident fraud evidence.",
  },
] as const;

export default function LandingPage() {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-border/70 bg-background/85 backdrop-blur-sm">
        <div className="mx-auto flex h-16 w-full max-w-6xl items-center justify-between px-4 sm:px-6">
          <AppLogo size="md" />
          <nav className="flex items-center gap-2">
            <Link href="/login" className={buttonVariants({ variant: "ghost", size: "sm" })}>
              Sign in
            </Link>
            <Link href="/register" className={buttonVariants({ size: "sm" })}>
              Create account
            </Link>
          </nav>
        </div>
      </header>

      <main className="flex-1">
        {/* ------------------------------------------------------------- hero */}
        <section className="relative overflow-hidden border-b border-border/70">
          {/* The bench: a cyan instrument light from the plate's corner — the
              product is already looking at this page. */}
          <div aria-hidden="true" className="absolute inset-0 bg-[radial-gradient(52%_60%_at_78%_-10%,hsl(192_76%_52%/0.09),transparent_70%)]" />

          <div className="relative mx-auto grid w-full max-w-6xl items-center gap-14 px-4 py-20 sm:px-6 lg:grid-cols-[1.05fr_0.95fr] lg:gap-16 lg:py-28">
            <div>
              <h1 className="font-display text-4xl font-semibold leading-[1.14] tracking-tight sm:text-[2.75rem]">
                Catch payment fraud before{" "}
                <span className="relative inline-block">
                  the money moves.
                  {/* The signature stroke — a single cyan rule under the
                      phrase that matters, like an examiner's mark. */}
                  <span
                    aria-hidden="true"
                    className="absolute inset-x-0 -bottom-2 h-[3px] rounded-full bg-primary/80"
                  />
                </span>
              </h1>
              <p className="mt-7 max-w-xl text-lg leading-relaxed text-muted-foreground">
                VeriPay cross-checks every invoice against your vendors, purchase orders and
                trusted bank accounts, and routes what it cannot prove to the humans who decide.
                It never approves a payment on its own — and it never declares an invoice
                &ldquo;genuine&rdquo;.
              </p>
              <div className="mt-9 flex flex-wrap items-center gap-3">
                <Link href="/register" className={buttonVariants({ size: "lg" })}>
                  Create your workspace <ArrowRight />
                </Link>
                <Link href="/login" className={buttonVariants({ variant: "outline", size: "lg" })}>
                  Sign in
                </Link>
              </div>
              <p className="mt-5 text-sm leading-relaxed text-muted-foreground">
                Decision support, human-in-the-loop. Registering creates a new organization and
                its first owner account.
              </p>
            </div>

            {/* The dossier plate — the same honest badges the real screens
                use: severity chips + the outcome vocabulary from
                src/lib/status.ts. Nothing here says "approved" or "genuine".
                The scan-line sweep is the one authored motion moment. */}
            <div className="relative">
              <div className="relative overflow-hidden rounded-lg border bg-card shadow-plate">
                <span aria-hidden="true" className="animate-scanline pointer-events-none absolute inset-0">
                  <span className="absolute inset-x-0 top-0 h-16 -translate-y-full bg-gradient-to-b from-transparent to-primary/[0.07]" />
                  <span className="absolute inset-x-0 top-0 h-px bg-primary/50 shadow-[0_0_14px_1px_hsl(192_76%_52%/0.35)]" />
                </span>

                <div className="flex items-center justify-between gap-4 border-b border-border/70 bg-panel/60 px-6 py-4">
                  <p className="font-mono text-sm text-foreground/90">Invoice INV-2041</p>
                  <StatusBadge
                    presentation={{ label: HONEST_OUTCOME_LABELS.manualReviewRequired, tone: "warning" }}
                  />
                </div>

                <ul className="divide-y divide-border/60">
                  {SIGNALS.map((signal) => (
                    <li key={signal.title} className="px-6 py-4">
                      <div className="flex items-center justify-between gap-3">
                        <span className="flex items-center gap-2.5 text-sm font-medium">
                          <signal.icon
                            className="h-4 w-4 shrink-0 text-muted-foreground"
                            aria-hidden="true"
                          />
                          {signal.title}
                        </span>
                        <SeverityBadge severity={signal.severity} />
                      </div>
                      <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
                        {signal.body}
                      </p>
                    </li>
                  ))}
                </ul>

                <div className="flex items-center justify-between gap-4 border-t border-border/70 bg-panel/60 px-6 py-4">
                  <span className="text-sm text-muted-foreground">Human decision required</span>
                  <Link
                    href="/dashboard"
                    className={cn(
                      "inline-flex items-center gap-1.5 text-sm font-medium text-primary transition-colors hover:text-accent",
                      "rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-card"
                    )}
                  >
                    Open the dashboard <ArrowRight className="h-4 w-4" />
                  </Link>
                </div>
              </div>
            </div>
          </div>
        </section>

        <div className="mx-auto w-full max-w-6xl px-4 sm:px-6">
          {/* --------------------------------------------------- the charter */}
          <section aria-label="VeriPay's non-negotiable rules" className="py-20">
            <div className="rounded-lg border bg-card shadow-plate">
              <div className="border-b border-border/70 px-6 py-5 sm:px-8">
                <h2 className="font-display text-xl font-semibold tracking-tight sm:text-2xl">
                  Non-negotiable, by design
                </h2>
              </div>
              <ul className="grid gap-x-8 gap-y-5 px-6 py-6 sm:grid-cols-2 sm:px-8 lg:grid-cols-4">
                {INVARIANTS.map((invariant) => (
                  <li key={invariant.rule} className="flex items-start gap-3">
                    <span
                      aria-hidden="true"
                      className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-border bg-secondary/70"
                    >
                      <invariant.icon className="h-4 w-4 text-primary" />
                    </span>
                    <p className="text-sm leading-relaxed text-muted-foreground">
                      <span className="mr-1.5 font-mono text-xs text-primary">{invariant.rule}</span>
                      {invariant.text}
                    </p>
                  </li>
                ))}
              </ul>
            </div>
          </section>

          {/* ------------------------------------- principles — ruled columns */}
          <section className="pb-24">
            <h2 className="font-display text-xl font-semibold tracking-tight sm:text-2xl">
              Built on non-negotiables
            </h2>
            <div className="mt-2 grid gap-y-10 md:grid-cols-3 md:divide-x md:divide-border/70">
              {PRINCIPLES.map((principle) => (
                <div key={principle.title} className="pt-6 md:px-8 md:first:pl-0 md:last:pr-0">
                  <span className="flex h-9 w-9 items-center justify-center rounded-md border border-primary/25 bg-primary/10">
                    <principle.icon className="h-5 w-5 text-primary" aria-hidden="true" />
                  </span>
                  <h3 className="mt-4 font-display text-lg font-semibold leading-snug">
                    {principle.title}
                  </h3>
                  <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                    {principle.body}
                  </p>
                </div>
              ))}
            </div>
          </section>
        </div>
      </main>

      <footer className="border-t border-border/70 bg-panel/60">
        <div className="mx-auto flex w-full max-w-6xl flex-col items-start justify-between gap-4 px-4 py-6 text-sm text-muted-foreground sm:flex-row sm:items-center sm:px-6">
          <div className="flex flex-col items-start gap-3 sm:flex-row sm:items-center sm:gap-5">
            <AppLogo size="sm" />
            <p>© 2026 VeriPay — invoice &amp; payment fraud prevention for finance &amp; procurement teams.</p>
          </div>
          <div className="flex items-center gap-5">
            <Link
              href="/login"
              className="rounded-sm transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              Sign in
            </Link>
            <Link
              href="/register"
              className="rounded-sm transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              Create account
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
