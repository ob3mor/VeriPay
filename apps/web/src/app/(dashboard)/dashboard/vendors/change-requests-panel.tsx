"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeftRight, CheckCheck, Plus, ShieldX } from "lucide-react";

import { FormDialog } from "@/components/form-dialog";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useMe } from "@/hooks/use-session";
import {
  approveChangeRequest,
  createChangeRequest,
  listChangeRequests,
  rejectChangeRequest,
} from "@/lib/api";
import { changeRequestStatusPresentation } from "@/lib/status";
import type { ChangeRequestOut } from "@veripay/api-contracts";

import { fieldError, mutationMessage } from "./screen-helpers";

export interface ChangeRequestsPanelProps {
  vendorId: string;
}

/**
 * Bank-account change requests (R5 change control): a finance user proposes a
 * new pay-to account with a reason; a reviewer approves or rejects. On
 * approval the SERVICE creates the new account already verified, stamped with
 * the deciding human — the decision IS the independent verification record.
 * Nothing automatic touches this flow, and no invoice can approve a change.
 */
export function ChangeRequestsPanel({ vendorId }: ChangeRequestsPanelProps) {
  const me = useMe();
  const role = me.data?.user.role;
  const canVerify = role === "org_admin" || role === "reviewer";
  const canContribute = canVerify || role === "finance_officer";

  const requestsQuery = useQuery({
    queryKey: ["change-requests", vendorId],
    queryFn: () => listChangeRequests(vendorId),
  });

  const [createOpen, setCreateOpen] = useState(false);
  const [approveTarget, setApproveTarget] = useState<ChangeRequestOut | null>(null);
  const [rejectTarget, setRejectTarget] = useState<ChangeRequestOut | null>(null);

  const requests = requestsQuery.data ?? [];

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex flex-wrap items-center justify-between gap-2 text-base">
          <span className="flex items-center gap-2">
            <ArrowLeftRight className="h-4 w-4 text-muted-foreground" />
            Bank-account change requests
          </span>
          {canContribute ? (
            <Button variant="outline" size="sm" onClick={() => setCreateOpen(true)}>
              <Plus />
              Request change…
            </Button>
          ) : null}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {requestsQuery.isError ? (
          <ErrorState
            error={requestsQuery.error}
            title="Could not load change requests"
            onRetry={() => void requestsQuery.refetch()}
          />
        ) : requestsQuery.isPending ? (
          <div className="h-16 animate-pulse rounded bg-muted" role="status" aria-label="Loading change requests" />
        ) : requests.length === 0 ? (
          <EmptyState
            icon={ArrowLeftRight}
            title="No change requests"
            description="When a vendor's pay-to details change, request the change here with a reason. A reviewer decides — approval creates the verified account, rejection closes the request; both are audited."
          />
        ) : (
          <ul className="space-y-3">
            {requests.map((request) => (
              <RequestRow
                key={request.id}
                request={request}
                canVerify={canVerify}
                onApprove={() => setApproveTarget(request)}
                onReject={() => setRejectTarget(request)}
              />
            ))}
          </ul>
        )}

        <CreateRequestDialog
          vendorId={vendorId}
          open={createOpen}
          onClose={() => setCreateOpen(false)}
        />
        <DecisionDialog
          vendorId={vendorId}
          request={approveTarget}
          decision="approve"
          onClose={() => setApproveTarget(null)}
        />
        <DecisionDialog
          vendorId={vendorId}
          request={rejectTarget}
          decision="reject"
          onClose={() => setRejectTarget(null)}
        />
      </CardContent>
    </Card>
  );
}

function RequestRow({
  request,
  canVerify,
  onApprove,
  onReject,
}: {
  request: ChangeRequestOut;
  canVerify: boolean;
  onApprove: () => void;
  onReject: () => void;
}) {
  const status = changeRequestStatusPresentation(request.status);
  return (
    <li className="rounded-md border p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-medium">
            {request.proposed_holder_name}{" "}
            {request.proposed_account_last4 ? (
              <span className="font-mono text-xs">•••• {request.proposed_account_last4}</span>
            ) : null}
          </p>
          <p className="text-sm text-muted-foreground">
            {request.proposed_bank_name ?? "Bank not recorded"}
            {request.proposed_bank_country ? ` (${request.proposed_bank_country})` : ""}
          </p>
          <p className="mt-1 break-words text-sm text-foreground/90">
            <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Reason:{" "}
            </span>
            {request.reason}
          </p>
          {request.resolution_note ? (
            <p className="mt-1 break-words text-xs text-muted-foreground">
              Decision note: {request.resolution_note}
            </p>
          ) : null}
          <p className="mt-1 font-mono text-xs text-muted-foreground">
            requested by {request.requested_by.slice(0, 8)}
            {request.reviewed_by ? ` · decided by ${request.reviewed_by.slice(0, 8)}` : ""}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <StatusBadge presentation={status} />
          {canVerify && request.status === "pending" ? (
            <>
              <Button size="sm" onClick={onApprove}>
                <CheckCheck />
                Approve…
              </Button>
              <Button variant="outline" size="sm" onClick={onReject}>
                <ShieldX />
                Reject…
              </Button>
            </>
          ) : null}
        </div>
      </div>
    </li>
  );
}

function CreateRequestDialog({
  vendorId,
  open,
  onClose,
}: {
  vendorId: string;
  open: boolean;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [holder, setHolder] = useState("");
  const [accountNumber, setAccountNumber] = useState("");
  const [bankName, setBankName] = useState("");
  const [country, setCountry] = useState("");
  const [reason, setReason] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      createChangeRequest(vendorId, {
        account_holder_name: holder.trim(),
        account_number: accountNumber.trim(),
        bank_name: bankName.trim() ? bankName.trim() : null,
        bank_country: country.trim() ? country.trim().toUpperCase() : null,
        reason: reason.trim(),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["change-requests", vendorId] });
      close();
    },
  });

  const submit = () => {
    setLocalError(null);
    if (holder.trim().length === 0) {
      setLocalError("The proposed account holder name is required.");
      return;
    }
    if (accountNumber.trim().length < 4) {
      setLocalError("Enter the proposed account number or IBAN (at least 4 characters).");
      return;
    }
    if (reason.trim().length === 0) {
      setLocalError("A reason is required — reviewers decide on the strength of it.");
      return;
    }
    mutation.mutate();
  };

  const close = () => {
    mutation.reset();
    setLocalError(null);
    setHolder("");
    setAccountNumber("");
    setBankName("");
    setCountry("");
    setReason("");
    onClose();
  };

  return (
    <FormDialog
      open={open}
      title="Request bank-account change"
      description="Proposes a new pay-to account for this vendor. The request stays pending until a reviewer decides; the proposed account number is fingerprinted and never stored or displayed in full."
      confirmLabel="Submit request"
      busy={mutation.isPending}
      onConfirm={submit}
      onCancel={close}
    >
      <div className="space-y-1.5">
        <Label htmlFor="cr-holder">Proposed account holder *</Label>
        <Input id="cr-holder" value={holder} onChange={(event) => setHolder(event.target.value)} autoComplete="off" />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="cr-number">Proposed account number / IBAN *</Label>
        <Input
          id="cr-number"
          value={accountNumber}
          onChange={(event) => setAccountNumber(event.target.value)}
          autoComplete="off"
          spellCheck={false}
        />
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="cr-bank">Bank name</Label>
          <Input id="cr-bank" value={bankName} onChange={(event) => setBankName(event.target.value)} autoComplete="off" />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="cr-country">Country (ISO 2-letter)</Label>
          <Input
            id="cr-country"
            value={country}
            onChange={(event) => setCountry(event.target.value)}
            placeholder="DE"
            maxLength={2}
            autoComplete="off"
          />
        </div>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="cr-reason">Reason *</Label>
        <textarea
          id="cr-reason"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          rows={3}
          placeholder="Why the pay-to account is changing — bank letter reference, contract change, etc."
          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        />
      </div>
      {localError ? <p className="text-sm text-destructive">{localError}</p> : null}
      {mutation.isError ? (
        <p className="text-sm text-destructive">
          {mutationMessage(mutation.error, "The change request could not be submitted.")}
          {fieldError(mutation.error, "reason") ? ` (${fieldError(mutation.error, "reason")})` : ""}
        </p>
      ) : null}
    </FormDialog>
  );
}

function DecisionDialog({
  vendorId,
  request,
  decision,
  onClose,
}: {
  vendorId: string;
  request: ChangeRequestOut | null;
  decision: "approve" | "reject";
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const open = request !== null;
  const [note, setNote] = useState("");

  const mutation = useMutation({
    mutationFn: () => {
      const body = { resolution_note: note.trim() ? note.trim() : null };
      return decision === "approve"
        ? approveChangeRequest(vendorId, (request as ChangeRequestOut).id, body)
        : rejectChangeRequest(vendorId, (request as ChangeRequestOut).id, body);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["change-requests", vendorId] });
      void queryClient.invalidateQueries({ queryKey: ["accounts", vendorId] });
      close();
    },
  });

  const close = () => {
    mutation.reset();
    setNote("");
    onClose();
  };

  const approve = decision === "approve";

  return (
    <FormDialog
      open={open}
      title={approve ? "Approve change request" : "Reject change request"}
      description={
        approve ? (
          <>
            Approval creates the proposed account <strong>already verified</strong>,
            stamped with you as the deciding human — your decision is the
            independent verification record (R5). It authorizes no payment; it
            establishes the human-checked pay-to record.
          </>
        ) : (
          <>
            Rejection closes this request. The vendor&apos;s on-file accounts are
            unchanged, and the decision is recorded for the audit trail.
          </>
        )
      }
      confirmLabel={approve ? "Approve and create verified account" : "Reject request"}
      destructive={!approve}
      busy={mutation.isPending}
      onConfirm={() => mutation.mutate()}
      onCancel={close}
    >
      <div className="space-y-1.5">
        <Label htmlFor="cr-decision-note">Decision note</Label>
        <textarea
          id="cr-decision-note"
          value={note}
          onChange={(event) => setNote(event.target.value)}
          rows={3}
          placeholder="Optional note recorded with the decision."
          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        />
      </div>
      {mutation.isError ? (
        <p className="text-sm text-destructive">
          {mutationMessage(mutation.error, "The decision could not be recorded.")}
        </p>
      ) : null}
    </FormDialog>
  );
}
