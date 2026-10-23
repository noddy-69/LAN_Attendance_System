"use client";

import { LeaveManagement } from "@/components/shared/LeaveManagement";
import { ADMIN_NAV } from "@/components/admin/nav";

export default function AdminLeavePage() {
  return <LeaveManagement navItems={ADMIN_NAV} portalLabel="Admin" />;
}
