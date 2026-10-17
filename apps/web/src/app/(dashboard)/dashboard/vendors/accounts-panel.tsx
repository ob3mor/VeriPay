"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, CheckCheck, Landmark, Plus, ShieldX } from "lucide-react";

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
  createBankAccount,
  listBankAccounts,
  listDocuments,
  rejectBankAccount,
  revokeBankAccount,
  verifyBankAccount,
} from "@/lib/api";
import { bankAccountStatusPresentation } from "@/lib/status";
import type {
  BankAccountListItem,
  BankAccountVerificationMethod,
} from "@veripay/api-contracts";
import { isBankAccountDetail } from "@veripay/api-contracts";

import { fieldError, formatDate, mutationMessage } from "./screen-helpers";

export interface AccountsPanelProps {
  vendorId: string;
}

const METHOD_LABELS: Record<BankAccountVerificationMethod, string> = {
  callback_to_known_contact: "Callback to a known contact",
  written_confirmation: "Written confirmation",
  registry_check: "Registry check",
};

const METHOD_OPTIONS = Object.keys(METHOD_LABELS) as BankAccountVerificationMethod[];

/**
 * Trusted bank accounts (R5). Every action on this panel is human-only and
 * audited server-side:
 * - Register (contributor roles): ALWAYS creates a pending account; the full
 *   account number exists only in this request (fingerprinted server-side,
 *   never stored or shown again).
 * - Verify (reviewer/org_admin): requires a method AND a reference or a
 *   supporting document — the exact independent-verification record of R5;
 *   there is no automatic path anywhere and an invoice can never approve an
 *   account.
 * - Reject (pending) / Revoke (pending or approved) — reviewer/org_admin.
 */
export function AccountsPanel({ vendorId }: AccountsPanelProps) {
  const me = useMe();
  const role = me.data?.user.role;
  const canVerify = role === "org_admin" || role === "reviewer";
  const canContribute = canVerify || role === "finance_officer";

  const accountsQuery = useQuery({
    queryKey: ["accounts", vendorId],
    queryFn: async () => (await listBankAccounts(vendorId)).items,
  });

  const [registerOpen, setRegisterOpen] = useState(false);
  const [verifyTarget, setVerifyTarget] = useState<BankAccountListItem | null>(null);
  const [rejectTarget, setRejectTarget] = useState<BankAccountListItem | null>(null);
  const [revokeTarget, setRevokeTarget] = useState<BankAccountListItem | null>(null);

  const accounts = [...(accountsQuery.data ?? [])].sort(
    (a, b) => Number(b.is_current) - Number(a.is_current)
  );

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex flex-wrap items-center justify-between gap-2 text-base">
          <span className="flex items-center gap-2">
            <Landmark className="h-4 w-4 text-muted-foreground" />
            Trusted bank accounts
          </span>
          {canContribute ? (
            <Button variant="outline" size="sm" onClick={() => setRegisterOpen(true)}>
              <Plus />
              Register account…
            </Button>
          ) : null}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {accountsQuery.isError ? (
          <ErrorState
            error={accountsQuery.error}
            title="Could not load bank accounts"
            onRetry={() => void accountsQuery.refetch()}
          />
        ) : accountsQuery.isPending ? (
          <div className="h-24 animate-pulse rounded bg-muted" role="status" aria-label="Loading accounts" />
        ) : accounts.length === 0 ? (
          <EmptyState
            icon={Landmark}
            title="No bank accounts on file"
            description="Register the vendor's pay-to account. It stays pending — flagged for human verification — until a reviewer independently verifies it."
          />
        ) : (
          <ul className="space-y-3">
            {accounts.map((account) => (
              <AccountRow
                key={account.id}
                account={account}
                canVerify={canVerify}
                onVerify={() => setVerifyTarget(account)}
                onReject={() => setRejectTarget(account)}
                onRevoke={() => setRevokeTarget(account)}
              />
            ))}
          </ul>
        )}

        <p className="text-xs text-muted-foreground">
          Full account numbers and fingerprints are never displayed — the API
          only returns the last four digits (docs/API.md §5.8). Verification
          provenance (method/reference) is visible to reviewer and admin roles
          only.
        </p>

        <RegisterAccountDialog
          vendorId={vendorId}
          open={registerOpen}
          onClose={() => setRegisterOpen(false)}
        />
        <VerifyAccountDialog
          vendorId={vendorId}
          account={verifyTarget}
          onClose={() => setVerifyTarget(null)}
        />
        <RejectAccountDialog
          vendorId={vendorId}
          account={rejectTarget}
          onClose={() => setRejectTarget(null)}
        />
        <RevokeAccountDialog
          vendorId={vendorId}
          account={revokeTarget}
          onClose={() => setRevokeTarget(null)}
        />
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Row
// ---------------------------------------------------------------------------

function AccountRow({
  account,
  canVerify,
  onVerify,
  onReject,
  onRevoke,
}: {
  account: BankAccountListItem;
  canVerify: boolean;
  onVerify: () => void;
  onReject: () => void;
  onRevoke: () => void;
}) {
  const detail = isBankAccountDetail(account) ? account : null;
  const status = bankAccountStatusPresentation(account.status);

  return (
    <li className="rounded-md border p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-medium">
            {account.account_holder_name}
            {account.is_current ? (
              <span className="ml-2 rounded-full border border-primary/20 bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
                Current on file
              </span>
            ) : null}
          </p>
          <p className="mt-0.5 text-sm text-muted-foreground">
            {account.bank_name ?? "Bank not recorded"}
            {account.bank_country ? ` (${account.bank_country})` : ""} · Account{" "}
            <span className="font-mono">
              {account.account_number_last4 ? `•••• ${account.account_number_last4}` : "—"}
            </span>
          </p>
          {detail ? (
            <p className="mt-1 text-xs text-muted-foreground">
              {detail.status === "approved" && detail.verification_method ? (
                <>
                  Verified {formatDate(detail.verified_at)} — method:{" "}
                  {METHOD_LABELS[detail.verification_method as BankAccountVerificationMethod] ??
                    detail.verification_method}
                  {detail.verification_reference ? ` · ref: ${detail.verification_reference}` : ""}
                  {detail.verification_document_id ? " · with supporting document" : ""}
                </>
              ) : detail.status === "rejected" ? (
                <>Rejected{detail.verification_reference ? ` — ${detail.verification_reference}` : ""}</>
              ) : null}
            </p>
          ) : null}
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <StatusBadge presentation={status} />
          {canVerify && account.status === "pending" ? (
            <>
              <Button size="sm" onClick={onVerify}>
                <CheckCheck />
                Verify…
              </Button>
              <Button variant="outline" size="sm" onClick={onReject}>
                <ShieldX />
                Reject…
              </Button>
            </>
          ) : null}
          {canVerify && (account.status === "approved" || account.status === "pending") ? (
            <Button variant="ghost" size="sm" onClick={onRevoke}>
              <Ban />
              Revoke…
            </Button>
          ) : null}
        </div>
      </div>
    </li>
  );
}

// ---------------------------------------------------------------------------
// Register (creates a PENDING account — R5)
// ---------------------------------------------------------------------------

function RegisterAccountDialog({
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
  const [makeCurrent, setMakeCurrent] = useState(true);
  const [localError, setLocalError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      createBankAccount(vendorId, {
        account_holder_name: holder.trim(),
        account_number: accountNumber.trim(),
        bank_name: bankName.trim() ? bankName.trim() : null,
        bank_country: country.trim() ? country.trim().toUpperCase() : null,
        make_current: makeCurrent,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["accounts", vendorId] });
      onClose();
    },
  });

  const submit = () => {
    setLocalError(null);
    if (holder.trim().length === 0) {
      setLocalError("The account holder name is required.");
      return;
    }
    if (accountNumber.trim().length < 4) {
      setLocalError("Enter the full account number or IBAN (at least 4 characters).");
      return;
    }
    if (country.trim() && country.trim().length !== 2) {
      setLocalError("Country must be a 2-letter ISO code (e.g. DE).");
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
    setMakeCurrent(true);
    onClose();
  };

  return (
    <FormDialog
      open={open}
      title="Register bank account"
      description={
        <>
          The account is registered as <strong>pending</strong>. A reviewer must
          independently verify it — with a method and a reference or supporting
          document — before it can be trusted for pay-to comparisons (R5). The
          full number is sent once for fingerprinting and is never stored,
          logged, or displayed again.
        </>
      }
      confirmLabel="Register pending account"
      busy={mutation.isPending}
      onConfirm={submit}
      onCancel={close}
    >
      <div className="space-y-1.5">
        <Label htmlFor="account-holder">Account holder *</Label>
        <Input
          id="account-holder"
          value={holder}
          onChange={(event) => setHolder(event.target.value)}
          autoComplete="off"
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="account-number">Account number / IBAN *</Label>
        <Input
          id="account-number"
          value={accountNumber}
          onChange={(event) => setAccountNumber(event.target.value)}
          autoComplete="off"
          spellCheck={false}
        />
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="account-bank">Bank name</Label>
          <Input
            id="account-bank"
            value={bankName}
            onChange={(event) => setBankName(event.target.value)}
            autoComplete="off"
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="account-country">Country (ISO 2-letter)</Label>
          <Input
            id="account-country"
            value={country}
            onChange={(event) => setCountry(event.target.value)}
            placeholder="DE"
            maxLength={2}
            autoComplete="off"
          />
        </div>
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={makeCurrent}
          onChange={(event) => setMakeCurrent(event.target.checked)}
          className="h-4 w-4 rounded border-input"
        />
        Make this the vendor&apos;s current on-file account
      </label>
      {localError ? <p className="text-sm text-destructive">{localError}</p> : null}
      {mutation.isError ? (
        <p className="text-sm text-destructive">
          {mutationMessage(mutation.error, "The account could not be registered.")}
        </p>
      ) : null}
    </FormDialog>
  );
}

// ---------------------------------------------------------------------------
// Verify (THE R5 human step)
// ---------------------------------------------------------------------------

function VerifyAccountDialog({
  vendorId,
  account,
  onClose,
}: {
  vendorId: string;
  account: BankAccountListItem | null;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const open = account !== null;
  const [method, setMethod] = useState<BankAccountVerificationMethod | "">("");
  const [reference, setReference] = useState("");
  const [documentId, setDocumentId] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);

  // Supporting documents uploaded in this vendor's context (bank letters,
  // statements) — the R5 verification document picker.
  const documentsQuery = useQuery({
    queryKey: ["documents"],
    queryFn: async () => (await listDocuments({ limit: 100 })).items,
    enabled: open,
  });
  const vendorDocuments = (documentsQuery.data ?? []).filter(
    (doc) => doc.vendor_id === vendorId
  );

  const mutation = useMutation({
    mutationFn: () =>
      verifyBankAccount(vendorId, (account as BankAccountListItem).id, {
        verification_method: method as BankAccountVerificationMethod,
        verification_reference: reference.trim() ? reference.trim() : null,
        verification_document_id: documentId ? documentId : null,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["accounts", vendorId] });
      close();
    },
  });

  const submit = () => {
    setLocalError(null);
    if (!method) {
      setLocalError("Choose the verification method.");
      return;
    }
    if (!reference.trim() && !documentId) {
      setLocalError(
        "An independent verification record is required: enter a reference (who/when/what, e.g. a ticket id) or attach the supporting document."
      );
      return;
    }
    mutation.mutate();
  };

  const close = () => {
    mutation.reset();
    setLocalError(null);
    setMethod("");
    setReference("");
    setDocumentId("");
    onClose();
  };

  const holder = account?.account_holder_name ?? "";
  const last4 = account?.account_number_last4 ? `•••• ${account.account_number_last4}` : "";

  return (
    <FormDialog
      open={open}
      title="Verify bank account"
      description={
        <>
          Approving <span className="font-medium">{holder}</span>{" "}
          {last4 ? <span className="font-mono">{last4}</span> : null} records{" "}
          <strong>your independent verification</strong> — the method and a
          reference or supporting document are mandatory and audited. Nothing in
          VeriPay verifies an account automatically, and no invoice or
          assessment can ever approve one (R5). This authorizes nothing: it
          marks the account as the human-checked pay-to record.
        </>
      }
      confirmLabel="Record verification"
      busy={mutation.isPending}
      onConfirm={submit}
      onCancel={close}
    >
      <div className="space-y-1.5">
        <Label htmlFor="verify-method">Verification method *</Label>
        <select
          id="verify-method"
          value={method}
          onChange={(event) => setMethod(event.target.value as BankAccountVerificationMethod)}
          className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        >
          <option value="" disabled>
            Choose the method…
          </option>
          {METHOD_OPTIONS.map((value) => (
            <option key={value} value={value}>
              {METHOD_LABELS[value]}
            </option>
          ))}
        </select>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="verify-reference">Verification reference</Label>
        <Input
          id="verify-reference"
          value={reference}
          onChange={(event) => setReference(event.target.value)}
          placeholder="Who / when / what — e.g. ticket INC-2041, call with signatory"
          autoComplete="off"
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="verify-document">…or supporting document</Label>
        <select
          id="verify-document"
          value={documentId}
          onChange={(event) => setDocumentId(event.target.value)}
          className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        >
          <option value="">
            {documentsQuery.isPending
              ? "Loading documents…"
              : vendorDocuments.length === 0
                ? "No documents uploaded in this vendor's context"
                : "None — I entered a reference above"}
          </option>
          {vendorDocuments.map((doc) => (
            <option key={doc.id} value={doc.id}>
              {doc.file_name} ({doc.kind})
            </option>
          ))}
        </select>
        <p className="text-xs text-muted-foreground">
          Bank letters or statements must be uploaded in the vendor&apos;s context
          from the Invoices screen first; they appear here. Either a reference
          or a document is required — both together are even better.
        </p>
      </div>
      {localError ? <p className="text-sm text-destructive">{localError}</p> : null}
      {mutation.isError ? (
        <p className="text-sm text-destructive">
          {mutationMessage(mutation.error, "The verification could not be recorded.")}
          {fieldError(mutation.error, "verification_method")
            ? ` (${fieldError(mutation.error, "verification_method")})`
            : ""}
        </p>
      ) : null}
    </FormDialog>
  );
}

// ---------------------------------------------------------------------------
// Reject (pending only) / Revoke (pending or approved)
// ---------------------------------------------------------------------------

function RejectAccountDialog({
  vendorId,
  account,
  onClose,
}: {
  vendorId: string;
  account: BankAccountListItem | null;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const open = account !== null;
  const [note, setNote] = useState("");

  const mutation = useMutation({
    mutationFn: () =>
      rejectBankAccount(vendorId, (account as BankAccountListItem).id, {
        resolution_note: note.trim() ? note.trim() : null,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["accounts", vendorId] });
      close();
    },
  });

  const close = () => {
    mutation.reset();
    setNote("");
    onClose();
  };

  return (
    <FormDialog
      open={open}
      title="Reject bank account"
      description={
        <>
          Marks this pending account as <strong>rejected</strong> with your
          note. Rejection is a human decision and is audited; the account can no
          longer pass pay-to verification.
        </>
      }
      confirmLabel="Reject account"
      destructive
      busy={mutation.isPending}
      onConfirm={() => mutation.mutate()}
      onCancel={close}
    >
      <div className="space-y-1.5">
        <Label htmlFor="reject-note">Reason / note</Label>
        <textarea
          id="reject-note"
          value={note}
          onChange={(event) => setNote(event.target.value)}
          rows={3}
          placeholder="Why this account is rejected (recorded with the decision)."
          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        />
      </div>
      {mutation.isError ? (
        <p className="text-sm text-destructive">
          {mutationMessage(mutation.error, "The rejection could not be recorded.")}
        </p>
      ) : null}
    </FormDialog>
  );
}

function RevokeAccountDialog({
  vendorId,
  account,
  onClose,
}: {
  vendorId: string;
  account: BankAccountListItem | null;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const open = account !== null;

  const mutation = useMutation({
    mutationFn: () => revokeBankAccount(vendorId, (account as BankAccountListItem).id, {}),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["accounts", vendorId] });
      close();
    },
  });

  const close = () => {
    mutation.reset();
    onClose();
  };

  return (
    <FormDialog
      open={open}
      title="Revoke bank account"
      description={
        <>
          Revocation marks the account <strong>revoked</strong> and clears it as
          the vendor&apos;s current on-file account. Invoices paid to this
          destination from now on will be flagged for human review — revocation
          never un-flags past findings. This is a human decision and is audited.
        </>
      }
      confirmLabel="Revoke account"
      destructive
      busy={mutation.isPending}
      onConfirm={() => mutation.mutate()}
      onCancel={close}
    >
      {mutation.isError ? (
        <p className="text-sm text-destructive">
          {mutationMessage(mutation.error, "The revocation could not be recorded.")}
        </p>
      ) : null}
    </FormDialog>
  );
}
