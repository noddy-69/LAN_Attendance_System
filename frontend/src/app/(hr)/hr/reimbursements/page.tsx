"use client";

import { ReimbursementManagement } from "@/components/shared/ReimbursementManagement";
import { HR_NAV } from "@/components/hr/nav";

export default function HRReimbursementsPage() {
  return <ReimbursementManagement navItems={HR_NAV} portalLabel="HR" />;
}
