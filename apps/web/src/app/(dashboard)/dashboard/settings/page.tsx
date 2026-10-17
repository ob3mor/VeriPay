import { Settings } from "lucide-react";

import { PlaceholderPage } from "@/components/placeholder-page";

export default function SettingsPage() {
  return (
    <PlaceholderPage
      title="Settings"
      description="Organization and user administration, plus the audit trail — admin/owner territory."
      phase="Phase 6"
      icon={Settings}
      points={[
        "Org/user administration — admin/owner roles only (docs/API.md §5 role × action matrix).",
        "GET /audit-logs — paginated, owner/admin only, with request_id correlation back to API responses (docs/API.md §6).",
        "Until then, your account details (email, role, organization) are shown live on the Overview page via GET /auth/me.",
        "Workspaces are created at registration — joining an existing organization arrives later with invites.",
      ]}
    />
  );
}
