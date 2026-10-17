import type { Metadata } from "next";

import { DashboardShell } from "@/components/dashboard-shell";

export const metadata: Metadata = {
  title: "Dashboard · VeriPay",
};

/**
 * Server layout for the (dashboard) route group. The interactive shell (auth
 * guard, sidebar, topbar) is a client component; this wrapper keeps per-route
 * metadata exportable and the component tree clean.
 */
export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return <DashboardShell>{children}</DashboardShell>;
}
