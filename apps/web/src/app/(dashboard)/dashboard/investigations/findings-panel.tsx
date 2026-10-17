"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, ShieldAlert, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { SeverityBadge } from "@/components/severity-badge";
import { StatusBadge } from "@/components/status-badge";
import { assessmentRiskPresentation } from "@/lib/status";
import type { FraudAssessmentOut, FraudFindingOut } from "@veripay/api-contracts";

import { dispositionFinding, mutationMessage } from "./api-extras";

export interface FindingsPanelProps {
  invoiceId: string | null;
  /** Latest assessment from the shared query (null = none run yet). */
  assessment: FraudAssessmentOut | null;
  pending: boolean;
  error: unknown;
  onRetry: () => void;
  canVerify: boolean;
  canContribute: boolean;
  onRunAssessment: () => void;
  runPending: boolean;
  runError: unknown;
}

const SIGNAL_LABELS: Record<string, string> = {
  missing_evidence: "Missing evidence",
  unverified_input: "Unverified input",
  field_provenance_conflict: "Field provenance conflict",
  duplicate_candidate: "Duplicate candidate",
  amount_mismatch: "Amount mismatch",
  bank_account_unverified: "Bank account unverified",
  // EVC v1 additions (≤ medium — uncertainty/absence, never a fraud claim):
  unknown_vendor: "Vendor not resolved",
  ocr_uncertain: "OCR uncertain",
};

/**
 * Risk findings with severity (right pane). Everything shown is recorded
 * machine output — signals, severities, ordered explanations — and every
 * human action is explicit:
 *
 * - Run assessment (contributor roles) writes a new append-only assessment.
 * - Disposition (reviewer/org_admin) annotates one finding; it never
 *   rewrites severity and never un-flags the invoice — the ARCHITECTURE §8
 *   forcing rules are not dispositioned away, and the copy says so.
 * - No "is this invoice genuine?" control exists anywhere (R2); when the
 *   assessment found nothing, the honest outcome label is "No material
 *   discrepancies" — a statement about the findings, not the invoice.
 */
export function FindingsPanel({
  invoiceId,
  assessment,
  pending,
  error,
  onRetry,
  canVerify,
  canContribute,
  onRunAssessment,
  runPending,
  runError,
}: FindingsPanelProps) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Risk findings</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {error ? (
          <ErrorState error={error} title="Could not load the assessment" onRetry={onRetry} />
        ) : pending ? (
          <div className="h-24 animate-pulse rounded bg-muted" role="status" aria-label="Loading assessment" />
        ) : !assessment ? (
          <EmptyState
            icon={ShieldAlert}
            title="No assessment has been run for this invoice"
            description="An assessment computes the explainable signals (PO amount, pay-to destination, duplicates, input provenance) and records them append-only. It supports the human decision — it never makes it."
          />
        ) : (
          <AssessmentView assessment={assessment} canVerify={canVerify} />
        )}

        {canContribute && invoiceId ? (
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="outline" size="sm" onClick={onRunAssessment} disabled={runPending}>
              {assessment ? "Re-run assessment" : "Run assessment"}
            </Button>
            <span className="text-xs text-muted-foreground">
              Append-only: each run records a new assessment; nothing is overwritten.
            </span>
          </div>
        ) : null}
        {runError ? (
          <p className="text-sm text-destructive">
            {mutationMessage(runError, "The assessment could not be computed.")}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function AssessmentView({
  assessment,
  canVerify,
}: {
  assessment: FraudAssessmentOut;
  canVerify: boolean;
}) {
  const outcome = assessmentRiskPresentation(assessment.risk_level);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge presentation={outcome} />
        <SeverityBadge
          severity={assessment.risk_level}
          noneLabel="No signals"
        />
        {assessment.risk_score !== null ? (
          <span className="text-xs text-muted-foreground">
            Score {assessment.risk_score} (within {assessment.model_version})
          </span>
        ) : (
          <span className="text-xs text-muted-foreground">Score not computable</span>
        )}
        <StatusBadge
          presentation={
            assessment.status === "complete"
              ? { label: "Assessment complete", tone: "neutral" }
              : assessment.status === "partial"
                ? { label: "Assessment partial", tone: "warning" }
                : { label: "Assessment failed", tone: "danger" }
          }
          hideDot
        />
      </div>

      {assessment.explanation.length > 0 ? (
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Why (ordered explanation)
          </p>
          <ol className="mt-1 list-decimal space-y-1 pl-5 text-sm text-foreground/90">
            {assessment.explanation.map((line, index) => (
              <li key={index} className="break-words">{line}</li>
            ))}
          </ol>
        </div>
      ) : null}

      {assessment.findings.length > 0 ? (
        <ul className="space-y-3">
          {assessment.findings.map((finding) => (
            <FindingItem key={finding.id} finding={finding} canVerify={canVerify} />
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">
          No per-signal findings were recorded — see the explanation above for
          what the rule set did and did not check.
        </p>
      )}

      <p className="text-xs text-muted-foreground">
        Signals and severities come from the recorded assessment. VeriPay never
        authorizes payments and never certifies an invoice as genuine.
      </p>
    </div>
  );
}

const DISPOSITION_LABELS: Record<string, string> = {
  open: "Open",
  acknowledged: "Acknowledged by human",
  dismissed: "Dismissed by human",
};

function FindingItem({ finding, canVerify }: { finding: FraudFindingOut; canVerify: boolean }) {
  const queryClient = useQueryClient();
  const [dispositioning, setDispositioning] = useState(false);
  const [note, setNote] = useState("");
  const [pendingDisposition, setPendingDisposition] = useState<"acknowledged" | "dismissed" | null>(null);

  const mutation = useMutation({
    mutationFn: (input: { disposition: "acknowledged" | "dismissed"; reason: string }) =>
      dispositionFinding(finding.id, input),
    onSuccess: () => {
      setDispositioning(false);
      setPendingDisposition(null);
      // The assessment payload embeds its findings; refresh it.
      void queryClient.invalidateQueries({ queryKey: ["assessment"] });
    },
  });

  const dispositionLabel = DISPOSITION_LABELS[finding.disposition] ?? finding.disposition;
  // The API refuses an empty reason (422 — FindingDispositionIn model
  // validator), so the record button stays disabled until one is written.
  const reasonReady = note.trim().length > 0;

  return (
    <li className="rounded-md border p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-medium">
            {SIGNAL_LABELS[finding.signal_type] ?? finding.signal_type}
          </p>
          <p className="mt-0.5 break-words text-sm text-foreground/90">{finding.message}</p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-1.5">
          <SeverityBadge severity={finding.severity} />
          <span
            className={
              finding.disposition === "open"
                ? "rounded-full border border-border bg-muted px-2 py-0.5 text-xs text-muted-foreground"
                : "rounded-full border border-primary/20 bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary"
            }
          >
            {dispositionLabel}
          </span>
        </div>
      </div>

      {canVerify && finding.disposition === "open" ? (
        dispositioning ? (
          <div className="mt-2 space-y-2">
            <textarea
              value={note}
              onChange={(event) => setNote(event.target.value)}
              rows={2}
              placeholder="Required: what you checked and why — the reason is recorded with the decision."
              aria-label="Disposition reason (required)"
              className="w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
            <div className="flex flex-wrap items-center gap-2">
              <Button
                size="sm"
                onClick={() => {
                  if (!pendingDisposition || !reasonReady) return;
                  mutation.mutate({
                    disposition: pendingDisposition,
                    reason: note.trim(),
                  });
                }}
                disabled={!pendingDisposition || !reasonReady || mutation.isPending}
              >
                <Check />
                Record disposition
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setDispositioning(false);
                  setPendingDisposition(null);
                  mutation.reset();
                }}
              >
                <X />
                Cancel
              </Button>
              {!reasonReady ? (
                <span className="text-xs text-muted-foreground">
                  A written reason is mandatory — the API rejects an override without one.
                </span>
              ) : null}
              {mutation.isError ? (
                <span className="text-xs text-destructive">
                  {mutationMessage(mutation.error, "The disposition failed.")}
                </span>
              ) : null}
            </div>
          </div>
        ) : (
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setPendingDisposition("acknowledged");
                setDispositioning(true);
              }}
            >
              Acknowledge…
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setPendingDisposition("dismissed");
                setDispositioning(true);
              }}
            >
              Dismiss…
            </Button>
            <span className="text-xs text-muted-foreground">
              An annotation only — it never changes the severity or the invoice status.
            </span>
          </div>
        )
      ) : null}
    </li>
  );
}
