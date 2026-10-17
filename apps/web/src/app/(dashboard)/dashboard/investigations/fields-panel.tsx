"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Pencil, RefreshCw, RotateCcw, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { StatusBadge } from "@/components/status-badge";
import { getDocument, getExtraction, listExtractionFields, reprocessDocument } from "@/lib/api";
import {
  confidencePresentation,
  fieldVerificationPresentation,
  processingStatusPresentation,
} from "@/lib/status";
import type { ExtractionFieldOut } from "@veripay/api-contracts";

import { mutationMessage, reviewExtractionField } from "./api-extras";

export interface FieldsPanelProps {
  documentId: string | null;
  canVerify: boolean;
  canContribute: boolean;
}

/**
 * RIGHT pane, top: extracted fields with confidence badges and the human
 * R3 review actions (confirm / correct — reviewer/org_admin; the server
 * rejects anyone else with 403).
 *
 * Invariant R3 is surfaced, not laundered: NULL or below-threshold confidence
 * renders as "Uncertain" (lib/status.ts confidencePresentation) and the panel
 * copy states that uncertain extraction is provenance for humans, never
 * confident evidence. Correction requires a non-empty value (the API enforces
 * 422 as well); the original extraction is never overwritten — the human's
 * value lands in verified_value.
 */
export function FieldsPanel({ documentId, canVerify, canContribute }: FieldsPanelProps) {
  if (!documentId) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Extracted fields</CardTitle>
        </CardHeader>
        <CardContent>
          <EmptyState
            icon={Pencil}
            title="No source document selected"
            description="Choose the invoice's source document on the left to see its extracted fields and review them."
          />
        </CardContent>
      </Card>
    );
  }
  return <FieldsForDocument documentId={documentId} canVerify={canVerify} canContribute={canContribute} />;
}

function FieldsForDocument({
  documentId,
  canVerify,
  canContribute,
}: {
  documentId: string;
  canVerify: boolean;
  canContribute: boolean;
}) {
  const queryClient = useQueryClient();
  const documentQuery = useQuery({
    queryKey: ["document", documentId],
    queryFn: () => getDocument(documentId),
  });
  const extractionQuery = useQuery({
    queryKey: ["extraction", documentId],
    queryFn: () => getExtraction(documentId),
  });
  const fieldsQuery = useQuery({
    queryKey: ["fields", documentId],
    queryFn: async () => (await listExtractionFields(documentId)).items,
    staleTime: 60_000,
  });

  const reprocessMutation = useMutation({
    mutationFn: () => reprocessDocument(documentId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["document", documentId] });
      void queryClient.invalidateQueries({ queryKey: ["extraction", documentId] });
      void queryClient.invalidateQueries({ queryKey: ["fields", documentId] });
    },
  });

  const doc = documentQuery.data ?? null;
  const processing = doc ? processingStatusPresentation(doc.processing_status) : null;
  const notProcessed =
    doc !== null && doc.processing_status !== "completed" && doc.processing_status !== "failed";

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex flex-wrap items-center justify-between gap-2 text-base">
          <span>Extracted fields</span>
          <span className="flex items-center gap-2 text-xs font-normal text-muted-foreground">
            {extractionQuery.data ? (
              <>
                Extraction {extractionQuery.data.extraction_version}
                {extractionQuery.data.ocr_provider ? ` · OCR: ${extractionQuery.data.ocr_provider}` : ""}
              </>
            ) : null}
            {processing ? <StatusBadge presentation={processing} hideDot /> : null}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {documentQuery.isError ? (
          <ErrorState
            error={documentQuery.error}
            title="Could not load the document record"
            onRetry={() => void documentQuery.refetch()}
          />
        ) : fieldsQuery.isError ? (
          <ErrorState
            error={fieldsQuery.error}
            title="Could not load extracted fields"
            onRetry={() => void fieldsQuery.refetch()}
          />
        ) : doc && doc.processing_status === "failed" ? (
          <div className="space-y-3">
            <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm">
              <p className="font-semibold text-destructive">Processing failed</p>
              <p className="mt-1 break-words text-foreground/80">
                {extractionQuery.data?.error ?? "The processing job recorded a failure for this document."}
              </p>
            </div>
            {canContribute ? (
              <Button
                variant="outline"
                size="sm"
                onClick={() => reprocessMutation.mutate()}
                disabled={reprocessMutation.isPending}
              >
                <RotateCcw />
                Retry processing
              </Button>
            ) : null}
          </div>
        ) : notProcessed ? (
          <div className="space-y-3 rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
            <p>
              This document has not completed processing yet — there are no
              extracted fields to review.
            </p>
            {canContribute ? (
              <Button
                variant="outline"
                size="sm"
                onClick={() => reprocessMutation.mutate()}
                disabled={reprocessMutation.isPending}
              >
                <RefreshCw />
                Request processing
              </Button>
            ) : null}
          </div>
        ) : fieldsQuery.isPending || documentQuery.isPending ? (
          <div className="space-y-3" role="status" aria-label="Loading fields">
            <div className="h-4 w-40 animate-pulse rounded bg-muted" />
            <div className="h-4 w-64 animate-pulse rounded bg-muted" />
            <div className="h-4 w-52 animate-pulse rounded bg-muted" />
          </div>
        ) : (fieldsQuery.data ?? []).length === 0 ? (
          <EmptyState
            icon={Pencil}
            title="Nothing was extracted"
            description="Processing completed but no named fields were persisted for this document."
          />
        ) : (
          <ul className="divide-y divide-border">
            {(fieldsQuery.data ?? []).map((field) => (
              <FieldRow
                key={field.id}
                field={field}
                documentId={documentId}
                canVerify={canVerify}
              />
            ))}
          </ul>
        )}

        {reprocessMutation.isError ? (
          <p className="text-sm text-destructive">
            {mutationMessage(reprocessMutation.error, "Could not request processing.")}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// One field row
// ---------------------------------------------------------------------------

const FIELD_LABELS: Record<string, string> = {
  invoice_number: "Invoice number",
  invoice_date: "Invoice date",
  due_date: "Due date",
  vendor_name: "Vendor name",
  vendor_tax_id: "Vendor tax ID",
  total_amount: "Total amount",
  subtotal_amount: "Subtotal",
  tax_amount: "Tax",
  currency: "Currency",
  po_number: "PO number",
  remittance_bank_name: "Remittance bank (printed)",
  remittance_account: "Remittance account (printed)",
};

function FieldRow({
  field,
  documentId,
  canVerify,
}: {
  field: ExtractionFieldOut;
  documentId: string;
  canVerify: boolean;
}) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");

  const reviewMutation = useMutation({
    mutationFn: (input: { action: "confirm" | "correct"; verified_value?: string | null }) =>
      reviewExtractionField(documentId, field.id, input),
    onSuccess: () => {
      setEditing(false);
      void queryClient.invalidateQueries({ queryKey: ["fields", documentId] });
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
  });

  const confidence = confidencePresentation(field.confidence);
  const verification = fieldVerificationPresentation(field.verification_status);
  const corrected = field.verification_status === "corrected";
  const displayValue = corrected ? field.verified_value : field.field_value;
  const percent =
    field.confidence === null ? null : `${Math.round(field.confidence * 100)}%`;
  const unreviewed = field.verification_status === "unverified";

  const submitCorrection = () => {
    if (draft.trim().length === 0) return;
    reviewMutation.mutate({ action: "correct", verified_value: draft.trim() });
  };

  return (
    <li className="py-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {FIELD_LABELS[field.field_name] ?? field.field_name}
          </p>
          <p className="mt-0.5 break-words text-sm">
            <span className={corrected ? "font-medium text-primary" : undefined}>
              {displayValue ?? "—"}
            </span>
            {corrected && field.field_value ? (
              <span className="ml-2 text-xs text-muted-foreground">
                (extracted: {field.field_value})
              </span>
            ) : null}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-1.5">
          <StatusBadge presentation={confidence} hideDot />
          {percent ? <span className="text-xs text-muted-foreground">{percent}</span> : null}
          <StatusBadge presentation={verification} hideDot />
        </div>
      </div>

      {(field.evidence_spans ?? []).length > 0 ? (
        <ul className="mt-1.5 space-y-0.5">
          {field.evidence_spans.slice(0, 4).map((span, index) => (
            <li key={index} className="truncate text-xs text-muted-foreground">
              {typeof span?.page === "number" ? `p.${span.page}` : "p.?"}
              {typeof span?.text === "string" && span.text ? `: “${span.text.slice(0, 90)}”` : ""}
            </li>
          ))}
        </ul>
      ) : null}

      {canVerify && unreviewed ? (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {editing ? (
            <>
              <input
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                placeholder="Corrected value"
                aria-label={`Corrected value for ${FIELD_LABELS[field.field_name] ?? field.field_name}`}
                className="h-8 flex-1 rounded-md border border-input bg-background px-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
              <Button
                size="sm"
                onClick={submitCorrection}
                disabled={draft.trim().length === 0 || reviewMutation.isPending}
              >
                <Check />
                Save correction
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setEditing(false);
                  setDraft("");
                  reviewMutation.reset();
                }}
              >
                <X />
                Cancel
              </Button>
            </>
          ) : (
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={() => reviewMutation.mutate({ action: "confirm" })}
                disabled={reviewMutation.isPending}
              >
                <Check />
                Confirm value
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setEditing(true)}>
                <Pencil />
                Correct…
              </Button>
            </>
          )}
          {reviewMutation.isError ? (
            <span className="text-xs text-destructive">
              {mutationMessage(reviewMutation.error, "The review action failed.")}
            </span>
          ) : null}
        </div>
      ) : null}

      {canVerify && !unreviewed ? (
        <p className="mt-1 text-xs text-muted-foreground">
          Already reviewed by a human — the record of that review stands.
        </p>
      ) : null}
    </li>
  );
}
