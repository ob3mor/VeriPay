"use client";

import { useEffect } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Building2,
  ClipboardList,
  FileText,
  LayoutDashboard,
  LoaderCircle,
  LogOut,
  ScrollText,
  Settings,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { AppLogo } from "@/components/app-logo";
import { isSessionExpired, useMe, useSignOut } from "@/hooks/use-session";
import { cn } from "@/lib/utils";

/**
 * Primary navigation — /dashboard itself is the Overview page.
 * `roles` (when present) filters the entry to the given roles, mirroring the
 * backend's role × action matrix (docs/API.md §5): audit events are visible
 * to org_admin/auditor only, so the link is hidden from other roles AND the
 * audit page itself renders a graceful restricted state on direct visits.
 */
interface NavItem {
  href: string;
  label: string;
  icon: typeof LayoutDashboard;
  roles?: readonly string[];
}

const NAV_ITEMS: NavItem[] = [
  { href: "/dashboard", label: "Overview", icon: LayoutDashboard },
  { href: "/dashboard/vendors", label: "Vendors", icon: Building2 },
  { href: "/dashboard/invoices", label: "Invoices", icon: FileText },
  { href: "/dashboard/cases", label: "Cases", icon: ClipboardList },
  {
    href: "/dashboard/audit",
    label: "Audit trail",
    icon: ScrollText,
    roles: ["org_admin", "auditor"],
  },
  { href: "/dashboard/settings", label: "Settings", icon: Settings },
];

/**
 * Authenticated app shell — the operator's bench: a panel-dark sidebar (the
 * second neutral layer, distinct from the plate layer pages work on), a
 * hairline topbar, and the workspace itself.
 *
 * Active nav items read through the instrument light (cyan text on a cyan
 * tint with a leading dot) — the accent marks "you are here" and nothing
 * else. The bench's charter note (R1/R2) sits at the sidebar's foot like the
 * fine print of an instrument.
 *
 * Auth guard: the durable session is the httpOnly cookie, so membership is
 * checked by GET /auth/me (credentials: "include") — a fresh page load needs
 * no stored token. The check resolves on the client after mount; the shell
 * renders the same neutral loading state on server and first client render
 * (no hydration mismatch, no crash without a backend). A 401 sends the user
 * to /login.
 */
export function DashboardShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const signOut = useSignOut();
  const me = useMe();

  useEffect(() => {
    if (me.isError && isSessionExpired(me.error)) {
      router.replace("/login");
    }
  }, [me.isError, me.error, router]);

  if (me.isPending || me.isError) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <LoaderCircle className="h-6 w-6 animate-spin text-muted-foreground" aria-label="Loading" />
      </div>
    );
  }

  const email = me.data?.user.email ?? null;
  const organizationName = me.data?.organization.name ?? null;
  const role = me.data?.user.role;
  const navItems = NAV_ITEMS.filter(
    (item) => !item.roles || (role !== undefined && item.roles.includes(role))
  );

  return (
    <div className="flex min-h-screen">
      {/* Sidebar (desktop) — the panel layer */}
      <aside className="hidden w-60 shrink-0 flex-col border-r border-border/70 bg-panel md:flex">
        <div className="flex h-16 items-center border-b border-border/70 px-5">
          <AppLogo size="sm" href="/" />
        </div>

        <nav className="flex-1 space-y-1 p-3">
          {navItems.map(({ href, label, icon: Icon }) => {
            const active =
              pathname === href || (href !== "/dashboard" && pathname.startsWith(`${href}/`));
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-panel",
                  active
                    ? "bg-primary/12 text-primary"
                    : "text-muted-foreground hover:bg-secondary/70 hover:text-foreground"
                )}
              >
                <Icon className="h-4 w-4 shrink-0" />
                {label}
                {active && (
                  <span
                    aria-hidden="true"
                    className="ml-auto h-1.5 w-1.5 shrink-0 rounded-full bg-primary"
                  />
                )}
              </Link>
            );
          })}
        </nav>

        {/* The charter, as fine print at the foot of the instrument. */}
        <div className="border-t border-border/70 p-4">
          <p className="font-display text-xs font-semibold text-foreground/90">
            Decision support only
          </p>
          <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
            VeriPay never authorizes payments or claims genuineness —{" "}
            <span className="font-mono text-primary/80">R1</span>
            {" / "}
            <span className="font-mono text-primary/80">R2</span>.
          </p>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Topbar */}
        <header className="sticky top-0 z-20 flex h-16 shrink-0 items-center justify-between gap-4 border-b border-border/70 bg-background/85 px-4 backdrop-blur-sm md:px-8">
          <div className="flex min-w-0 items-center gap-3">
            <AppLogo size="xs" variant="mark" href="/" className="md:hidden" />
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
              <span className="hidden items-center gap-2 text-xs text-muted-foreground sm:flex">
                <span aria-hidden="true" className="h-1 w-1 rounded-full bg-primary/60" />
                {organizationName}
              </span>
            ) : null}
            <Button variant="outline" size="sm" onClick={signOut}>
              <LogOut />
              Sign out
            </Button>
          </div>
        </header>

        {/* Compact nav (mobile) */}
        <nav
          className="flex gap-1 overflow-x-auto border-b border-border/70 bg-panel px-2 py-2 md:hidden"
          aria-label="Dashboard"
        >
          {navItems.map(({ href, label, icon: Icon }) => {
            const active =
              pathname === href || (href !== "/dashboard" && pathname.startsWith(`${href}/`));
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex shrink-0 items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-panel",
                  active
                    ? "bg-primary/12 text-primary"
                    : "text-muted-foreground hover:bg-secondary/70 hover:text-foreground"
                )}
              >
                <Icon className="h-4 w-4" />
                {label}
              </Link>
            );
          })}
        </nav>

        <main className="flex-1 px-4 py-8 md:px-8 md:py-10">{children}</main>
      </div>
    </div>
  );
}
