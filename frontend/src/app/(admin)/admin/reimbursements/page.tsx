"use client";

import { ReimbursementManagement } from "@/components/shared/ReimbursementManagement";
import { ADMIN_NAV } from "@/components/admin/nav";

export default function AdminReimbursementsPage() {
  return <ReimbursementManagement navItems={ADMIN_NAV} portalLabel="Admin" />;
}
