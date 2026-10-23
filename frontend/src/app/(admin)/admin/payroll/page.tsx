"use client";

import { PayrollManagement } from "@/components/shared/PayrollManagement";
import { ADMIN_NAV } from "@/components/admin/nav";

export default function AdminPayrollPage() {
  return <PayrollManagement navItems={ADMIN_NAV} portalLabel="Admin" />;
}
