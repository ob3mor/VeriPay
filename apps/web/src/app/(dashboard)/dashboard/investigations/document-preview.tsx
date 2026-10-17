/* eslint-disable @next/next/no-img-element */
"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Download, FileText } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { StatusBadge } from "@/components/status-badge";
import {
  downloadDocumentFile,
  getDocument,
  listDocuments,
  listExtractionFields,
} from "@/lib/api";
import { processingStatusPresentation } from "@/lib/status";
import type { ExtractionFieldOut } from "@veripay/api-contracts";

import { mutationMessage } from "./api-extras";

export interface DocumentPreviewProps {
  /** Resolved source document id, or null when none is identified yet. */
  documentId: string | null;
  /** Persist an explicit document choice (workspace writes it to `&doc=`). */
  onChooseDocument?: (documentId: string) => void;
}

/**
 * LEFT split-screen pane: the invoice's source document with page navigation.
 *
 * - The bytes come from the protected GET /documents/{id}/file endpoint
 *   (DB-resolved storage key; session cookie authenticates) and are rendered
 *   from a blob object URL, which is revoked on change/unmount.
 * - PDFs render in the browser's viewer; `#page=N` drives page navigation.
 * - `DocumentOut` does not serialize `page_count`, so the page list is derived
 *   honestly from the extraction evidence spans ("Pages from evidence") —
 *   never guessed.
 * - When no document is identified, the pane offers the document chooser so
 *   the investigator can assert the provenance explicitly.
 */
export function DocumentPreview({ documentId, onChooseDocument }: DocumentPreviewProps) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <FileText className="h-4 w-4 text-muted-foreground" />
          Source document
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {documentId ? (
          <DocumentView documentId={documentId} />
        ) : (
          <EmptyState
            icon={FileText}
            title="No source document identified"
            description="The API does not expose the invoice's source document directly, and no invoice-kind document with a matching extracted invoice number was found. Pick the document below to review it here."
          />
        )}
        {onChooseDocument ? <DocumentChooser selectedId={documentId} onChoose={onChooseDocument} /> : null}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// One document: metadata, blob render, page navigation
// ---------------------------------------------------------------------------

function DocumentView({ documentId }: { documentId: string }) {
  const documentQuery = useQuery({
    queryKey: ["document", documentId],
    queryFn: () => getDocument(documentId),
  });
  const doc = documentQuery.data ?? null;

  // Page numbers come from the extraction evidence spans (cached by the
  // workspace's matcher and the fields panel — one shared cache entry).
  const fieldsQuery = useQuery({
    queryKey: ["fields", documentId],
    queryFn: () => listExtractionFields(documentId),
    staleTime: 60_000,
  });
  const fields: ExtractionFieldOut[] = fieldsQuery.data ?? [];

  const spanPages = useMemo(() => {
    const pages = new Set<number>();
    for (const field of fields) {
      for (const span of field.evidence_spans ?? []) {
        if (typeof span?.page === "number" && Number.isFinite(span.page) && span.page > 0) {
          pages.add(span.page);
        }
      }
    }
    return [...pages].sort((a, b) => a - b);
  }, [fields]);

  const [page, setPage] = useState(1);
  useEffect(() => {
    setPage(1);
  }, [documentId]);

  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [blobError, setBlobError] = useState<unknown>(null);
  const [reloadTick, setReloadTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let created: string | null = null;
    setObjectUrl(null);
    setBlobError(null);
    downloadDocumentFile(documentId, doc?.file_name ?? "document")
      .then(({ blob }) => {
        if (cancelled) return;
        created = URL.createObjectURL(blob);
        setObjectUrl(created);
      })
      .catch((error) => {
        if (!cancelled) setBlobError(error);
      });
    return () => {
      cancelled = true;
      if (created) URL.revokeObjectURL(created);
    };
    // Re-fetch when the metadata arrives (better fallback name) or when the
    // investigator hits Retry.
  }, [documentId, doc?.file_name, reloadTick]);

  if (documentQuery.isError) {
    return <ErrorState error={documentQuery.error} title="Could not load the document record" />;
  }
  if (blobError) {
    return (
      <div className="space-y-2">
        <ErrorState
          error={blobError}
          title="Could not download the document"
          retryLabel="Retry"
          onRetry={() => {
            setBlobError(null);
            setReloadTick((tick) => tick + 1);
          }}
        />
        <p className="text-xs text-muted-foreground">
          The file endpoint requires an authenticated session; without the API
          running, the preview cannot load.
        </p>
      </div>
    );
  }

  const mime = doc?.mime_type ?? "";
  const isPdf = mime === "application/pdf";
  const isImage = mime.startsWith("image/");
  const maxKnownPage = spanPages.length > 0 ? spanPages[spanPages.length - 1] : 1;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="min-w-0 truncate text-sm font-medium" title={doc?.file_name ?? undefined}>
          {doc?.file_name ?? "Loading…"}
        </p>
        <div className="flex items-center gap-2">
          {doc ? <StatusBadge presentation={processingStatusPresentation(doc.processing_status)} hideDot /> : null}
          {objectUrl ? (
            <a
              href={objectUrl}
              download={doc?.file_name ?? "document"}
              className="inline-flex h-8 items-center gap-1.5 rounded-md border px-2.5 text-xs font-medium hover:bg-muted"
            >
              <Download className="h-3.5 w-3.5" />
              Download
            </a>
          ) : null}
        </div>
      </div>

      {isPdf && objectUrl ? (
        <>
          <embed
            key={`${objectUrl}#${page}`}
            src={`${objectUrl}#page=${page}`}
            type="application/pdf"
            title="Source document (PDF)"
            className="h-[65vh] w-full rounded-md border bg-muted"
          />
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-muted-foreground">Pages from evidence spans:</span>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              aria-label="Previous page"
            >
              <ChevronLeft />
            </Button>
            <span className="min-w-16 text-center text-sm font-medium">Page {page}</span>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => p + 1)}
              disabled={page >= maxKnownPage}
              aria-label="Next page"
              title={page >= maxKnownPage ? "Highest page cited by the extraction evidence" : undefined}
            >
              <ChevronRight />
            </Button>
            {spanPages.length > 0 ? (
              <span className="flex flex-wrap items-center gap-1">
                {spanPages.map((p) => (
                  <button
                    key={p}
                    type="button"
                    onClick={() => setPage(p)}
                    aria-current={p === page ? "true" : undefined}
                    className={
                      p === page
                        ? "rounded bg-primary px-2 py-0.5 text-xs font-medium text-primary-foreground"
                        : "rounded border px-2 py-0.5 text-xs hover:bg-muted"
                    }
                  >
                    {p}
                  </button>
                ))}
              </span>
            ) : null}
          </div>
        </>
      ) : isImage && objectUrl ? (
        <img
          src={objectUrl}
          alt={doc?.file_name ?? "Source document"}
          className="max-h-[65vh] w-full rounded-md border bg-muted object-contain"
        />
      ) : objectUrl ? (
        <div className="rounded-md border border-dashed p-4 text-sm">
          <p className="text-muted-foreground">
            This file type ({mime || "unknown"}) cannot be previewed inline.
          </p>
          <a href={objectUrl} download={doc?.file_name ?? "document"} className="mt-2 inline-flex items-center gap-1.5 text-sm font-medium text-primary hover:underline">
            <Download className="h-4 w-4" />
            Download the file
          </a>
        </div>
      ) : (
        <div className="flex h-48 items-center justify-center rounded-md border bg-muted/40" role="status" aria-label="Loading document">
          <span className="text-sm text-muted-foreground">Loading document…</span>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Document chooser — explicit provenance when auto-match is not possible
// ---------------------------------------------------------------------------

function DocumentChooser({
  selectedId,
  onChoose,
}: {
  selectedId: string | null;
  onChoose: (documentId: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const listQuery = useQuery({
    queryKey: ["documents"],
    queryFn: () => listDocuments({ limit: 100 }),
    enabled: open,
  });

  return (
    <div className="rounded-md border border-dashed p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-muted-foreground">
          Wrong or missing document? Pick the source document explicitly — the
          choice is kept in the workspace link.
        </p>
        <Button variant="outline" size="sm" onClick={() => setOpen((v) => !v)}>
          {open ? "Hide list" : "Choose document…"}
        </Button>
      </div>
      {open ? (
        listQuery.isError ? (
          <p className="mt-2 text-xs text-destructive">
            {mutationMessage(listQuery.error, "Could not load the document list.")}
          </p>
        ) : listQuery.isPending ? (
          <p className="mt-2 text-xs text-muted-foreground">Loading documents…</p>
        ) : (listQuery.data?.length ?? 0) === 0 ? (
          <p className="mt-2 text-xs text-muted-foreground">
            Your organization has no documents yet.
          </p>
        ) : (
          <ul className="mt-2 max-h-56 space-y-1 overflow-y-auto">
            {(listQuery.data ?? []).map((doc) => (
              <li key={doc.id}>
                <button
                  type="button"
                  onClick={() => {
                    onChoose(doc.id);
                    setOpen(false);
                  }}
                  aria-pressed={doc.id === selectedId}
                  className={
                    doc.id === selectedId
                      ? "flex w-full items-center justify-between gap-3 rounded-md bg-primary/10 px-3 py-2 text-left text-sm"
                      : "flex w-full items-center justify-between gap-3 rounded-md px-3 py-2 text-left text-sm hover:bg-muted"
                  }
                >
                  <span className="min-w-0 truncate" title={doc.file_name}>
                    {doc.file_name}
                  </span>
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {doc.kind} · {processingStatusPresentation(doc.processing_status).label}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )
      ) : null}
    </div>
  );
}
