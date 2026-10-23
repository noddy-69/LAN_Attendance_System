"use client";

import { EmployeeManagement } from "@/components/shared/EmployeeManagement";
import { HR_NAV } from "@/components/hr/nav";

export default function HREmployeesPage() {
  return <EmployeeManagement navItems={HR_NAV} portalLabel="HR" />;
}
