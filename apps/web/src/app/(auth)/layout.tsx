import type { Metadata } from "next";

import { AppLogo } from "@/components/app-logo";

export const metadata: Metadata = {
  title: "Account access · VeriPay",
};

/**
 * Shared layout for /login and /register: centered card on a muted backdrop,
 * the owner's real logo (apps/web/public/logo.png) up top and a thin
 * navy→teal brand strip along the top edge (Prompt 05 palette).
 * Pure server component — no data fetching, static-export friendly.
 */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col bg-muted/40">
      <div
        aria-hidden="true"
        className="h-1 w-full shrink-0 bg-gradient-to-r from-primary via-accent to-primary"
      />
      <div className="flex flex-1 flex-col items-center justify-center px-4 py-12">
        <div className="mb-8">
          <AppLogo size="lg" href="/" />
        </div>

        <div className="w-full max-w-md">{children}</div>

        <p className="mt-8 max-w-sm text-center text-xs leading-relaxed text-muted-foreground">
          VeriPay never authorizes payments automatically and never declares an invoice genuine.
          Critical inconsistencies always go to human review.
        </p>
      </div>
    </div>
  );
}
