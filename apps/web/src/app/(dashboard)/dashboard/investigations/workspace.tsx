"use client";

import { useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { ShieldAlert } from "lucide-react";

import { FormDialog } from "@/components/form-dialog";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { SkeletonList } from "@/components/skeleton";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { useMe } from "@/hooks/use-session";
import {
  assessInvoice,
  getCase,
  getInvoice,
  getLatestAssessment,
  listCases,
  listDocuments,
  listExtractionFields,
  openCase,
} from "@/lib/api";
import type { CaseSeverity, InvoiceOut } from "@veripay/api-contracts";

import { mutationMessage } from "./api-extras";
import { ActionsFeed } from "./actions-feed";
import { CaseHeader } from "./case-header";
import { CaseList } from "./case-list";
import { DocumentPreview } from "./document-preview";
import { EvidencePanel } from "./evidence-panel";
import { FieldsPanel } from "./fields-panel";
import { FindingsPanel } from "./findings-panel";
import { MatchesPanel } from "./matches-panel";
import { PoPanel } from "./po-panel";
import { VendorPanel } from "./vendor-panel";

/**
 * Investigations workspace (Prompt 05, wired to the completed backend).
 *
 * Route state lives in the URL so a workspace view is shareable:
 *   /dashboard/investigations                 → case list
 *   /dashboard/investigations?case=<id>       → case workspace (split screen)
 *   /dashboard/investigations?invoice=<id>    → case-less invoice workspace
 *   …&doc=<documentId>                        → explicit source-document choice
 *
 * The detail is split-screen: LEFT the source document with page navigation,
 * RIGHT the extracted fields (R3 review), vendor + trusted bank-account
 * comparison, PO comparison, the evidence trail (GET /invoices/{id}/evidence),
 * risk findings with dispositions (reason mandatory — the API 422s otherwise),
 * evidence matches and the review-actions feed. Every panel degrades
 * gracefully when the API is offline (ErrorState) — the static page never
 * crashes.
 *
 * The case-less invoice view (reached from the Invoices screen) shows the same
 * panels minus the case-only ones (assign/close/actions). reviewer/org_admin
 * can open an investigation case for the invoice there — POST /cases (R6
 * provenance: critical assessments auto-open their own).
 *
 * Known API-shape constraint (stated honestly in the UI): `InvoiceOut` does
 * not serialize `source_document_id`, so the source document is located by
 * matching the extracted `invoice_number` field across the org's invoice-kind
 * documents, or chosen explicitly by the investigator (persisted as `&doc=`).
 */
export function InvestigationsWorkspace() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const caseId = searchParams.get("case") ?? "";
  const invoiceParam = searchParams.get("invoice");
  const docParam = searchParams.get("doc");

  const openCaseWorkspace = (id: string) =>
    router.push(`/dashboard/investigations?case=${encodeURIComponent(id)}`);

  if (caseId) {
    return (
      <CaseWorkspace
        caseId={caseId}
        docParam={docParam}
        onBack={() => router.push("/dashboard/investigations")}
        onSelectDocument={(docId) =>
          router.replace(
            `/dashboard/investigations?case=${encodeURIComponent(caseId)}&doc=${encodeURIComponent(docId)}`,
            { scroll: false }
          )
        }
      />
    );
  }
  if (invoiceParam) {
    return (
      <InvoiceWorkspace
        invoiceId={invoiceParam}
        docParam={docParam}
        onBack={() => router.push("/dashboard/investigations")}
        onSelectDocument={(docId) =>
          router.replace(
            `/dashboard/investigations?invoice=${encodeURIComponent(invoiceParam)}&doc=${encodeURIComponent(docId)}`,
            { scroll: false }
          )
        }
        onCaseOpened={openCaseWorkspace}
      />
    );
  }
  return <CaseListSection onOpen={openCaseWorkspace} />;
}

// ---------------------------------------------------------------------------
// Case list
// ---------------------------------------------------------------------------

function CaseListSection({ onOpen }: { onOpen: (caseId: string) => void }) {
  const casesQuery = useQuery({
    queryKey: ["cases"],
    queryFn: async () => (await listCases({ limit: 100 })).items,
  });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Investigations"
        description="Human review of flagged inconsistencies. Every case is a decision-support workspace — VeriPay never closes a case automatically and never claims an invoice is genuine (R2/R6)."
      />
      <CaseList
        cases={casesQuery.data}
        pending={casesQuery.isPending}
        error={casesQuery.error}
        onRetry={() => void casesQuery.refetch()}
        onOpen={onOpen}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Source-document identification (shared by both workspace modes)
// ---------------------------------------------------------------------------

/**
 * InvoiceOut does not carry source_document_id, so: list the org's documents,
 * fetch fields for invoice-kind ones (cached), and auto-match on the extracted
 * invoice number. An explicit `&doc=` choice always wins.
 */
function useSourceDocument(invoice: InvoiceOut | null, docParam: string | null) {
  const documentsQuery = useQuery({
    queryKey: ["documents"],
    queryFn: async () => (await listDocuments({ limit: 100 })).items,
    enabled: invoice !== null,
  });

  const candidateDocuments = useMemo(
    () => (documentsQuery.data ?? []).filter((doc) => doc.kind === "invoice"),
    [documentsQuery.data]
  );

  const candidateFields = useQueries({
    queries: candidateDocuments.map((doc) => ({
      queryKey: ["fields", doc.id],
      queryFn: async () => (await listExtractionFields(doc.id)).items,
      enabled: invoice !== null,
      staleTime: 60_000,
    })),
  });

  // Stable signature of the candidates' field data — the useQueries result
  // array itself changes identity every render.
  const candidateFieldsStamp = candidateFields.map((q) => q.dataUpdatedAt).join(",");
  const matchedDocumentId = useMemo(() => {
    if (!invoice) return null;
    const printedNumber = invoice.invoice_number.trim().toLowerCase();
    for (let index = 0; index < candidateDocuments.length; index += 1) {
      const fields = candidateFields[index]?.data;
      if (!fields) continue;
      const numberField = fields.find((field) => field.field_name === "invoice_number");
      const value = (numberField?.verified_value ?? numberField?.field_value ?? "")
        .trim()
        .toLowerCase();
      if (value && value === printedNumber) return candidateDocuments[index].id;
    }
    return null;
    // candidateFieldsStamp summarizes candidateFields data freshness.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [invoice, candidateDocuments, candidateFieldsStamp]);

  const selectedDocumentId = docParam ?? matchedDocumentId ?? null;
  return { selectedDocumentId };
}

// ---------------------------------------------------------------------------
// Case workspace (split screen)
// ---------------------------------------------------------------------------

function CaseWorkspace({
  caseId,
  docParam,
  onBack,
  onSelectDocument,
}: {
  caseId: string;
  docParam: string | null;
  onBack: () => void;
  onSelectDocument: (documentId: string) => void;
}) {
  const me = useMe();
  const role = me.data?.user.role;
  // RBAC mirrors apps/api tenancy/permissions.py — the server enforces the
  // same matrix; these flags only hide buttons the API would reject (403).
  const canVerify = role === "org_admin" || role === "reviewer";
  const canContribute = canVerify || role === "finance_officer";
  const currentUserId = me.data?.user.id ?? null;

  const caseQuery = useQuery({
    queryKey: ["case", caseId],
    queryFn: () => getCase(caseId),
  });
  const caseData = caseQuery.data;

  const invoiceId = caseData?.invoice_id ?? null;
  const vendorId = caseData?.vendor_id ?? null;

  const invoiceQuery = useQuery({
    queryKey: ["invoice", invoiceId],
    queryFn: () => getInvoice(invoiceId as string),
    enabled: invoiceId !== null,
  });
  const invoice = invoiceQuery.data ?? null;
  const { selectedDocumentId } = useSourceDocument(invoice, docParam);

  // ---- assessment (shared by FindingsPanel + MatchesPanel) ----------------
  const queryClient = useQueryClient();
  const assessmentQuery = useQuery({
    queryKey: ["assessment", invoiceId],
    queryFn: () => getLatestAssessment(invoiceId as string),
    enabled: invoiceId !== null,
  });
  const assessment = assessmentQuery.data ?? null;

  const assessMutation = useMutation({
    mutationFn: () => assessInvoice(invoiceId as string),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["assessment", invoiceId] });
      void queryClient.invalidateQueries({ queryKey: ["invoice", invoiceId] });
      void queryClient.invalidateQueries({ queryKey: ["cases"] });
      void queryClient.invalidateQueries({ queryKey: ["case", caseId] });
    },
  });

  if (caseQuery.isPending) {
    return (
      <div className="space-y-6">
        <button type="button" onClick={onBack} className="text-sm text-primary hover:underline">
          ← All investigations
        </button>
        <SkeletonList rows={6} />
      </div>
    );
  }

  if (caseQuery.isError) {
    return (
      <div className="space-y-6">
        <button type="button" onClick={onBack} className="text-sm text-primary hover:underline">
          ← All investigations
        </button>
        <ErrorState
          error={caseQuery.error}
          title="Could not load this case"
          onRetry={() => void caseQuery.refetch()}
        />
      </div>
    );
  }

  if (!caseData) return null;

  const hasInvoice = invoiceId !== null;

  return (
    <div className="space-y-6">
      <button type="button" onClick={onBack} className="text-sm text-primary hover:underline">
        ← All investigations
      </button>

      <CaseHeader
        caseData={caseData}
        canVerify={canVerify}
        canContribute={canContribute}
        currentUserId={currentUserId}
      />

      {!hasInvoice && !vendorId ? (
        <EmptyState
          icon={ShieldAlert}
          title="This case has no linked invoice or vendor"
          description="A case must reference an invoice or a vendor; this one references neither, so there is nothing to investigate yet."
        />
      ) : (
        <div className="grid items-start gap-6 lg:grid-cols-2">
          {/* LEFT — document preview with page navigation */}
          <div className="lg:sticky lg:top-6">
            <DocumentPreview
              documentId={hasInvoice ? selectedDocumentId : null}
              // The chooser only makes sense for invoice-backed cases.
              onChooseDocument={hasInvoice ? onSelectDocument : undefined}
            />
          </div>

          {/* RIGHT — review panels */}
          <div className="space-y-6">
            {hasInvoice ? (
              <>
                <FieldsPanel
                  documentId={selectedDocumentId}
                  canVerify={canVerify}
                  canContribute={canContribute}
                />
                <VendorPanel vendorId={invoice?.vendor_id ?? vendorId} invoice={invoice} />
                <PoPanel invoice={invoice} />
                <EvidencePanel invoiceId={invoiceId} />
                <FindingsPanel
                  invoiceId={invoiceId}
                  assessment={assessment}
                  pending={assessmentQuery.isPending}
                  error={assessmentQuery.error}
                  onRetry={() => void assessmentQuery.refetch()}
                  canVerify={canVerify}
                  canContribute={canContribute}
                  onRunAssessment={() => assessMutation.mutate()}
                  runPending={assessMutation.isPending}
                  runError={assessMutation.error}
                />
                <MatchesPanel assessment={assessment} />
              </>
            ) : (
              <VendorPanel vendorId={vendorId} invoice={null} />
            )}
            <ActionsFeed caseId={caseId} canContribute={canContribute} />
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Case-less invoice workspace (reached from the Invoices screen)
// ---------------------------------------------------------------------------

function InvoiceWorkspace({
  invoiceId,
  docParam,
  onBack,
  onSelectDocument,
  onCaseOpened,
}: {
  invoiceId: string;
  docParam: string | null;
  onBack: () => void;
  onSelectDocument: (documentId: string) => void;
  onCaseOpened: (caseId: string) => void;
}) {
  const me = useMe();
  const role = me.data?.user.role;
  const canVerify = role === "org_admin" || role === "reviewer";
  const canContribute = canVerify || role === "finance_officer";

  const invoiceQuery = useQuery({
    queryKey: ["invoice", invoiceId],
    queryFn: () => getInvoice(invoiceId),
  });
  const invoice = invoiceQuery.data ?? null;
  const { selectedDocumentId } = useSourceDocument(invoice, docParam);

  const queryClient = useQueryClient();
  const assessmentQuery = useQuery({
    queryKey: ["assessment", invoiceId],
    queryFn: () => getLatestAssessment(invoiceId),
  });
  const assessment = assessmentQuery.data ?? null;

  const assessMutation = useMutation({
    mutationFn: () => assessInvoice(invoiceId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["assessment", invoiceId] });
      void queryClient.invalidateQueries({ queryKey: ["invoice", invoiceId] });
      void queryClient.invalidateQueries({ queryKey: ["cases"] });
    },
  });

  const [openCaseOpen, setOpenCaseOpen] = useState(false);

  return (
    <div className="space-y-6">
      <button type="button" onClick={onBack} className="text-sm text-primary hover:underline">
        ← All investigations
      </button>

      <PageHeader
        title={invoice ? `Invoice ${invoice.invoice_number}` : "Investigate invoice"}
        description="Case-less investigation of one invoice. It shows the same evidence panels a case workspace shows; opening a case adds the assignment, review-actions record and the R6 close decision."
      />

      {invoiceQuery.isError ? (
        <ErrorState
          error={invoiceQuery.error}
          title="Could not load this invoice"
          onRetry={() => void invoiceQuery.refetch()}
        />
      ) : null}

      <div className="rounded-lg border bg-card px-4 py-3 text-sm">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-muted-foreground">
            No investigation case is linked to this invoice. Critical assessments
            open one automatically (R6); a reviewer or organization admin can also
            open one manually.
          </p>
          {canVerify ? (
            <Button variant="outline" size="sm" onClick={() => setOpenCaseOpen(true)}>
              Open investigation case…
            </Button>
          ) : null}
        </div>
        {invoice ? (
          <p className="mt-1 text-xs text-muted-foreground">
            Invoice {invoice.invoice_number}
            {invoice.total_amount ? ` · ${invoice.total_amount} ${invoice.currency ?? ""}` : ""}
            {" · "}
            workflow status {invoice.status.replace(/_/g, " ")}
          </p>
        ) : null}
      </div>

      <div className="grid items-start gap-6 lg:grid-cols-2">
        <div className="lg:sticky lg:top-6">
          <DocumentPreview documentId={selectedDocumentId} onChooseDocument={onSelectDocument} />
        </div>
        <div className="space-y-6">
          <FieldsPanel
            documentId={selectedDocumentId}
            canVerify={canVerify}
            canContribute={canContribute}
          />
          <VendorPanel vendorId={invoice?.vendor_id ?? null} invoice={invoice} />
          <PoPanel invoice={invoice} />
          <EvidencePanel invoiceId={invoiceId} />
          <FindingsPanel
            invoiceId={invoiceId}
            assessment={assessment}
            pending={assessmentQuery.isPending}
            error={assessmentQuery.error}
            onRetry={() => void assessmentQuery.refetch()}
            canVerify={canVerify}
            canContribute={canContribute}
            onRunAssessment={() => assessMutation.mutate()}
            runPending={assessMutation.isPending}
            runError={assessMutation.error}
          />
          <MatchesPanel assessment={assessment} />
        </div>
      </div>

      <OpenCaseDialog
        open={openCaseOpen}
        invoice={invoice}
        onClose={() => setOpenCaseOpen(false)}
        onOpened={onCaseOpened}
      />
    </div>
  );
}

const SEVERITY_OPTIONS: CaseSeverity[] = ["low", "medium", "high", "critical"];

/** POST /cases for this invoice (reviewer/org_admin — the API 403s anyone
 *  else; the title + severity are the CaseIn required fields). */
function OpenCaseDialog({
  open,
  invoice,
  onClose,
  onOpened,
}: {
  open: boolean;
  invoice: InvoiceOut | null;
  onClose: () => void;
  onOpened: (caseId: string) => void;
}) {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState("");
  const [severity, setSeverity] = useState<CaseSeverity>("medium");
  const [localError, setLocalError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      openCase({
        title: title.trim(),
        severity,
        invoice_id: invoice?.id ?? null,
      }),
    onSuccess: (created) => {
      void queryClient.invalidateQueries({ queryKey: ["cases"] });
      onClose();
      onOpened(created.id);
    },
  });

  const submit = () => {
    setLocalError(null);
    if (title.trim().length === 0) {
      setLocalError("Give the case a title.");
      return;
    }
    mutation.mutate();
  };

  const close = () => {
    mutation.reset();
    setLocalError(null);
    setTitle("");
    setSeverity("medium");
    onClose();
  };

  return (
    <FormDialog
      open={open}
      title="Open an investigation case"
      description={
        <>
          A case is a human review obligation (R6): it gets an assignee, a
          review-actions record and a human close decision with an outcome +
          resolution summary. Critical assessments already open one
          automatically; this creates one manually for{" "}
          <span className="font-medium">
            {invoice ? `invoice ${invoice.invoice_number}` : "this invoice"}
          </span>
          .
        </>
      }
      confirmLabel="Open case"
      busy={mutation.isPending}
      onConfirm={submit}
      onCancel={close}
    >
      <div className="space-y-1.5">
        <Label htmlFor="open-case-title">Title</Label>
        <input
          id="open-case-title"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder={invoice ? `Investigate invoice ${invoice.invoice_number}` : "What needs review"}
          className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="open-case-severity">Severity</Label>
        <select
          id="open-case-severity"
          value={severity}
          onChange={(event) => setSeverity(event.target.value as CaseSeverity)}
          className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        >
          {SEVERITY_OPTIONS.map((value) => (
            <option key={value} value={value}>
              {value.charAt(0).toUpperCase() + value.slice(1)}
            </option>
          ))}
        </select>
      </div>
      {localError ? <p className="text-sm text-destructive">{localError}</p> : null}
      {mutation.isError ? (
        <p className="text-sm text-destructive">
          {mutationMessage(mutation.error, "The case could not be opened.")}
        </p>
      ) : null}
    </FormDialog>
  );
}
