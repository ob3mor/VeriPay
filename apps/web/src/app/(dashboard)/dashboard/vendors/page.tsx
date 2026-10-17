import { Building2 } from "lucide-react";

import { PlaceholderPage } from "@/components/placeholder-page";

export default function VendorsPage() {
  return (
    <PlaceholderPage
      title="Vendors"
      description="Vendor master data and trusted bank accounts — org-scoped, with human-only bank account verification."
      phase="Phase 3"
      icon={Building2}
      points={[
        "POST /vendors · GET /vendors — create and list vendors for your organization (docs/API.md §6).",
        "POST /vendors/{id}/trusted-accounts — pay-to accounts per vendor, tenant-prefixed storage.",
        "New bank accounts start as pending and require independent, human verification before they can be trusted (invariant R5) — never automatic.",
        "POST /vendors/{id}/trusted-accounts/{account_id}/revoke — revocation is reviewer/admin/owner only.",
        "Verification provenance (method/reference) is visible only to reviewer+ roles in investigation surfaces (docs/API.md §5.8).",
      ]}
    />
  );
}
