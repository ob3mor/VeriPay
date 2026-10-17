"use client";

/**
 * Case detail — evidence, the investigation record, and role-aware actions
 * (R6; docs/API.md §6 cases surface).
 *
 * Static export note: this page is reached as /dashboard/cases/detail?id=<uuid>
 * (no dynamic segments — the export has no server to resolve them).
 *
 * Data (all real, via lib/api.ts):
 * - GET /cases/{id} and GET /cases/{id}/actions (the investigation record —
 *   every human decision lands in review_actions, not free-floating notes).
 * - Evidence, composed client-side as the API allows: for invoice cases the
 *   invoice + its LATEST assessment (the API has no assessment-by-id read,
 *   so the assessment that originally triggered the case is not addressable —
 *   stated honestly on screen); for vendor cases the vendor + its bank
 *   accounts with their R5 verification status.
 *
 * Role-aware actions (docs/API.md §5 matrix, mirrored from
 * apps/api/app/tenancy/permissions.py):
 * - Assign / add a note: org_admin, finance_officer, reviewer (CAN_CONTRIBUTE).
 * - Close with outcome + resolution summary: org_admin, reviewer only (R6).
 *
 * Invariants: R2 (an outcome is a disposition, never a genuineness claim),
 * R6 (close is human-only; outcome + summary mandatory — enforced here AND
 * server-side with 422 business_rule_violation).
 */

import { Suspense, useId, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Inbox, UserPlus } from "lucide-react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { SeverityBadge } from "@/components/severity-badge";
import { SkeletonList } from "@/components/skeleton";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useMe } from "@/hooks/use-session";
import {
  ApiError,
  addReviewAction,
  assignCase,
  closeCase,
  getCase,
  getInvoice,
  getLatestAssessment,
  getVendor,
  listBankAccounts,
  listReviewActions,
} from "@/lib/api";
import { roleLabel } from "@/lib/auth";
import {
  assessmentRiskPresentation,
  bankAccountStatusPresentation,
  caseOutcomePresentation,
  caseStatusPresentation,
  invoiceStatusPresentation,
  vendorStatusPresentation,
  type StatusPresentation,
} from "@/lib/status";
import type { CaseCloseIn, CaseOutcome, FraudFindingOut } from "@veripay/api-contracts";

const SELECT_CLASS =
  "h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";

const TEXTAREA_CLASS =
  "min-h-24 w-full rounded-md border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";

const OUTCOMES: CaseOutcome[] = [
  "fraud_confirmed",
  "policy_violation",
  "false_positive",
  "no_critical_findings",
  "inconclusive",
];

/** Finding disposition → quiet factual chip (no verdict language). */
const DISPOSITION_PRESENTATION: Record<string, StatusPresentation> = {
  open: { label: "Undispositioned", tone: "neutral" },
  acknowledged: { label: "Acknowledged", tone: "info" },
  dismissed: { label: "Dismissed", tone: "muted" },
};

/** Review-action type → factual label (unknown values render as-is). */
const ACTION_TYPE_LABELS: Record<string, string> = {
  comment: "Comment",
  decision: "Decision",
  assignment: "Assignment",
  status_change: "Status change",
  field_verified: "Field verified",
  account_verified: "Account verified",
  account_change_approved: "Account change approved",
  account_change_rejected: "Account change rejected",
};

function shortId(id: string | null | undefined): string {
  if (!id) return "—";
  return id.length > 8 ? `${id.slice(0, 8)}…` : id;
}

function isNotFound(error: unknown): error is ApiError {
  return error instanceof ApiError && error.status === 404;
}

function payloadText(payload: Record<string, unknown> | null): string | null {
  if (!payload || Object.keys(payload).length === 0) return null;
  try {
    return JSON.stringify(payload, null, 2);
  } catch {
    return null;
  }
}

/** ReviewActionOut carries only actor_user_id (no actor_type): NULL means the
 *  system generated the action (e.g. the auto-open reason). */
function actorLabel(actorUserId: string | null, meId: string | null): string {
  if (!actorUserId) return "System";
  if (meId && actorUserId === meId) return "You";
  return shortId(actorUserId);
}

export default function CaseDetailPage() {
  // useSearchParams needs a Suspense boundary to prerender in the static export.
  return (
    <Suspense fallback={<SkeletonList rows={6} />}>
      <CaseDetailView />
    </Suspense>
  );
}

function CaseDetailView() {
  const searchParams = useSearchParams();
  const caseId = searchParams.get("id")?.trim() ?? "";
  const router = useRouter();
  const queryClient = useQueryClient();
  const me = useMe();
  const meData = me.data;
  const meId = meData?.user.id ?? null;
  const role = meData?.user.role;

  const canWork =
    role === "org_admin" || role === "finance_officer" || role === "reviewer";
  const canDecide = role === "org_admin" || role === "reviewer";

  const caseQuery = useQuery({
    queryKey: ["cases", "detail", caseId],
    queryFn: () => getCase(caseId),
    enabled: caseId.length > 0,
  });
  const data = caseQuery.data;

  const actionsQuery = useQuery({
    queryKey: ["cases", "actions", caseId],
    queryFn: async () => (await listReviewActions(caseId)).items,
    enabled: caseId.length > 0 && !!data,
  });

  // --- Evidence: composed client-side, keyed off what the case references ---
  const invoiceId = data?.invoice_id ?? null;
  const vendorId = data?.vendor_id ?? null;

  const invoiceQuery = useQuery({
    queryKey: ["invoices", invoiceId],
    queryFn: () => getInvoice(invoiceId!),
    enabled: !!invoiceId,
  });
  const assessmentQuery = useQuery({
    queryKey: ["invoices", invoiceId, "assessment"],
    queryFn: () => getLatestAssessment(invoiceId!),
    enabled: !!invoiceId,
  });
  const vendorQuery = useQuery({
    queryKey: ["vendors", vendorId],
    queryFn: () => getVendor(vendorId!),
    enabled: !!vendorId,
  });
  const accountsQuery = useQuery({
    queryKey: ["vendors", vendorId, "bank-accounts"],
    queryFn: async () => (await listBankAccounts(vendorId!)).items,
    enabled: !!vendorId,
  });

  const invalidateCases = () => void queryClient.invalidateQueries({ queryKey: ["cases"] });

  // --- Mutations (role-gated in the UI; the API enforces it again) ---
  const assignSelfMutation = useMutation({
    mutationFn: () => assignCase(caseId, { user_id: meId! }),
    onSuccess: invalidateCases,
  });
  const [manualUserId, setManualUserId] = useState("");
  const assignUserMutation = useMutation({
    mutationFn: (userId: string) => assignCase(caseId, { user_id: userId }),
    onSuccess: () => {
      setManualUserId("");
      invalidateCases();
    },
  });

  const [noteBody, setNoteBody] = useState("");
  const noteMutation = useMutation({
    mutationFn: (body: string) =>
      addReviewAction(caseId, { action_type: "comment", body }),
    onSuccess: () => {
      setNoteBody("");
      invalidateCases();
    },
  });

  const [outcome, setOutcome] = useState<CaseOutcome | "">("");
  const [summary, setSummary] = useState("");
  const [confirmCloseOpen, setConfirmCloseOpen] = useState(false);
  const closeMutation = useMutation({
    mutationFn: (input: CaseCloseIn) => closeCase(caseId, input),
    onSuccess: () => {
      setOutcome("");
      setSummary("");
      setConfirmCloseOpen(false);
      invalidateCases();
    },
  });

  const canSubmitClose = outcome !== "" && summary.trim().length > 0;

  const findings = useMemo<FraudFindingOut[]>(
    () => assessmentQuery.data?.findings ?? [],
    [assessmentQuery.data]
  );

  const backLink = (
    <Link
      href="/dashboard/cases"
      className="inline-flex items-center gap-1.5 text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
    >
      <ArrowLeft className="h-4 w-4" />
      All cases
    </Link>
  );

  // ------------------------------------------------------------ guard states
  if (caseId.length === 0) {
    return (
      <div className="space-y-6">
        {backLink}
        <EmptyState
          icon={Inbox}
          title="No case selected"
          description="Open a case from the review queue — this screen shows one case at a time."
          action={
            <Button variant="outline" size="sm" onClick={() => router.push("/dashboard/cases")}>
              Go to the case queue
            </Button>
          }
        />
      </div>
    );
  }

  if (caseQuery.isPending) {
    return (
      <div className="space-y-6">
        {backLink}
        <SkeletonList rows={6} />
      </div>
    );
  }

  if (caseQuery.isError) {
    if (isNotFound(caseQuery.error)) {
      return (
        <div className="space-y-6">
          {backLink}
          <EmptyState
            icon={Inbox}
            title="Case not found"
            description="No case with this ID exists in your organization. Another organization's case is deliberately indistinguishable from a nonexistent one (docs/API.md §5)."
            action={
              <Button variant="outline" size="sm" onClick={() => router.push("/dashboard/cases")}>
                Go to the case queue
              </Button>
            }
          />
        </div>
      );
    }
    return (
      <div className="space-y-6">
        {backLink}
        <ErrorState
          error={caseQuery.error}
          onRetry={() => void caseQuery.refetch()}
        />
      </div>
    );
  }

  // Explicit data guard: TanStack's result union keeps a placeholder variant
  // where data is still undefined even after the isPending/isError checks.
  if (!data) return null;

  const isClosed = data.status === "closed";

  return (
    <div className="space-y-6">
      {backLink}

      <PageHeader
        title={data.title}
        description={`Case ${data.case_number} — a human review obligation (R6). Closing requires an outcome and a resolution summary.`}
        actions={
          <>
            <SeverityBadge severity={data.severity} />
            <StatusBadge presentation={caseStatusPresentation(data.status)} />
            {data.outcome ? (
              <StatusBadge presentation={caseOutcomePresentation(data.outcome)} />
            ) : null}
          </>
        }
      />

      <div className="grid gap-6 lg:grid-cols-3">
        {/* ------------------------------------------------- left: evidence */}
        <div className="space-y-6 lg:col-span-2">
          {invoiceId ? (
            <section aria-labelledby="invoice-evidence-heading" className="space-y-3">
              <h2 id="invoice-evidence-heading" className="text-sm font-medium text-muted-foreground">
                Invoice evidence
              </h2>
              {invoiceQuery.isPending ? (
                <SkeletonList rows={2} labeled={false} />
              ) : invoiceQuery.isError ? (
                <ErrorState
                  title="Could not load the invoice"
                  error={invoiceQuery.error}
                  onRetry={() => void invoiceQuery.refetch()}
                />
              ) : (
                <div className="rounded-lg border bg-card p-6">
                  <dl className="grid gap-x-8 gap-y-4 sm:grid-cols-2">
                    <FactTerm term="Invoice number">
                      <span className="font-medium">{invoiceQuery.data.invoice_number}</span>
                    </FactTerm>
                    <FactTerm term="Workflow status">
                      <StatusBadge presentation={invoiceStatusPresentation(invoiceQuery.data.status)} />
                    </FactTerm>
                    <FactTerm term="Total">
                      <span className="font-mono text-sm">
                        {invoiceQuery.data.total_amount ?? "Not on file"}
                        {invoiceQuery.data.currency ? ` ${invoiceQuery.data.currency}` : ""}
                      </span>
                    </FactTerm>
                    <FactTerm term="Remittance account (masked)">
                      <span className="font-mono text-sm">
                        {invoiceQuery.data.remittance_account_last4
                          ? `•••• ${invoiceQuery.data.remittance_account_last4}`
                          : "Not on file"}
                        {invoiceQuery.data.remittance_bank_name_raw
                          ? ` — ${invoiceQuery.data.remittance_bank_name_raw}`
                          : ""}
                      </span>
                    </FactTerm>
                    <FactTerm term="Vendor">
                      <span className="font-mono text-xs" title={invoiceQuery.data.vendor_id ?? undefined}>
                        {invoiceQuery.data.vendor_id ? shortId(invoiceQuery.data.vendor_id) : "Unresolved"}
                      </span>
                    </FactTerm>
                  </dl>
                </div>
              )}

              <div className="rounded-lg border bg-card p-6">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="text-sm font-semibold">Latest fraud assessment</h3>
                  <span className="text-xs text-muted-foreground">Decision support — never a verdict (R2)</span>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  Shows the invoice&apos;s <span className="font-medium">latest</span> assessment; the API does not
                  expose the specific assessment that triggered this case.
                </p>
                <div className="mt-4">
                  {assessmentQuery.isPending ? (
                    <SkeletonList rows={2} labeled={false} />
                  ) : assessmentQuery.isError ? (
                    <ErrorState
                      title="Could not load the assessment"
                      error={assessmentQuery.error}
                      onRetry={() => void assessmentQuery.refetch()}
                    />
                  ) : assessmentQuery.data === null ? (
                    <p className="text-sm text-muted-foreground">
                      No assessment has been run for this invoice yet.
                    </p>
                  ) : (
                    <div className="space-y-4">
                      <div className="flex flex-wrap items-center gap-2">
                        <StatusBadge
                          presentation={assessmentRiskPresentation(assessmentQuery.data.risk_level)}
                        />
                        <span className="font-mono text-xs text-muted-foreground">
                          risk_score {assessmentQuery.data.risk_score ?? "not computable"} ·{" "}
                          {assessmentQuery.data.model_version} · status {assessmentQuery.data.status}
                        </span>
                      </div>

                      {assessmentQuery.data.explanation.length > 0 && (
                        <ul className="list-disc space-y-1 pl-5 text-sm text-foreground/90">
                          {assessmentQuery.data.explanation.map((line, index) => (
                            <li key={index}>{line}</li>
                          ))}
                        </ul>
                      )}

                      {findings.length > 0 ? (
                        <div className="overflow-hidden rounded-md border">
                          <table className="w-full text-sm">
                            <caption className="sr-only">Findings from the assessment</caption>
                            <thead>
                              <tr className="border-b bg-muted/40 text-left text-xs uppercase tracking-wide text-muted-foreground">
                                <th scope="col" className="px-3 py-2 font-medium">Severity</th>
                                <th scope="col" className="px-3 py-2 font-medium">Finding</th>
                                <th scope="col" className="px-3 py-2 font-medium">Disposition</th>
                              </tr>
                            </thead>
                            <tbody>
                              {findings.map((finding) => (
                                <tr key={finding.id} className="border-b border-border/60 last:border-0">
                                  <td className="px-3 py-2 align-top">
                                    <SeverityBadge severity={finding.severity} />
                                  </td>
                                  <td className="px-3 py-2">
                                    <span className="font-mono text-xs text-muted-foreground">
                                      {finding.signal_type}
                                    </span>
                                    <p className="mt-0.5">{finding.message}</p>
                                  </td>
                                  <td className="px-3 py-2 align-top">
                                    <StatusBadge
                                      hideDot
                                      presentation={
                                        DISPOSITION_PRESENTATION[finding.disposition] ?? {
                                          label: finding.disposition,
                                          tone: "neutral",
                                        }
                                      }
                                    />
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      ) : assessmentQuery.data.signals.length > 0 ? (
                        <ul className="space-y-2">
                          {assessmentQuery.data.signals.map((signal, index) => (
                            <li key={index} className="flex items-start gap-3 rounded-md border px-3 py-2">
                              <SeverityBadge severity={signal.severity} />
                              <div className="min-w-0">
                                <span className="font-mono text-xs text-muted-foreground">{signal.type}</span>
                                <p className="text-sm">{signal.message}</p>
                              </div>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="text-sm text-muted-foreground">
                          No signals were recorded — the assessment found no material discrepancies. That is a
                          statement about what the assessment checked, not a claim that the invoice is genuine (R2).
                        </p>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </section>
          ) : null}

          {vendorId ? (
            <section aria-labelledby="vendor-evidence-heading" className="space-y-3">
              <h2 id="vendor-evidence-heading" className="text-sm font-medium text-muted-foreground">
                Vendor evidence
              </h2>
              {vendorQuery.isPending ? (
                <SkeletonList rows={2} labeled={false} />
              ) : vendorQuery.isError ? (
                <ErrorState
                  title="Could not load the vendor"
                  error={vendorQuery.error}
                  onRetry={() => void vendorQuery.refetch()}
                />
              ) : (
                <div className="rounded-lg border bg-card p-6">
                  <dl className="grid gap-x-8 gap-y-4 sm:grid-cols-2">
                    <FactTerm term="Vendor">
                      <span className="font-medium">{vendorQuery.data.display_name}</span>
                    </FactTerm>
                    <FactTerm term="Status">
                      <StatusBadge presentation={vendorStatusPresentation(vendorQuery.data.status)} />
                    </FactTerm>
                    <FactTerm term="Tax ID (masked)">
                      <span className="font-mono text-sm">
                        {vendorQuery.data.tax_id_masked ?? "Not on file"}
                      </span>
                    </FactTerm>
                  </dl>

                  <div className="mt-5">
                    <h3 className="text-sm font-semibold">Bank accounts (R5)</h3>
                    {accountsQuery.isPending ? (
                      <SkeletonList rows={2} labeled={false} />
                    ) : accountsQuery.isError ? (
                      <ErrorState
                        title="Could not load bank accounts"
                        error={accountsQuery.error}
                        onRetry={() => void accountsQuery.refetch()}
                      />
                    ) : accountsQuery.data.length === 0 ? (
                      <p className="mt-2 text-sm text-muted-foreground">
                        No accounts on file. Absence of a record is not proof of fraud — it is reported as missing
                        evidence (R4), and any pay-to destination still requires independent human verification (R5).
                      </p>
                    ) : (
                      <div className="mt-2 overflow-x-auto rounded-md border">
                        <table className="w-full text-sm">
                          <caption className="sr-only">Vendor bank accounts and verification status</caption>
                          <thead>
                            <tr className="border-b bg-muted/40 text-left text-xs uppercase tracking-wide text-muted-foreground">
                              <th scope="col" className="px-3 py-2 font-medium">Holder</th>
                              <th scope="col" className="px-3 py-2 font-medium">Bank</th>
                              <th scope="col" className="px-3 py-2 font-medium">Account</th>
                              <th scope="col" className="px-3 py-2 font-medium">Verification</th>
                            </tr>
                          </thead>
                          <tbody>
                            {accountsQuery.data.map((account) => (
                              <tr key={account.id} className="border-b border-border/60 last:border-0">
                                <td className="px-3 py-2">
                                  {account.account_holder_name}
                                  {account.is_current ? (
                                    <span className="ml-2 rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
                                      current
                                    </span>
                                  ) : null}
                                </td>
                                <td className="px-3 py-2">{account.bank_name ?? "—"}</td>
                                <td className="px-3 py-2 font-mono text-xs">
                                  {account.account_number_last4 ? `•••• ${account.account_number_last4}` : "—"}
                                </td>
                                <td className="px-3 py-2">
                                  <StatusBadge
                                    presentation={bankAccountStatusPresentation(account.status)}
                                  />
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </section>
          ) : null}

          {/* --------------------------------- the investigation record */}
          <section aria-labelledby="record-heading" className="space-y-3">
            <h2 id="record-heading" className="text-sm font-medium text-muted-foreground">
              Investigation record
            </h2>
            <div className="rounded-lg border bg-card p-6">
              {actionsQuery.isPending ? (
                <SkeletonList rows={3} labeled={false} />
              ) : actionsQuery.isError ? (
                <ErrorState
                  title="Could not load the investigation record"
                  error={actionsQuery.error}
                  onRetry={() => void actionsQuery.refetch()}
                />
              ) : actionsQuery.data.length === 0 ? (
                <p className="text-sm text-muted-foreground">No actions recorded yet.</p>
              ) : (
                <ol className="space-y-4">
                  {actionsQuery.data.map((action) => {
                    const payload = payloadText(action.payload);
                    return (
                      <li key={action.id} className="border-b border-border/60 pb-4 last:border-0 last:pb-0">
                        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                          <span className="rounded bg-muted px-1.5 py-0.5 font-medium text-foreground">
                            {ACTION_TYPE_LABELS[action.action_type] ?? action.action_type}
                          </span>
                          <span>{actorLabel(action.actor_user_id, meId)}</span>
                        </div>
                        <p className="mt-1.5 whitespace-pre-wrap text-sm">{action.body}</p>
                        {payload ? (
                          <details className="mt-1.5">
                            <summary className="cursor-pointer text-xs text-muted-foreground">
                              structured payload
                            </summary>
                            <pre className="mt-1 overflow-x-auto rounded bg-muted/50 p-2 font-mono text-xs">
                              {payload}
                            </pre>
                          </details>
                        ) : null}
                      </li>
                    );
                  })}
                </ol>
              )}

              {canWork ? (
                <NoteForm
                  body={noteBody}
                  onBodyChange={setNoteBody}
                  pending={noteMutation.isPending}
                  onSubmit={() => noteMutation.mutate(noteBody.trim())}
                  disabled={noteBody.trim().length === 0 || noteMutation.isPending}
                />
              ) : (
                <p className="mt-4 border-t pt-4 text-xs text-muted-foreground">
                  Adding notes requires the finance officer, reviewer, or organization admin role (docs/API.md §5).
                </p>
              )}

              {noteMutation.isError ? (
                <ErrorState
                  className="mt-3"
                  title="Could not add the note"
                  error={noteMutation.error}
                  onRetry={() => noteMutation.reset()}
                  retryLabel="Dismiss"
                />
              ) : null}
            </div>
          </section>
        </div>

        {/* ------------------------------------------- right: facts + actions */}
        <div className="space-y-6">
          <section aria-labelledby="facts-heading" className="space-y-3">
            <h2 id="facts-heading" className="text-sm font-medium text-muted-foreground">
              Case facts
            </h2>
            <div className="rounded-lg border bg-card p-6">
              <dl className="space-y-4">
                <FactTerm term="Status">
                  <StatusBadge presentation={caseStatusPresentation(data.status)} />
                </FactTerm>
                <FactTerm term="Outcome">
                  {data.outcome ? (
                    <StatusBadge presentation={caseOutcomePresentation(data.outcome)} />
                  ) : (
                    <span className="text-sm text-muted-foreground">
                      Not closed — a human records the outcome at close (R6)
                    </span>
                  )}
                </FactTerm>
                <FactTerm term="Assignee">
                  <span className="font-mono text-xs" title={data.assigned_to ?? undefined}>
                    {data.assigned_to
                      ? meId && data.assigned_to === meId
                        ? "You"
                        : shortId(data.assigned_to)
                      : "Unassigned"}
                  </span>
                </FactTerm>
                <FactTerm term="Linked invoice">
                  <span className="font-mono text-xs" title={data.invoice_id ?? undefined}>
                    {data.invoice_id ? shortId(data.invoice_id) : "—"}
                  </span>
                </FactTerm>
                <FactTerm term="Linked vendor">
                  <span className="font-mono text-xs" title={data.vendor_id ?? undefined}>
                    {data.vendor_id ? shortId(data.vendor_id) : "—"}
                  </span>
                </FactTerm>
              </dl>
              {isClosed ? (
                <p className="mt-4 border-t pt-4 text-xs text-muted-foreground">
                  This case is closed. The outcome above was recorded by a human; the resolution summary is stored
                  with the case record on the server (the case endpoint does not echo it back).
                </p>
              ) : null}
            </div>
          </section>

          <section aria-labelledby="actions-heading" className="space-y-3">
            <h2 id="actions-heading" className="text-sm font-medium text-muted-foreground">
              Actions
            </h2>
            <div className="space-y-6 rounded-lg border bg-card p-6">
              {canWork ? (
                <div>
                  <h3 className="text-sm font-semibold">Assignment</h3>
                  {assignSelfMutation.isError ? (
                    <ErrorState
                      className="mt-2"
                      title="Could not assign this case to you"
                      error={assignSelfMutation.error}
                      onRetry={() => assignSelfMutation.reset()}
                      retryLabel="Dismiss"
                    />
                  ) : null}
                  {assignUserMutation.isError ? (
                    <ErrorState
                      className="mt-2"
                      title="Could not assign this case"
                      error={assignUserMutation.error}
                      onRetry={() => assignUserMutation.reset()}
                      retryLabel="Dismiss"
                    />
                  ) : null}
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={!meId || assignSelfMutation.isPending || data.assigned_to === meId}
                      onClick={() => assignSelfMutation.mutate()}
                    >
                      <UserPlus />
                      Assign to me
                    </Button>
                  </div>
                  <div className="mt-3 space-y-1.5">
                    <Label htmlFor="assign-user-id">Assign to another member (user ID)</Label>
                    <div className="flex gap-2">
                      <Input
                        id="assign-user-id"
                        className="font-mono text-xs"
                        placeholder="Paste a user UUID"
                        value={manualUserId}
                        onChange={(event) => setManualUserId(event.target.value)}
                      />
                      <Button
                        size="sm"
                        variant="secondary"
                        disabled={
                          manualUserId.trim().length === 0 || assignUserMutation.isPending
                        }
                        onClick={() => assignUserMutation.mutate(manualUserId.trim())}
                      >
                        Assign
                      </Button>
                    </div>
                    <p className="text-xs text-muted-foreground">
                      The API does not list organization members yet, so the ID must be pasted. Assigning a user who
                      is not in your organization fails with “not found”.
                    </p>
                  </div>
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">
                  Case work (assignment, notes) requires the finance officer, reviewer, or organization admin role —
                  you are signed in as {role ? roleLabel(role) : "unknown"} (docs/API.md §5).
                </p>
              )}

              <div className="border-t pt-5">
                <h3 className="text-sm font-semibold">Close this case (R6)</h3>
                {isClosed ? (
                  <p className="mt-2 text-xs text-muted-foreground">
                    Closed — the outcome is recorded and the case can no longer be changed.
                  </p>
                ) : canDecide ? (
                  <>
                    <p className="mt-2 text-xs text-muted-foreground">
                      Recording an outcome is a human decision, stored in the audit trail. An outcome is a case
                      disposition — it never states that an invoice or vendor is genuine (R2).
                    </p>
                    <div className="mt-3 space-y-3">
                      <div className="space-y-1.5">
                        <Label htmlFor="close-outcome">Outcome (required)</Label>
                        <select
                          id="close-outcome"
                          className={SELECT_CLASS}
                          value={outcome}
                          onChange={(event) => setOutcome(event.target.value as CaseOutcome | "")}
                        >
                          <option value="">Select an outcome…</option>
                          {OUTCOMES.map((value) => (
                            <option key={value} value={value}>
                              {caseOutcomePresentation(value).label}
                            </option>
                          ))}
                        </select>
                      </div>
                      <div className="space-y-1.5">
                        <Label htmlFor="close-summary">Resolution summary (required)</Label>
                        <textarea
                          id="close-summary"
                          className={TEXTAREA_CLASS}
                          placeholder="What was reviewed, what was decided, and why — the durable human explanation."
                          value={summary}
                          onChange={(event) => setSummary(event.target.value)}
                        />
                      </div>
                      <Button
                        disabled={!canSubmitClose || closeMutation.isPending}
                        onClick={() => setConfirmCloseOpen(true)}
                      >
                        {closeMutation.isPending ? "Recording…" : "Record outcome & close"}
                      </Button>
                      {!canSubmitClose ? (
                        <p className="text-xs text-muted-foreground">
                          Both fields are mandatory — the API rejects a close without them (422, R6).
                        </p>
                      ) : null}
                    </div>
                  </>
                ) : (
                  <p className="mt-2 text-xs text-muted-foreground">
                    Closing a case requires the reviewer or organization admin role (docs/API.md §5). You are signed
                    in as {role ? roleLabel(role) : "unknown"}.
                  </p>
                )}
                {closeMutation.isError ? (
                  <ErrorState
                    className="mt-3"
                    title="Could not close the case"
                    error={closeMutation.error}
                    onRetry={() => closeMutation.reset()}
                    retryLabel="Dismiss"
                  />
                ) : null}
              </div>
            </div>
          </section>
        </div>
      </div>

      <ConfirmDialog
        open={confirmCloseOpen}
        title={`Close ${data.case_number}?`}
        description={
          <>
            <p>
              This records the outcome{" "}
              <span className="font-medium text-foreground">
                {outcome ? caseOutcomePresentation(outcome).label : ""}
              </span>{" "}
              and your resolution summary as a human decision in the audit trail. It closes the case permanently.
            </p>
            <p className="mt-2">
              It is a disposition of this case — never a claim that the invoice or vendor is genuine (R2), and never
              a payment authorization (R1).
            </p>
          </>
        }
        confirmLabel="Record outcome & close"
        destructive={false}
        onConfirm={() => {
          if (!canSubmitClose) return;
          closeMutation.mutate({ outcome: outcome as CaseOutcome, resolution_summary: summary.trim() });
        }}
        onCancel={() => setConfirmCloseOpen(false)}
      />
    </div>
  );
}

/** Small dt/dd pair used across the fact cards. */
function FactTerm({ term, children }: { term: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{term}</dt>
      <dd className="mt-1 break-words text-sm">{children}</dd>
    </div>
  );
}

/** The add-a-note form — one more entry in the investigation record. */
function NoteForm({
  body,
  onBodyChange,
  pending,
  disabled,
  onSubmit,
}: {
  body: string;
  onBodyChange: (value: string) => void;
  pending: boolean;
  disabled: boolean;
  onSubmit: () => void;
}) {
  const noteId = useId();
  return (
    <form
      className="mt-5 border-t pt-4"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <Label htmlFor={noteId}>Add a note to the record</Label>
      <textarea
        id={noteId}
        className={`${TEXTAREA_CLASS} mt-1.5`}
        placeholder="What you checked, what you found — notes are part of the auditable investigation record."
        value={body}
        onChange={(event) => onBodyChange(event.target.value)}
      />
      <div className="mt-2">
        <Button type="submit" size="sm" disabled={disabled || pending}>
          {pending ? "Adding…" : "Add note"}
        </Button>
      </div>
    </form>
  );
}
