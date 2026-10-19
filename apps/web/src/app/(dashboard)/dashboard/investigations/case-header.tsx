"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ClipboardCheck, UserPlus } from "lucide-react";

import { FormDialog } from "@/components/form-dialog";
import { SeverityBadge } from "@/components/severity-badge";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { ApiError, assignCase, closeCase } from "@/lib/api";
import { caseOutcomePresentation, caseStatusPresentation } from "@/lib/status";
import type { CaseCloseIn, CaseOutcome, CaseOut } from "@veripay/api-contracts";

import { mutationMessage } from "./api-extras";

export interface CaseHeaderProps {
  caseData: CaseOut;
  canVerify: boolean;
  canContribute: boolean;
  currentUserId: string | null;
}

/**
 * Case identity + the two human workflow actions (R6):
 * - "Assign to me" (contributor roles) — the API has no users-list endpoint,
 *   so the only assignment the UI can offer honestly is self-assignment.
 * - "Close case" (reviewer/org_admin) — outcome + resolution summary are
 *   mandatory (422 without them; nothing auto-closes a case).
 */
export function CaseHeader({ caseData, canVerify, canContribute, currentUserId }: CaseHeaderProps) {
  const queryClient = useQueryClient();
  const [closeOpen, setCloseOpen] = useState(false);

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["case", caseData.id] });
    void queryClient.invalidateQueries({ queryKey: ["cases"] });
    void queryClient.invalidateQueries({ queryKey: ["actions", caseData.id] });
  };

  const assignMutation = useMutation({
    mutationFn: () => assignCase(caseData.id, { user_id: currentUserId as string }),
    onSuccess: invalidate,
  });

  const closed = caseData.status === "closed";
  const assignedToMe = caseData.assigned_to !== null && caseData.assigned_to === currentUserId;

  return (
    <Card className="p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="font-mono text-xs text-muted-foreground">{caseData.case_number}</p>
          <h2 className="mt-1 break-words text-xl font-semibold">{caseData.title}</h2>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <SeverityBadge severity={caseData.severity} />
            <StatusBadge presentation={caseStatusPresentation(caseData.status)} />
            {caseData.outcome ? (
              <StatusBadge
                presentation={caseOutcomePresentation(String(caseData.outcome))}
                hideDot
              />
            ) : null}
            <span className="text-xs text-muted-foreground">
              {assignedToMe
                ? "Assigned to you"
                : caseData.assigned_to
                  ? "Assigned to another member"
                  : "Unassigned"}
            </span>
          </div>
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {canContribute && !closed && !assignedToMe && currentUserId ? (
            <Button
              variant="outline"
              size="sm"
              onClick={() => assignMutation.mutate()}
              disabled={assignMutation.isPending}
            >
              <UserPlus />
              Assign to me
            </Button>
          ) : null}
          {canVerify && !closed ? (
            <Button size="sm" onClick={() => setCloseOpen(true)}>
              <ClipboardCheck />
              Close case…
            </Button>
          ) : null}
        </div>
      </div>

      {assignMutation.isError ? (
        <p className="mt-3 text-sm text-destructive">
          {mutationMessage(assignMutation.error, "Could not assign this case.")}
        </p>
      ) : null}

      <CloseCaseDialog
        open={closeOpen}
        caseData={caseData}
        onClose={() => setCloseOpen(false)}
        onClosed={() => {
          setCloseOpen(false);
          invalidate();
        }}
      />
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Close dialog (R6: outcome + resolution summary, human-only)
// ---------------------------------------------------------------------------

const OUTCOME_OPTIONS: CaseOutcome[] = [
  "fraud_confirmed",
  "policy_violation",
  "false_positive",
  "no_critical_findings",
  "inconclusive",
];

function CloseCaseDialog({
  open,
  caseData,
  onClose,
  onClosed,
}: {
  open: boolean;
  caseData: CaseOut;
  onClose: () => void;
  onClosed: () => void;
}) {
  const [outcome, setOutcome] = useState<CaseOutcome | "">("");
  const [summary, setSummary] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: (input: CaseCloseIn) => closeCase(caseData.id, input),
    onSuccess: onClosed,
  });

  const submit = () => {
    setLocalError(null);
    if (!outcome) {
      setLocalError("Choose an outcome — a case cannot close without one.");
      return;
    }
    if (summary.trim().length === 0) {
      setLocalError("Write a resolution summary — a case cannot close without one.");
      return;
    }
    mutation.mutate({ outcome, resolution_summary: summary.trim() });
  };

  const reset = () => {
    setOutcome("");
    setSummary("");
    setLocalError(null);
    mutation.reset();
  };

  const handleError = (which: "outcome" | "summary"): string | null => {
    if (!open) return null;
    if (localError) return localError;
    if (mutation.isError && mutation.error instanceof ApiError) {
      const match = (mutation.error.details ?? []).find((detail) => detail.field === which);
      return match?.message ?? null;
    }
    return null;
  };

  return (
    <FormDialog
      open={open}
      title={`Close ${caseData.case_number}`}
      description={
        <>
          Closing records a <strong>human</strong> outcome and resolution summary. It never
          authorizes a payment and never claims the invoice is genuine — even{" "}
          <em>no critical findings</em> is a case disposition, not a genuineness verdict (R2/R6).
        </>
      }
      confirmLabel="Record outcome and close"
      busy={mutation.isPending}
      onConfirm={submit}
      onCancel={() => {
        reset();
        onClose();
      }}
    >
      <div className="space-y-1.5">
        <Label htmlFor="close-outcome">Outcome</Label>
        <select
          id="close-outcome"
          value={outcome}
          onChange={(event) => setOutcome(event.target.value as CaseOutcome)}
          className="flex h-10 w-full rounded-md border border-input bg-background/60 px-3 py-2 text-sm focus-visible:outline-none focus-visible:border-primary/50 focus-visible:ring-2 focus-visible:ring-ring/60 focus-visible:ring-offset-1 focus-visible:ring-offset-card"
        >
          <option value="" disabled>
            Choose an outcome…
          </option>
          {OUTCOME_OPTIONS.map((value) => (
            <option key={value} value={value}>
              {caseOutcomePresentation(value).label}
            </option>
          ))}
        </select>
        {handleError("outcome") ? (
          <p className="text-xs text-destructive">{handleError("outcome")}</p>
        ) : null}
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="close-summary">Resolution summary</Label>
        <textarea
          id="close-summary"
          value={summary}
          onChange={(event) => setSummary(event.target.value)}
          rows={5}
          placeholder="What was reviewed, what was decided, and why — this is the audit record of the human decision."
          className="w-full rounded-md border border-input bg-background/60 px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:border-primary/50 focus-visible:ring-2 focus-visible:ring-ring/60 focus-visible:ring-offset-1 focus-visible:ring-offset-card"
        />
        {handleError("summary") ? (
          <p className="text-xs text-destructive">{handleError("summary")}</p>
        ) : null}
      </div>
      {mutation.isError && !localError ? (
        <p className="text-sm text-destructive">
          {mutationMessage(mutation.error, "The API rejected this close request.")}
        </p>
      ) : null}
    </FormDialog>
  );
}
