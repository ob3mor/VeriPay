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
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { HONEST_OUTCOME_LABELS } from "@/lib/status";

/**
 * Landing page — a pure server component. It renders no data, so it is
 * identical with or without a running API (static-export friendly).
 *
 * Copy deliberately mirrors the product's non-negotiable invariants
 * (docs/ARCHITECTURE.md §8): VeriPay never authorizes payments automatically,
 * never claims an invoice is genuine, and treats uncertain or missing evidence
 * as exactly that — never as confident fraud. The mock review card uses the
 * same honest badge components as the real screens (src/components/…).
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
 * The invariant strip copy — one line per normative rule from
 * docs/ARCHITECTURE.md §2/§8 (R1–R4), phrased for a landing page. R5/R6 are
 * covered by the third principle card and the review-queue mock.
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
      <header className="border-b bg-card">
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

      <main className="mx-auto w-full max-w-6xl flex-1 px-4 sm:px-6">
        <section className="grid items-center gap-12 bg-gradient-to-b from-primary/[0.04] to-transparent py-16 lg:grid-cols-2 lg:py-24">
          <div>
            <span className="inline-flex items-center gap-2 rounded-full border bg-card px-3 py-1 text-xs font-medium text-muted-foreground">
              <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-accent" />
              Decision support · human-in-the-loop
            </span>
            <h1 className="mt-6 text-4xl font-bold tracking-tight sm:text-5xl">
              Catch payment fraud before{" "}
              <span className="relative inline-block">
                the money moves.
                {/* Owner-palette teal accent — a decorative underline, never
                    colored text (teal-on-white fails contrast for copy). */}
                <span
                  aria-hidden="true"
                  className="absolute inset-x-0 -bottom-1.5 h-1.5 rounded-full bg-accent/70"
                />
              </span>
            </h1>
            <p className="mt-5 max-w-xl text-lg text-muted-foreground">
              VeriPay cross-checks every invoice against your vendors, purchase orders and trusted
              bank accounts, and routes what it cannot prove to the humans who decide. It never
              approves a payment on its own — and it never declares an invoice &ldquo;genuine&rdquo;.
            </p>
            <div className="mt-8 flex flex-wrap items-center gap-3">
              <Link href="/register" className={buttonVariants({ size: "lg" })}>
                Create your workspace <ArrowRight />
              </Link>
              <Link href="/login" className={buttonVariants({ variant: "outline", size: "lg" })}>
                Sign in
              </Link>
            </div>
            <p className="mt-4 text-sm text-muted-foreground">
              Registering creates a new organization and its first owner account.
            </p>
          </div>

          {/* Product-shaped mock of a review queue — the same honest badges the
              real screens use: severity chips + the outcome vocabulary from
              src/lib/status.ts. Nothing here says "approved" or "genuine". */}
          <Card className="lg:ml-auto lg:w-full lg:max-w-lg">
            <CardHeader>
              <div className="flex items-center justify-between gap-4">
                <CardTitle className="text-base">Invoice INV-2041</CardTitle>
                <StatusBadge
                  presentation={{ label: HONEST_OUTCOME_LABELS.manualReviewRequired, tone: "warning" }}
                />
              </div>
              <p className="text-sm text-muted-foreground">
                3 signals raised · final disposition is a human decision
              </p>
            </CardHeader>
            <CardContent className="space-y-3">
              {SIGNALS.map((signal) => (
                <div key={signal.title} className="rounded-md border p-3">
                  <div className="flex items-center justify-between gap-3">
                    <span className="flex items-center gap-2 text-sm font-medium">
                      <signal.icon className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
                      {signal.title}
                    </span>
                    <SeverityBadge severity={signal.severity} />
                  </div>
                  <p className="mt-2 text-sm text-muted-foreground">{signal.body}</p>
                </div>
              ))}
            </CardContent>
            <CardFooter className="justify-between text-sm">
              <span className="text-muted-foreground">Human decision required</span>
              <Link href="/dashboard" className={buttonVariants({ variant: "ghost", size: "sm" })}>
                Open the dashboard <ArrowRight />
              </Link>
            </CardFooter>
          </Card>
        </section>

        {/* Invariant band — the owner's navy, restating the normative rules
            (docs/ARCHITECTURE.md §2/§8) as product promises. */}
        <section
          aria-label="VeriPay's non-negotiable rules"
          className="mb-16 rounded-xl bg-primary px-6 py-8 text-primary-foreground sm:px-10"
        >
          <h2 className="text-sm font-semibold uppercase tracking-wide text-primary-foreground/70">
            Non-negotiable, by design
          </h2>
          <ul className="mt-4 grid gap-x-8 gap-y-4 sm:grid-cols-2 lg:grid-cols-4">
            {INVARIANTS.map((invariant) => (
              <li key={invariant.rule} className="flex items-start gap-3">
                <span
                  aria-hidden="true"
                  className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary-foreground/10"
                >
                  <invariant.icon className="h-4 w-4" />
                </span>
                <p className="text-sm leading-relaxed">
                  <span className="mr-1.5 font-mono text-xs text-primary-foreground/60">
                    {invariant.rule}
                  </span>
                  {invariant.text}
                </p>
              </li>
            ))}
          </ul>
        </section>

        <section className="pb-20">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Built on non-negotiables
          </h2>
          <div className="mt-4 grid gap-4 md:grid-cols-3">
            {PRINCIPLES.map((principle) => (
              <Card key={principle.title}>
                <CardHeader className="pb-3">
                  <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
                    <principle.icon className="h-5 w-5 text-primary" aria-hidden="true" />
                  </span>
                  <CardTitle className="text-base">{principle.title}</CardTitle>
                </CardHeader>
                <CardContent className="text-sm text-muted-foreground">{principle.body}</CardContent>
              </Card>
            ))}
          </div>
        </section>
      </main>

      <footer className="border-t bg-card">
        <div className="mx-auto flex w-full max-w-6xl flex-col items-start justify-between gap-4 px-4 py-6 text-sm text-muted-foreground sm:flex-row sm:items-center sm:px-6">
          <div className="flex flex-col items-start gap-2 sm:flex-row sm:items-center sm:gap-4">
            <AppLogo size="sm" />
            <p>© 2026 VeriPay — invoice &amp; payment fraud prevention for finance &amp; procurement teams.</p>
          </div>
          <div className="flex items-center gap-4">
            <Link href="/login" className="hover:text-foreground">
              Sign in
            </Link>
            <Link href="/register" className="hover:text-foreground">
              Create account
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
