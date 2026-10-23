"use client";

import { LeaveManagement } from "@/components/shared/LeaveManagement";
import { HR_NAV } from "@/components/hr/nav";

export default function HRLeavePage() {
  return <LeaveManagement navItems={HR_NAV} portalLabel="HR" />;
}
