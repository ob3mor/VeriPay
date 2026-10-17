"use client";

import { useState } from "react";
import { Download, LoaderCircle, RotateCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/status-badge";
import { ErrorState } from "@/components/error-state";
import { downloadDocumentFile } from "@/lib/api";
import { processingStatusPresentation } from "@/lib/status";
import { formatBytes } from "@/components/upload/upload-client";
import type { DocumentOut, DocumentKind } from "@veripay/api-contracts";

const KIND_LABELS: Record<DocumentKind, string> = {
  invoice: "Invoice",
  purchase_order: "Purchase order",
  bank_letter: "Bank letter",
  statement: "Statement",
  other: "Other",
};

export interface ProcessingStatusCardProps {
  document: DocumentOut;
  /** Error text from GET /documents/{id}/extraction when processing failed. */
  extractionError?: string | null;
  onRetry?: () => void;
  retryPending?: boolean;
  retryError?: unknown;
}

/**
 * Post-upload processing panel: the document record's processing_status,
 * rendered through the honest vocabulary in src/lib/status.ts. Polling is
 * owned by useDocumentProcessing — this card just states what the record
 * currently says, plus a Retry (POST /documents/{id}/process) when the job
 * failed or needs manual input, and the protected file download.
 *
 * Honesty rules: failure is shown as "Processing failed" — never restated as
 * success; there is no "invoice verified/approved" language anywhere (R1/R2).
 */
export function ProcessingStatusCard({
  document: doc,
  extractionError,
  onRetry,
  retryPending = false,
  retryError,
}: ProcessingStatusCardProps) {
  const [downloadError, setDownloadError] = useState<unknown>(null);
  const [downloading, setDownloading] = useState(false);
  const presentation = processingStatusPresentation(doc.processing_status);
  const canRetry =
    Boolean(onRetry) && (doc.processing_status === "failed" || doc.processing_status === "requires_manual_input");

  async function handleDownload() {
    setDownloading(true);
    setDownloadError(null);
    try {
      const { blob, fileName } = await downloadDocumentFile(doc.id, doc.file_name);
      const url = URL.createObjectURL(blob);
      const anchor = window.document.createElement("a");
      anchor.href = url;
      anchor.download = fileName;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      setDownloadError(error);
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="rounded-lg border bg-card p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-foreground">{doc.file_name}</p>
            <p className="mt-1 text-xs text-muted-foreground">
              {KIND_LABELS[doc.kind] ?? doc.kind} · {formatBytes(doc.size_bytes)} ·{" "}
              {"deduplicated" in doc && doc.deduplicated
                ? "already on file (identical copy reused)"
                : "stored"}
            </p>
          </div>
          <StatusBadge presentation={presentation} />
        </div>

        {(doc.processing_status === "pending" || doc.processing_status === "processing") && (
          <p className="mt-4 flex items-center gap-2 text-sm text-muted-foreground" role="status">
            <LoaderCircle aria-hidden="true" className="h-4 w-4 animate-spin" />
            Running OCR / extraction — this panel updates automatically.
          </p>
        )}

        {doc.processing_status === "completed" && (
          <p className="mt-4 text-sm text-muted-foreground">
            Processing finished. The extracted fields carry OCR confidence — uncertain values stay
            marked uncertain and never become confident evidence on their own (invariant R3).
          </p>
        )}

        {doc.processing_status === "requires_manual_input" && (
          <p className="mt-4 text-sm text-foreground/80">
            The pipeline could not finish without human input. Retry processing, or review the
            document manually.
          </p>
        )}

        {doc.processing_status === "failed" && (
          <div className="mt-4 space-y-3">
            <p className="text-sm font-medium text-destructive">Processing failed.</p>
            {extractionError && (
              <p className="break-words rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 font-mono text-xs text-foreground/80">
                {extractionError}
              </p>
            )}
          </div>
        )}

        <div className="mt-5 flex flex-wrap items-center gap-2">
          {canRetry && (
            <Button variant="outline" size="sm" onClick={onRetry} disabled={retryPending}>
              {retryPending ? (
                <LoaderCircle aria-hidden="true" className="animate-spin" />
              ) : (
                <RotateCw />
              )}
              Retry processing
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={handleDownload} disabled={downloading}>
            {downloading ? (
              <LoaderCircle aria-hidden="true" className="animate-spin" />
            ) : (
              <Download />
            )}
            Download file
          </Button>
        </div>

        {retryError ? (
          <ErrorState error={retryError} title="Retry failed" className="mt-4 py-4" />
        ) : null}
        {downloadError ? (
          <ErrorState error={downloadError} title="Download failed" className="mt-4 py-4" />
        ) : null}
      </div>
    </div>
  );
}
