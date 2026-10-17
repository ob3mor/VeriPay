import Link from "next/link";
import { ArrowRight, FileSearch, Landmark, ShieldCheck, TriangleAlert } from "lucide-react";

import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";

/**
 * Landing page — a pure server component. It renders no data, so it is
 * identical with or without a running API (static-export friendly).
 *
 * Copy deliberately mirrors the product's non-negotiable invariants
 * (docs/ARCHITECTURE.md §8): VeriPay never authorizes payments automatically,
 * never claims an invoice is genuine, and treats uncertain or missing evidence
 * as exactly that — never as confident fraud.
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

const SIGNALS = [
  {
    icon: TriangleAlert,
    title: "Bank account changed",
    tone: "High severity",
    toneClass: "bg-destructive/10 text-destructive",
    body: "The remittance account on INV-2041 does not match any verified trusted account for this vendor.",
  },
  {
    icon: TriangleAlert,
    title: "No matching purchase order",
    tone: "Missing evidence",
    toneClass: "bg-muted text-muted-foreground",
    body: "No PO found for this invoice. A missing record is not proof of fraud — it is flagged for human review.",
  },
  {
    icon: FileSearch,
    title: "Low OCR confidence",
    tone: "Uncertain",
    toneClass: "bg-muted text-muted-foreground",
    body: "The extracted total is uncertain. Uncertain extractions never become confident fraud evidence.",
  },
] as const;

export default function LandingPage() {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b">
        <div className="mx-auto flex h-16 w-full max-w-6xl items-center justify-between px-4 sm:px-6">
          <div className="flex items-center gap-2.5">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <ShieldCheck className="h-5 w-5" />
            </span>
            <span className="text-lg font-semibold tracking-tight">VeriPay</span>
          </div>
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
        <section className="grid items-center gap-12 py-16 lg:grid-cols-2 lg:py-24">
          <div>
            <span className="inline-flex items-center rounded-full border px-3 py-1 text-xs font-medium text-muted-foreground">
              Phase 1 preview · static build
            </span>
            <h1 className="mt-6 text-4xl font-bold tracking-tight sm:text-5xl">
              Catch payment fraud before the money moves.
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

          {/* Product-shaped mock of a review queue — signals for humans, not verdicts. */}
          <Card className="lg:ml-auto lg:w-full lg:max-w-lg">
            <CardHeader>
              <div className="flex items-center justify-between gap-4">
                <CardTitle className="text-base">Invoice INV-2041</CardTitle>
                <span className="rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-medium text-amber-900">
                  needs review
                </span>
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
                      <signal.icon className="h-4 w-4 text-muted-foreground" />
                      {signal.title}
                    </span>
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${signal.toneClass}`}>
                      {signal.tone}
                    </span>
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

        <section className="pb-20">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Built on non-negotiables
          </h2>
          <div className="mt-4 grid gap-4 md:grid-cols-3">
            {PRINCIPLES.map((principle) => (
              <Card key={principle.title}>
                <CardHeader className="pb-3">
                  <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-muted">
                    <principle.icon className="h-5 w-5 text-muted-foreground" />
                  </span>
                  <CardTitle className="text-base">{principle.title}</CardTitle>
                </CardHeader>
                <CardContent className="text-sm text-muted-foreground">{principle.body}</CardContent>
              </Card>
            ))}
          </div>
        </section>
      </main>

      <footer className="border-t">
        <div className="mx-auto flex w-full max-w-6xl flex-col items-start justify-between gap-2 px-4 py-6 text-sm text-muted-foreground sm:flex-row sm:items-center sm:px-6">
          <p>© 2026 VeriPay — invoice &amp; payment fraud prevention for finance &amp; procurement teams.</p>
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
