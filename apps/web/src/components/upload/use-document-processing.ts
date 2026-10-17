"use client";

import { useQuery } from "@tanstack/react-query";

import { ApiNetworkError, getDocument } from "@/lib/api";
import type { DocumentOut } from "@veripay/api-contracts";

/**
 * Poll GET /documents/{id} while the processing job is non-terminal
 * (documents endpoints, per the task contract): every 2 s for
 * pending/processing, stopping on completed/failed/requires_manual_input.
 *
 * The upload response already carries the post-inline-processing status, but
 * polling is what keeps the page honest for async processing backends
 * (ADR 0006 ProcessingBackend seam) — the UI reflects the record, it never
 * assumes.
 *
 * Network failures while polling: up to 3 quick retries, then the error is
 * surfaced (the card shows it honestly — polling stops, nothing is faked).
 * API errors (e.g. 401/404) surface immediately.
 */
export function useDocumentProcessing(documentId: string | null) {
  return useQuery({
    queryKey: ["documents", documentId],
    queryFn: () => getDocument(documentId as string),
    enabled: Boolean(documentId),
    // Keep fresh results immediately usable when navigating back to the list.
    staleTime: 5_000,
    refetchInterval: (query) => {
      const status = (query.state.data as DocumentOut | undefined)?.processing_status;
      return status === "pending" || status === "processing" ? 2_000 : false;
    },
    retry: (failureCount, error) => error instanceof ApiNetworkError && failureCount < 3,
  });
}
