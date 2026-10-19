"use client";

/**
 * Settings — read-only, honest view of the signed-in account and the active
 * risk policy.
 *
 * - Profile + role: live from GET /auth/me via the shared ["auth", "me"]
 *   cache (src/hooks/use-session.ts). There is nothing to edit here: profile
 *   administration (invites, role changes) is a later flow (docs/API.md §4).
 * - "What your role can do": the role × action matrix from docs/API.md §5,
 *   mirrored from the backend's actual guards (apps/api tenancy/permissions.py).
 * - Risk policy (organization admins only, read-only): the documented active
 *   policy — signal vocabulary + default severities + forcing rules
 *   (docs/ARCHITECTURE.md §8) and the R3 confidence gate. Honesty note shown
 *   on screen: the API does not expose a policy endpoint yet, so this renders
 *   the documented policy that the current backend implements (rules-v0.1);
 *   the backend is authoritative if they ever disagree.
 *
 * Invariants carried here: R1 (never authorizes payments), R2 (no genuineness
 * verdicts), R3 (confidence gate), R4 (missing evidence capped), R5 (human-only
 * account verification with provenance), R6 (critical forces human review).
 */

import { KeyRound, ShieldCheck } from "lucide-react";

import { PageHeader } from "@/components/page-header";
import { SeverityBadge } from "@/components/severity-badge";
import { SkeletonList } from "@/components/skeleton";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useMe } from "@/hooks/use-session";
import { getApiRoot } from "@/lib/api";
import { roleLabel } from "@/lib/auth";
import { OCR_CONFIDENCE_THRESHOLD } from "@/lib/status";
import { cn } from "@/lib/utils";
import type { UserRole } from "@veripay/api-contracts";

/** Capability statements per role — mirrored from the backend's role guards
 *  (apps/api/app/tenancy/permissions.py) and docs/API.md §5. Stated as the
 *  role's actual permissions, including what it may NOT do. */
const ROLE_CAPABILITIES: Record<UserRole, readonly string[]> = {
  org_admin: [
    "Upload documents; create vendors, purchase orders and invoices",
    "Run assessments and work cases — assignment, notes",
    "Verify / approve / reject / revoke bank accounts and change requests (R5)",
    "Close cases with an outcome + resolution summary (R6)",
    "View the audit trail",
    "Organization administration",
  ],
  reviewer: [
    "Upload documents; create vendors, purchase orders and invoices",
    "Run assessments and work cases — assignment, notes",
    "Verify / approve / reject / revoke bank accounts and change requests (R5)",
    "Close cases with an outcome + resolution summary (R6)",
    "May NOT view the audit trail",
  ],
  finance_officer: [
    "Upload documents; create vendors, purchase orders and invoices",
    "Run assessments and work cases — assignment, notes",
    "May NOT close cases or verify bank accounts",
    "May NOT view the audit trail",
  ],
  auditor: [
    "View the audit trail (read-only)",
    "May NOT work cases, create data, verify accounts, or administer the organization",
  ],
};

/** The signal vocabulary — single source of truth docs/ARCHITECTURE.md §8. */
const SIGNAL_POLICY: readonly {
  signal: string;
  severity: string;
  note: string;
  forcing: string;
}[] = [
  {
    signal: "missing_evidence",
    severity: "low–medium (capped)",
    note: "A record may simply not exist in VeriPay — absence is not fraud (R4).",
    forcing: "none — informational; humans decide whether to look",
  },
  {
    signal: "unverified_input",
    severity: "low",
    note: "Marks a machine value that failed the R3 confidence gate.",
    forcing: "none — never presented as confident evidence",
  },
  {
    signal: "field_provenance_conflict",
    severity: "medium",
    note: "Invoice column and its extracted provenance disagree; the column wins.",
    forcing: "none — humans are informed",
  },
  {
    signal: "duplicate_candidate",
    severity: "medium",
    note: "A duplicate vendor + invoice number is a fraud signal, not an intake error.",
    forcing: "sets the invoice to needs_review",
  },
  {
    signal: "amount_mismatch",
    severity: "high",
    note: "Invoice total disagrees with the matched purchase order.",
    forcing: "sets the invoice to needs_review",
  },
  {
    signal: "bank_account_unverified",
    severity: "high (floor)",
    note: "The pay-to destination does not match a VERIFIED trusted account (R5).",
    forcing: "sets needs_review; the invoice cannot close while undispositioned",
  },
];

const HARD_LIMITS: readonly string[] = [
  "R1 — VeriPay never authorizes payments: there is no payment-rail integration anywhere; the terminal decision happens outside VeriPay.",
  "R2 — No genuineness verdicts: assessments expose signals, severities and explanations only; even a closed case outcome is a disposition, not a claim that anything is genuine.",
  "R3 — No confidence laundering: machine-extracted values below the confidence gate (or with no confidence) raise an unverified_input observation instead of a mismatch claim.",
  "R4 — No fraud-from-absence: missing records produce missing_evidence signals capped at medium severity.",
  "R5 — No automatic bank-account verification: only a human can approve an account, and only with an independent verification method plus a reference or supporting document.",
  "R6 — No auto-resolution of critical findings: a critical assessment always opens a case; only a human records the closing outcome and summary.",
];

export default function SettingsPage() {
  const me = useMe();
  const data = me.data;
  const role = data?.user.role;
  const isAdmin = role === "org_admin";

  return (
    <div className="space-y-8">
      <PageHeader
        title="Settings"
        description="Your account, your role's permissions, and the active risk policy — all read-only here."
      />

      {/* ------------------------------------------------------- profile */}
      <section aria-labelledby="profile-heading" className="max-w-3xl">
        <h2 id="profile-heading" className="text-sm font-medium text-muted-foreground">
          Profile
        </h2>
        <Card className="mt-3">
          <CardHeader className="pb-4">
            <CardTitle className="text-base">Signed-in user</CardTitle>
            <CardDescription>
              Live from <span className="font-mono text-xs">GET /auth/me</span> at{" "}
              <span className="font-mono text-xs">{getApiRoot()}</span>. Editing profiles and
              managing members arrives with the invitation flow (docs/API.md §4).
            </CardDescription>
          </CardHeader>
          <CardContent>
            {me.isPending ? (
              <SkeletonList rows={3} labeled={false} />
            ) : me.isError ? (
              <p className="text-sm text-muted-foreground">
                Could not load your account
                {me.error instanceof Error ? ` — ${me.error.message}` : ""}. The page still
                renders; try reloading once the API at{" "}
                <span className="font-mono text-xs">{getApiRoot()}</span> is reachable.
              </p>
            ) : data ? (
              <dl className="grid gap-x-8 gap-y-4 sm:grid-cols-2">
                <Fact term="Full name" value={data.user.full_name} />
                <Fact term="Email" value={data.user.email} mono />
                <Fact term="User ID" value={data.user.id} mono />
                <Fact term="Organization" value={data.organization.name} />
                <Fact term="Org slug" value={data.organization.slug} mono />
                <Fact term="Org ID" value={data.organization.id} mono />
                <div className="min-w-0 sm:col-span-2">
                  <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Role
                  </dt>
                  <dd className="mt-1">
                    <span className="inline-flex items-center gap-1.5 rounded-sm border border-primary/30 bg-primary/12 px-2 py-0.5 text-xs font-medium text-primary">
                      <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
                      {roleLabel(data.user.role)}
                    </span>
                    <span className="ml-2 font-mono text-xs text-muted-foreground">
                      {data.user.role}
                    </span>
                  </dd>
                </div>
              </dl>
            ) : null}
          </CardContent>
        </Card>
      </section>

      {/* ----------------------------------------------------- role matrix */}
      {role ? (
        <section aria-labelledby="role-heading" className="max-w-3xl">
          <h2 id="role-heading" className="text-sm font-medium text-muted-foreground">
            What your role can do
          </h2>
          <Card className="mt-3">
            <CardHeader className="pb-3">
              <CardTitle className="text-base">{roleLabel(role)}</CardTitle>
              <CardDescription>
                Mirrors the backend&apos;s enforced role × action matrix (docs/API.md §5) — the
                server re-checks every action regardless of what this page shows.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ul className="space-y-2">
                {ROLE_CAPABILITIES[role].map((capability) => (
                  <li key={capability} className="flex items-start gap-2 text-sm">
                    <span
                      aria-hidden="true"
                      className={cn(
                        "mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full",
                        capability.startsWith("May NOT")
                          ? "bg-muted-foreground"
                          : "bg-success"
                      )}
                    />
                    {capability}
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        </section>
      ) : null}

      {/* ---------------------------------------------------- risk policy */}
      <section aria-labelledby="policy-heading" className="max-w-3xl">
        <h2 id="policy-heading" className="text-sm font-medium text-muted-foreground">
          Risk policy
        </h2>

        {isAdmin ? (
          <Card className="mt-3">
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Active policy — read-only view</CardTitle>
              <CardDescription>
                The documented policy the current backend implements (rules-v0.1,
                docs/ARCHITECTURE.md §8). The API does not expose a policy endpoint yet, so this
                page cannot query it live — if this view and the backend ever disagree, the
                backend is authoritative. Nothing here is editable from the product.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="overflow-x-auto rounded-md border">
                <table className="w-full text-sm">
                  <caption className="sr-only">
                    Signal vocabulary with default severities and forcing rules
                  </caption>
                  <thead>
                    <tr className="border-b bg-panel/70 text-left font-mono text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                      <th scope="col" className="px-3 py-2 font-medium">Signal</th>
                      <th scope="col" className="px-3 py-2 font-medium">Default severity</th>
                      <th scope="col" className="px-3 py-2 font-medium">Meaning</th>
                      <th scope="col" className="px-3 py-2 font-medium">Forcing rule</th>
                    </tr>
                  </thead>
                  <tbody>
                    {SIGNAL_POLICY.map((row) => (
                      <tr key={row.signal} className="border-b border-border/60 align-top last:border-0">
                        <td className="whitespace-nowrap px-3 py-2 font-mono text-xs">{row.signal}</td>
                        <td className="whitespace-nowrap px-3 py-2">
                          <Severity severityLabel={row.severity} />
                        </td>
                        <td className="px-3 py-2 text-muted-foreground">{row.note}</td>
                        <td className="px-3 py-2 text-muted-foreground">{row.forcing}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="rounded-md border bg-muted/30 p-4 text-sm">
                <p className="flex items-center gap-2 font-medium">
                  <KeyRound className="h-4 w-4" aria-hidden="true" />
                  Confidence gate (R3)
                </p>
                <p className="mt-1 text-muted-foreground">
                  Machine-extracted values enter fraud features only at confidence ≥{" "}
                  <span className="font-mono">{OCR_CONFIDENCE_THRESHOLD}</span> or when a human
                  supplied/verified the value. Below the gate — including all stub-OCR output — a
                  feature emits an <span className="font-mono text-xs">unverified_input</span>{" "}
                  observation instead of a mismatch claim. Low confidence can lower trust in a
                  value; it is never presented as confident evidence.
                </p>
              </div>

              <div>
                <p className="text-sm font-medium">Hard limits — normative, never configurable away</p>
                <ul className="mt-2 space-y-2">
                  {HARD_LIMITS.map((limit) => (
                    <li key={limit} className="flex items-start gap-2 text-sm">
                      <span
                        aria-hidden="true"
                        className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-destructive"
                      />
                      <span className="text-muted-foreground">{limit}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </CardContent>
          </Card>
        ) : me.isError ? null : (
          <Card className="mt-3">
            <CardContent className="pt-6">
              <p className="text-sm text-muted-foreground">
                The risk-policy view is available to organization admins. You are signed in
                as {role ? roleLabel(role) : "a role without policy visibility"} — the policy
                still governs every signal and workflow state you see elsewhere in the product.
              </p>
            </CardContent>
          </Card>
        )}
      </section>
    </div>
  );
}

function Fact({ term, value, mono = false }: { term: string; value: string; mono?: boolean }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{term}</dt>
      <dd className={cn("mt-1 break-words text-sm", mono && "font-mono text-xs sm:text-sm")}>
        {value}
      </dd>
    </div>
  );
}

/** Severity cell for the policy table — free-form labels (e.g. "high (floor)",
 *  "low–medium (capped)") render as quiet chips; plain values use the badge. */
function Severity({ severityLabel }: { severityLabel: string }) {
  if (severityLabel.includes("–") || severityLabel.includes("(")) {
    return (
      <span className="inline-flex whitespace-nowrap rounded-sm border border-border bg-secondary/80 px-2 py-0.5 text-xs font-medium text-secondary-foreground">
        {severityLabel}
      </span>
    );
  }
  return <SeverityBadge severity={severityLabel} />;
}
