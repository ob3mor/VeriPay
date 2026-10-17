import type { Metadata } from "next";
import Link from "next/link";
import { ShieldCheck } from "lucide-react";

export const metadata: Metadata = {
  title: "Account access · VeriPay",
};

/**
 * Shared layout for /login and /register: centered card on a muted backdrop.
 * Pure server component — no data fetching, static-export friendly.
 */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-muted/40 px-4 py-12">
      <Link href="/" className="mb-8 flex items-center gap-2.5">
        <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <ShieldCheck className="h-5 w-5" />
        </span>
        <span className="text-xl font-semibold tracking-tight">VeriPay</span>
      </Link>

      <div className="w-full max-w-md">{children}</div>

      <p className="mt-8 max-w-sm text-center text-xs leading-relaxed text-muted-foreground">
        VeriPay never authorizes payments automatically. Critical inconsistencies always go to
        human review.
      </p>
    </div>
  );
}
