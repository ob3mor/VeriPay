"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Network } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { SeverityBadge } from "@/components/severity-badge";
import { StatusBadge } from "@/components/status-badge";
import { getInvoiceEvidence } from "@/lib/api";
import type {
  EvidenceItemOut,
  GraphGapOut,
  InvoiceEvidenceOut,
} from "@veripay/api-contracts";

export interface EvidencePanelProps {
  /** The case's invoice — the evidence endpoint is invoice-keyed. */
  invoiceId: string | null;
}

/**
 * Citable evidence (right pane) — the REAL retrieval aggregation from
 * GET /invoices/{id}/evidence (read-only; any authenticated role, apps/api
 * routes/retrieval.py):
 *
 * - `evidence`: graph relationships (invoice→vendor, approved bank accounts,
 *   linked/printed-referenced PO, historical invoices, vendor verification
 *   events) plus fuzzy retrieval hits, each with its explanation, techniques,
 *   scores and trust tier. Everything shown is machine-recorded provenance for
 *   the human — a retrieval hit is never a verdict on the invoice (R2).
 * - `gaps`: missing relationships (R4: absence stated as a gap — the record
 *   may simply not exist in VeriPay; severity capped ≤ medium).
 * - `contradictions`: records that disagree with each other.
 * - `meta`: backend, weights, query seeds, latency.
 *
 * Scores are retrieval-quality numbers (how well a record matched the query /
 * graph), NOT fraud probabilities; the copy says so.
 */
export function EvidencePanel({ invoiceId }: EvidencePanelProps) {
  if (!invoiceId) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Network className="h-4 w-4 text-muted-foreground" />
            Evidence trail
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            Evidence retrieval is invoice-keyed; this case has no linked invoice.
          </p>
        </CardContent>
      </Card>
    );
  }
  return <EvidenceForInvoice invoiceId={invoiceId} />;
}

function EvidenceForInvoice({ invoiceId }: { invoiceId: string }) {
  const evidenceQuery = useQuery({
    queryKey: ["evidence", invoiceId],
    queryFn: () => getInvoiceEvidence(invoiceId),
    staleTime: 30_000,
  });

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Network className="h-4 w-4 text-muted-foreground" />
          Evidence trail
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {evidenceQuery.isError ? (
          <ErrorState
            error={evidenceQuery.error}
            title="Could not load the evidence"
            onRetry={() => void evidenceQuery.refetch()}
          />
        ) : evidenceQuery.isPending ? (
          <div className="space-y-2" role="status" aria-label="Loading evidence">
            <div className="h-4 w-52 animate-pulse rounded bg-muted" />
            <div className="h-4 w-72 animate-pulse rounded bg-muted" />
            <div className="h-4 w-40 animate-pulse rounded bg-muted" />
          </div>
        ) : evidenceQuery.data ? (
          <EvidenceView result={evidenceQuery.data} />
        ) : null}
      </CardContent>
    </Card>
  );
}

function EvidenceView({ result }: { result: InvoiceEvidenceOut }) {
  return (
    <>
      <p className="text-xs text-muted-foreground">
        Backend <span className="font-mono">{result.meta.backend}</span>
        {" · "}{result.evidence.length} item{result.evidence.length === 1 ? "" : "s"} retrieved
        {" · "}{result.gaps.length} gap{result.gaps.length === 1 ? "" : "s"}
        {" · "}{result.contradictions.length} contradiction{result.contradictions.length === 1 ? "" : "s"}
        {typeof result.meta.latency_ms === "number" ? ` · ${result.meta.latency_ms} ms` : ""}
      </p>

      {result.gaps.length > 0 ? (
        <ul className="space-y-2">
          {result.gaps.map((gap, index) => (
            <GapItem key={`gap-${index}`} gap={gap} kind="gap" />
          ))}
        </ul>
      ) : null}
      {result.contradictions.length > 0 ? (
        <ul className="space-y-2">
          {result.contradictions.map((gap, index) => (
            <GapItem key={`contradiction-${index}`} gap={gap} kind="contradiction" />
          ))}
        </ul>
      ) : null}

      {result.evidence.length === 0 ? (
        <EmptyState
          icon={Network}
          title="No evidence records matched"
          description="Neither graph relationships nor fuzzy retrieval found corroborating records for this invoice's identifiers."
        />
      ) : (
        <ul className="space-y-2">
          {result.evidence.map((item) => (
            <EvidenceItem key={`${item.entity_type}-${item.entity_id}`} item={item} />
          ))}
        </ul>
      )}

      <p className="text-xs text-muted-foreground">
        Items are machine-recorded retrieval provenance (graph edges and query
        matches) — scores measure how well a record matched, never a fraud
        probability, and a hit is not a verdict on the invoice (R2). Gaps are
        absence statements: the record may simply not exist in VeriPay (R4).
      </p>
    </>
  );
}

const TRUST_LABELS: Record<
  string,
  { label: string; tone: "success" | "warning" | "muted" | "neutral" }
> = {
  verified: { label: "Trusted record", tone: "success" },
  unverified: { label: "Unverified record", tone: "warning" },
  system: { label: "System record", tone: "muted" },
};

function EvidenceItem({ item }: { item: EvidenceItemOut }) {
  const trust = TRUST_LABELS[item.trust_status] ?? {
    label: `Trust: ${item.trust_status}`,
    tone: "neutral" as const,
  };

  return (
    <li className="rounded-md border p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="break-words text-sm font-medium">{item.title}</p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            <span className="font-mono">{item.entity_type}</span>
            {item.matched_field ? ` · matched on ${item.matched_field}` : ""}
            {" · "}
            {item.techniques.join(", ")}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-1.5">
          <StatusBadge presentation={trust} hideDot />
          <span className="text-xs text-muted-foreground" title="Retrieval score (match quality)">
            score {item.retrieval_score.toFixed(3)}
          </span>
        </div>
      </div>
      <p className="mt-1 break-words text-sm text-foreground/90">{item.match_explanation}</p>
      <EvidenceLink entityType={item.entity_type} entityId={item.entity_id} />
    </li>
  );
}

/** Deep-link where a screen exists (vendor); the bare id otherwise — never a
 *  dead button. */
function EvidenceLink({ entityType, entityId }: { entityType: string; entityId: string }) {
  const shortId = entityId.length > 8 ? `${entityId.slice(0, 8)}…` : entityId;
  if (entityType === "vendor") {
    return (
      <Link
        href={`/dashboard/vendors?vendor=${encodeURIComponent(entityId)}`}
        className="mt-1 inline-block text-xs font-medium text-primary hover:underline"
      >
        Open vendor record
      </Link>
    );
  }
  return (
    <span className="mt-1 block font-mono text-xs text-muted-foreground" title={entityId}>
      {entityType} {shortId}
    </span>
  );
}

function GapItem({ gap, kind }: { gap: GraphGapOut; kind: "gap" | "contradiction" }) {
  return (
    <li className="rounded-md border border-dashed p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-medium">
          {kind === "gap" ? "Missing relationship" : "Records disagree"}
          <span className="ml-2 font-mono text-xs text-muted-foreground">{gap.relationship}</span>
        </span>
        <SeverityBadge severity={gap.severity} />
      </div>
      <p className="mt-1 break-words text-sm text-foreground/90">{gap.message}</p>
    </li>
  );
}
