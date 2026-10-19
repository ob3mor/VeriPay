import type { Metadata } from "next";

import { AppLogo } from "@/components/app-logo";

export const metadata: Metadata = {
  title: "Account access · VeriPay",
};

/**
 * Shared layout for /login and /register — the Persuade threshold of the
 * examiner's bench: the ledger grid under a focused light, the owner's full
 * lockup (transparent, no plate behind it), and the form as a single plate.
 * Pure server component — no data fetching, static-export friendly.
 */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative flex min-h-screen flex-col overflow-hidden">
      {/* The bench under a focused cyan light. */}
      <div aria-hidden="true" className="absolute inset-0 bg-[radial-gradient(48%_40%_at_50%_-8%,hsl(192_76%_52%/0.1),transparent_70%)]" />

      {/* The instrument's top edge — a single lit rule, bright at the center. */}
      <div
        aria-hidden="true"
        className="h-[2px] w-full shrink-0 bg-gradient-to-r from-transparent via-primary/70 to-transparent"
      />

      <div className="relative flex flex-1 flex-col items-center justify-center px-4 py-14">
        <div className="mb-10">
          <AppLogo size="lg" href="/" />
        </div>

        <div className="w-full max-w-md">{children}</div>

        <p className="mt-10 max-w-sm text-center text-xs leading-relaxed text-muted-foreground">
          VeriPay never authorizes payments automatically and never declares an invoice genuine.
          Critical inconsistencies always go to human review.
        </p>
      </div>
    </div>
  );
}
