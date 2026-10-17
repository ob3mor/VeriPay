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
 * Authenticated app shell: topbar + sidebar (desktop) with a scrollable nav
 * row on small screens.
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
      {/* Sidebar (desktop) */}
      <aside className="hidden w-60 shrink-0 flex-col border-r bg-muted/30 md:flex">
        <div className="flex h-16 items-center border-b px-5">
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
          <p className="font-medium text-foreground">Decision support only</p>
          <p>VeriPay never authorizes payments or claims genuineness (R1/R2).</p>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Topbar */}
        <header className="flex h-16 shrink-0 items-center justify-between gap-4 border-b bg-background/95 px-4 md:px-8">
          <div className="flex min-w-0 items-center gap-3">
            <AppLogo size="sm" href="/" className="md:hidden" />
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
          {navItems.map(({ href, label, icon: Icon }) => {
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
