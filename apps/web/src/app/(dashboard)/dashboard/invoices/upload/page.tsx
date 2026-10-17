"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CircleAlert, LoaderCircle, Upload } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Card, CardContent } from "@/components/ui/card";
import { PageHeader } from "@/components/page-header";
import { ErrorState } from "@/components/error-state";
import { FileDropZone } from "@/components/upload/file-drop-zone";
import { DocumentPreview } from "@/components/upload/document-preview";
import { ProcessingStatusCard } from "@/components/upload/processing-status-card";
import {
  useDocumentProcessing,
} from "@/components/upload/use-document-processing";
import {
  UploadAbortedError,
  uploadDocumentWithProgress,
  validateUploadFile,
  type UploadProgress,
} from "@/components/upload/upload-client";
import { ApiError, getExtraction, listVendors, reprocessDocument } from "@/lib/api";
import { roleLabel } from "@/lib/auth";
import { useMe } from "@/hooks/use-session";
import type { DocumentKind, ProcessedDocumentOut } from "@veripay/api-contracts";

const KIND_OPTIONS: ReadonlyArray<readonly [DocumentKind, string]> = [
  ["invoice", "Invoice"],
  ["purchase_order", "Purchase order"],
  ["bank_letter", "Bank letter"],
  ["statement", "Statement"],
  ["other", "Other"],
];

/**
 * Invoice upload: drag & drop, local PDF/image preview, client-side
 * validation (same rules as the API — MIME allowlist, magic bytes, 10 MiB),
 * XHR progress, processing-status polling via the document endpoints and the
 * idempotent retry (POST /documents/{id}/process).
 *
 * Honesty: every failure is shown as a failure with the API's own message
 * (docs/API.md §2 envelope — `message` is safe to render, request_id is kept
 * for correlation). Nothing here claims the document or invoice is genuine;
 * a completed extraction is exactly that — extraction (R1/R2/R3).
 *
 * Scope note rendered on the page: this uploads + processes the DOCUMENT. It
 * does not create an invoice record — invoice intake (number, amounts,
 * vendor) is the separate POST /invoices step, so humans control what enters
 * the registry.
 */
export default function InvoiceUploadPage() {
  const me = useMe();
  const role = me.data?.user.role;
  // Upload is contributor-only (org_admin/finance_officer/reviewer — apps/api
  // tenancy/permissions.py CAN_CONTRIBUTE). A disallowed role gets the honest
  // restricted panel BEFORE any upload attempt; a 403 from the API (defense in
  // depth) surfaces through the same panel below via the upload error state.
  const canUpload = role !== undefined && ["org_admin", "finance_officer", "reviewer"].includes(role);

  const queryClient = useQueryClient();
  const abortRef = useRef<AbortController | null>(null);

  const [file, setFile] = useState<File | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [kind, setKind] = useState<DocumentKind>("invoice");
  const [vendorId, setVendorId] = useState<string>("");
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState<UploadProgress | null>(null);
  const [uploadError, setUploadError] = useState<unknown>(null);
  const [uploaded, setUploaded] = useState<ProcessedDocumentOut | null>(null);

  // Vendor context is optional — loaded once; a failure only disables the
  // select (the upload itself does not depend on it).
  const vendorsQuery = useQuery({
    queryKey: ["vendors", "upload-options"],
    queryFn: () => listVendors({ limit: 100 }),
    staleTime: 60_000,
  });

  // Processing status polling via GET /documents/{id} (document endpoints).
  const pollingQuery = useDocumentProcessing(uploaded?.id ?? null);
  const polledDoc = pollingQuery.data ?? uploaded ?? null;

  // When processing failed, surface the extraction record's own error text.
  const extractionQuery = useQuery({
    queryKey: ["documents", uploaded?.id ?? "", "extraction"],
    queryFn: () => getExtraction(uploaded?.id as string),
    enabled: Boolean(uploaded?.id) && polledDoc?.processing_status === "failed",
  });

  // Idempotent retry — POST /documents/{id}/process.
  const retryMutation = useMutation({
    mutationFn: (documentId: string) => reprocessDocument(documentId),
    onSuccess: (doc) => {
      queryClient.setQueryData(["documents", doc.id], doc);
      // Drop the previous failure's extraction error so a second failure
      // shows the CURRENT error, not a stale one.
      void queryClient.invalidateQueries({ queryKey: ["documents", doc.id, "extraction"] });
    },
  });

  async function handleFileSelected(next: File) {
    setUploadError(null);
    setUploaded(null);
    setFile(next);
    setValidationError(await validateUploadFile(next));
  }

  function reset() {
    abortRef.current?.abort();
    abortRef.current = null;
    setFile(null);
    setValidationError(null);
    setUploading(false);
    setProgress(null);
    setUploadError(null);
    setUploaded(null);
  }

  async function handleUpload() {
    if (!file || validationError) return;
    setUploading(true);
    setUploadError(null);
    setProgress(null);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const doc = await uploadDocumentWithProgress({
        file,
        kind,
        vendor_id: vendorId || undefined,
        signal: controller.signal,
        onProgress: setProgress,
      });
      // Seed the polling cache with the upload response so the status card
      // renders immediately; the poll refines it from GET /documents/{id}.
      queryClient.setQueryData(["documents", doc.id], doc);
      setUploaded(doc);
      setFile(null);
      setValidationError(null);
    } catch (error) {
      if (error instanceof UploadAbortedError) {
        // User-initiated cancellation — back to the selected state, no error.
      } else {
        setUploadError(error);
      }
    } finally {
      setUploading(false);
      setProgress(null);
      abortRef.current = null;
    }
  }

  const vendors = vendorsQuery.data ?? [];
  const showForm = !uploaded;

  if (me.isPending) {
    return (
      <div className="space-y-8">
        <Link
          href="/dashboard/invoices"
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft aria-hidden="true" className="h-4 w-4" />
          Back to invoices
        </Link>
        <PageHeader title="Upload invoice document" />
        <div className="h-48 animate-pulse rounded-lg bg-muted" role="status" aria-label="Loading upload form" />
      </div>
    );
  }

  if (!canUpload) {
    return (
      <div className="space-y-8">
        <Link
          href="/dashboard/invoices"
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft aria-hidden="true" className="h-4 w-4" />
          Back to invoices
        </Link>
        <PageHeader title="Upload invoice document" />
        <div
          role="note"
          className="flex flex-col items-center justify-center rounded-lg border border-dashed bg-card px-6 py-14 text-center"
        >
          <span
            aria-hidden="true"
            className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-muted"
          >
            <CircleAlert className="h-6 w-6 text-muted-foreground" />
          </span>
          <p className="text-sm font-semibold text-foreground">Uploading is restricted</p>
          <p className="mt-1.5 max-w-md text-sm text-muted-foreground">
            You are signed in as {role ? roleLabel(role) : "a role without upload permission"}. Uploading
            documents requires the finance officer, reviewer, or organization admin role (docs/API.md §5
            role × action matrix), so this page made no upload. The invoice list itself remains available to you.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <Link
        href="/dashboard/invoices"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft aria-hidden="true" className="h-4 w-4" />
        Back to invoices
      </Link>

      <PageHeader
        title="Upload invoice document"
        description="Store a PDF, PNG or JPEG, and the OCR/extraction pipeline processes it. Processing is a machine step — it never approves anything and never claims the document is genuine."
      />

      {showForm ? (
        <div className="grid gap-6 lg:grid-cols-2">
          {/* Left: selection + metadata + upload action */}
          <div className="space-y-6">
            <FileDropZone
              onFileSelected={handleFileSelected}
              disabled={uploading}
              hint="PDF, PNG or JPEG · up to 10 MB · content is signature-checked before upload"
            />

            {validationError && (
              <p
                role="alert"
                className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive"
              >
                <CircleAlert aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />
                {validationError}
              </p>
            )}

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="document-kind">Document kind</Label>
                <select
                  id="document-kind"
                  value={kind}
                  onChange={(event) => setKind(event.target.value as DocumentKind)}
                  disabled={uploading}
                  className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {KIND_OPTIONS.map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="document-vendor">Vendor context (optional)</Label>
                <select
                  id="document-vendor"
                  value={vendorId}
                  onChange={(event) => setVendorId(event.target.value)}
                  disabled={uploading || vendors.length === 0}
                  className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <option value="">No vendor context</option>
                  {vendors.map((vendor) => (
                    <option key={vendor.id} value={vendor.id}>
                      {vendor.display_name}
                    </option>
                  ))}
                </select>
                {vendorsQuery.isError && (
                  <p className="text-xs text-muted-foreground">
                    Vendor list is unavailable right now — the upload still works without it.
                  </p>
                )}
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <Button onClick={handleUpload} disabled={!file || Boolean(validationError) || uploading}>
                {uploading ? (
                  <LoaderCircle aria-hidden="true" className="animate-spin" />
                ) : (
                  <Upload />
                )}
                {uploading ? "Uploading…" : "Upload"}
              </Button>
              {uploading && (
                <Button variant="ghost" onClick={() => abortRef.current?.abort()}>
                  Cancel
                </Button>
              )}
              {file && !uploading && (
                <Button variant="ghost" onClick={() => { setFile(null); setValidationError(null); }}>
                  Remove file
                </Button>
              )}
            </div>

            {uploading && (
              <div>
                <div
                  role="progressbar"
                  aria-label="Upload progress"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={progress?.percent ?? undefined}
                  className="h-2 w-full overflow-hidden rounded-full bg-muted"
                >
                  <div
                    className={
                      progress?.percent === null || progress?.percent === undefined
                        ? "h-full w-1/2 animate-pulse rounded-full bg-primary"
                        : "h-full rounded-full bg-primary transition-[width]"
                    }
                    style={
                      progress?.percent != null ? { width: `${progress.percent}%` } : undefined
                    }
                  />
                </div>
                <p className="mt-2 text-xs text-muted-foreground" role="status">
                  {progress?.percent != null
                    ? `${progress.percent}% uploaded`
                    : "Uploading… (the browser did not report a total size)"}
                </p>
              </div>
            )}

            {uploadError ? (
              <ErrorState
                error={uploadError}
                title={
                  uploadError instanceof ApiError && uploadError.status === 403
                    ? "Your role cannot upload documents"
                    : undefined
                }
                onRetry={handleUpload}
                retryLabel="Try uploading again"
              />
            ) : null}

            <Card>
              <CardContent className="pt-6 text-sm leading-relaxed text-muted-foreground">
                <p>
                  This step stores and processes the <span className="font-medium text-foreground">document</span>{" "}
                  (per-org duplicate detection included: identical bytes reuse the stored copy). It
                  does not create an invoice record — invoice intake (number, amounts, vendor) is
                  the separate <span className="font-mono text-xs">POST /invoices</span> step.
                </p>
              </CardContent>
            </Card>
          </div>

          {/* Right: local preview of the selected file */}
          <div>
            {file ? (
              <DocumentPreview file={file} />
            ) : (
              <div className="flex h-80 items-center justify-center rounded-lg border border-dashed bg-muted/20 px-6 text-center">
                <p className="max-w-xs text-sm text-muted-foreground">
                  Select a file to see its preview here before uploading.
                </p>
              </div>
            )}
          </div>
        </div>
      ) : (
        <div className="max-w-2xl space-y-6">
          {polledDoc && (
            <ProcessingStatusCard
              document={polledDoc}
              extractionError={extractionQuery.data?.error ?? null}
              onRetry={polledDoc.id ? () => retryMutation.mutate(polledDoc.id) : undefined}
              retryPending={retryMutation.isPending}
              retryError={retryMutation.error}
            />
          )}
          {pollingQuery.isError && (
            <ErrorState
              error={pollingQuery.error}
              title="Could not refresh the processing status"
              onRetry={() => pollingQuery.refetch()}
            />
          )}
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="outline" onClick={reset}>
              Upload another document
            </Button>
            <Link
              href="/dashboard/invoices"
              className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
            >
              Back to invoices
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}
