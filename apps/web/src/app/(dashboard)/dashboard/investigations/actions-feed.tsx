"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { History, Send } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { addReviewAction, listReviewActions } from "@/lib/api";
import type { ReviewActionOut } from "@veripay/api-contracts";

import { mutationMessage } from "./api-extras";

export interface ActionsFeedProps {
  caseId: string;
  canContribute: boolean;
}

const ACTION_TYPE_LABELS: Record<string, string> = {
  comment: "Comment",
  decision: "Decision",
  assignment: "Assignment",
  status_change: "Status change",
  field_verified: "Field verified",
  account_verified: "Account verified",
  account_change_approved: "Account change approved",
  account_change_rejected: "Account change rejected",
};

/**
 * Review actions feed (R6 audit trail of the case's human work): every
 * assignment, comment, field verification, account decision and close
 * decision the API has recorded, plus a comment box for contributor roles.
 *
 * Note: the wire schema of a review action carries no timestamp, so entries
 * render without one rather than guessing.
 */
export function ActionsFeed({ caseId, canContribute }: ActionsFeedProps) {
  const queryClient = useQueryClient();
  const actionsQuery = useQuery({
    queryKey: ["actions", caseId],
    queryFn: () => listReviewActions(caseId),
  });

  const [draft, setDraft] = useState("");
  const commentMutation = useMutation({
    mutationFn: () =>
      addReviewAction(caseId, { action_type: "comment", body: draft.trim() }),
    onSuccess: () => {
      setDraft("");
      void queryClient.invalidateQueries({ queryKey: ["actions", caseId] });
    },
  });

  const submitComment = () => {
    if (draft.trim().length === 0) return;
    commentMutation.mutate();
  };

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <History className="h-4 w-4 text-muted-foreground" />
          Review actions
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {actionsQuery.isError ? (
          <ErrorState
            error={actionsQuery.error}
            title="Could not load the review actions"
            onRetry={() => void actionsQuery.refetch()}
          />
        ) : actionsQuery.isPending ? (
          <div className="h-20 animate-pulse rounded bg-muted" role="status" aria-label="Loading review actions" />
        ) : (actionsQuery.data ?? []).length === 0 ? (
          <EmptyState
            icon={History}
            title="No review actions recorded yet"
            description="Assignments, comments, field verifications and decisions on this case will appear here as they are recorded."
          />
        ) : (
          <ol className="space-y-3">
            {(actionsQuery.data ?? []).map((action) => (
              <ActionItem key={action.id} action={action} />
            ))}
          </ol>
        )}

        {canContribute ? (
          <div className="space-y-2 border-t pt-4">
            <label
              htmlFor={`action-comment-${caseId}`}
              className="text-sm font-medium"
            >
              Add a comment
            </label>
            <textarea
              id={`action-comment-${caseId}`}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              rows={3}
              placeholder="What you checked, what you found, what remains open — visible to every member of the organization."
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            />
            <div className="flex flex-wrap items-center gap-3">
              <Button
                size="sm"
                onClick={submitComment}
                disabled={draft.trim().length === 0 || commentMutation.isPending}
              >
                <Send />
                Post comment
              </Button>
              {commentMutation.isError ? (
                <span className="text-xs text-destructive">
                  {mutationMessage(commentMutation.error, "The comment could not be saved.")}
                </span>
              ) : null}
            </div>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function ActionItem({ action }: { action: ReviewActionOut }) {
  const label = ACTION_TYPE_LABELS[action.action_type] ?? action.action_type;
  const system = action.actor_user_id === null;
  return (
    <li className="rounded-md border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span
          className={
            system
              ? "rounded-full border border-border bg-muted px-2 py-0.5 text-xs text-muted-foreground"
              : "rounded-full border border-primary/20 bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary"
          }
        >
          {label}
          {system ? " · system" : ""}
        </span>
        {action.actor_user_id ? (
          <span className="font-mono text-xs text-muted-foreground" title={action.actor_user_id}>
            member {action.actor_user_id.slice(0, 8)}
          </span>
        ) : null}
      </div>
      <p className="mt-1.5 break-words whitespace-pre-wrap text-sm">{action.body}</p>
    </li>
  );
}
