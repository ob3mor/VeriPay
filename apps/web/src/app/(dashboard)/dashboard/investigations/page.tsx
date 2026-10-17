import { ShieldAlert } from "lucide-react";

import { PlaceholderPage } from "@/components/placeholder-page";

export default function InvestigationsPage() {
  return (
    <PlaceholderPage
      title="Investigations"
      description="Case management for flagged inconsistencies — assignment, notes and human dispositions."
      phase="Phase 5"
      icon={ShieldAlert}
      points={[
        "GET /cases · GET /cases/{id} — cases composed with the triggering assessment (docs/API.md §6).",
        "POST /cases/{id}/assign · POST /cases/{id}/notes — case work for analyst and above.",
        "POST /cases/{id}/close — the disposition is a human decision (R6), reviewer/admin/owner only.",
        "Every list is org-scoped and paginated; another org's case is indistinguishable from a nonexistent one (404 — docs/API.md §5).",
      ]}
    />
  );
}
