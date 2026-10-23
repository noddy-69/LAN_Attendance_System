"use client";

import { EmployeeManagement } from "@/components/shared/EmployeeManagement";
import { ADMIN_NAV } from "@/components/admin/nav";

export default function EmployeesPage() {
  return <EmployeeManagement navItems={ADMIN_NAV} portalLabel="Admin" />;
}
