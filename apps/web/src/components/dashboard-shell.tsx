"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Building2,
  FileText,
  LayoutDashboard,
  LoaderCircle,
  LogOut,
  Settings,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { useMe, useSignOut } from "@/hooks/use-session";
import { getAccessToken } from "@/lib/auth";
import { cn } from "@/lib/utils";

/** Primary navigation — /dashboard itself is the Overview page. */
const NAV_ITEMS = [
  { href: "/dashboard", label: "Overview", icon: LayoutDashboard },
  { href: "/dashboard/vendors", label: "Vendors", icon: Building2 },
  { href: "/dashboard/invoices", label: "Invoices", icon: FileText },
  { href: "/dashboard/investigations", label: "Investigations", icon: ShieldAlert },
  { href: "/dashboard/settings", label: "Settings", icon: Settings },
] as const;

/**
 * Authenticated app shell: topbar + sidebar (desktop) with a scrollable nav
 * row on small screens.
 *
 * Auth guard: the token lives in localStorage (documented key
 * `veripay:access_token`), which does not exist during the static-export
 * prerender — so the check runs in an effect after mount, and the shell
 * renders the same neutral loading state on server and first client render
 * (no hydration mismatch, no crash without a backend).
 */
export function DashboardShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [checked, setChecked] = useState(false);
  const signOut = useSignOut();
  const me = useMe({ enabled: checked });

  useEffect(() => {
    if (!getAccessToken()) {
      router.replace("/login");
    } else {
      setChecked(true);
    }
  }, [router]);

  if (!checked) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <LoaderCircle className="h-6 w-6 animate-spin text-muted-foreground" aria-label="Loading" />
      </div>
    );
  }

  const email = me.data?.user.email ?? null;
  const organizationName = me.data?.organization.name ?? null;

  return (
    <div className="flex min-h-screen">
      {/* Sidebar (desktop) */}
      <aside className="hidden w-60 shrink-0 flex-col border-r bg-muted/30 md:flex">
        <div className="flex h-16 items-center border-b px-5">
          <Link href="/" className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 items-center justify-center rounded-md bg-primary text-primary-foreground">
              <ShieldCheck className="h-4 w-4" />
            </span>
            <span className="text-base font-semibold tracking-tight">VeriPay</span>
          </Link>
        </div>

        <nav className="flex-1 space-y-1 p-3">
          {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
            const active =
              pathname === href || (href !== "/dashboard" && pathname.startsWith(`${href}/`));
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                  active
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-accent hover:text-foreground"
                )}
              >
                <Icon className="h-4 w-4" />
                {label}
              </Link>
            );
          })}
        </nav>

        <div className="border-t p-4 text-xs leading-relaxed text-muted-foreground">
          <p className="font-medium text-foreground">Phase 1 scaffold</p>
          <p>Live data arrives in Phase 2.</p>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Topbar */}
        <header className="flex h-16 shrink-0 items-center justify-between gap-4 border-b bg-background/95 px-4 md:px-8">
          <div className="flex min-w-0 items-center gap-3">
            <Link href="/" className="flex items-center gap-2 md:hidden">
              <span className="flex h-8 w-8 items-center justify-center rounded-md bg-primary text-primary-foreground">
                <ShieldCheck className="h-4 w-4" />
              </span>
              <span className="font-semibold tracking-tight">VeriPay</span>
            </Link>
            <p className="hidden min-w-0 truncate text-sm text-muted-foreground md:block">
              {email ? (
                <>
                  Signed in as <span className="font-medium text-foreground">{email}</span>
                </>
              ) : (
                "Loading session…"
              )}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-3">
            {organizationName ? (
              <span className="hidden text-xs text-muted-foreground sm:inline">{organizationName}</span>
            ) : null}
            <Button variant="outline" size="sm" onClick={signOut}>
              <LogOut />
              Sign out
            </Button>
          </div>
        </header>

        {/* Compact nav (mobile) */}
        <nav className="flex gap-1 overflow-x-auto border-b px-2 py-2 md:hidden" aria-label="Dashboard">
          {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
            const active =
              pathname === href || (href !== "/dashboard" && pathname.startsWith(`${href}/`));
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex shrink-0 items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium",
                  active
                    ? "bg-primary/10 text-foreground"
                    : "text-muted-foreground hover:bg-accent hover:text-foreground"
                )}
              >
                <Icon className="h-4 w-4" />
                {label}
              </Link>
            );
          })}
        </nav>

        <main className="flex-1 px-4 py-8 md:px-8">{children}</main>
      </div>
    </div>
  );
}
