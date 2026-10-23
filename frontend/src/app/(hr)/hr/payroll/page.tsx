"use client";

import { PayrollManagement } from "@/components/shared/PayrollManagement";
import { HR_NAV } from "@/components/hr/nav";

export default function HRPayrollPage() {
  return <PayrollManagement navItems={HR_NAV} portalLabel="HR" />;
}
