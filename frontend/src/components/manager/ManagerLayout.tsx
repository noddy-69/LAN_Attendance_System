"use client";

import { PortalLayout } from "@/components/shared/Layout";
import { MANAGER_NAV_BASE } from "@/components/manager/nav";

interface ManagerLayoutProps {
  children: React.ReactNode;
  pageTitle?: string;
}

export function ManagerLayout({ children, pageTitle }: ManagerLayoutProps) {
  // Pending-approval badges are injected centrally by PortalLayout (department-scoped).
  return (
    <PortalLayout navItems={MANAGER_NAV_BASE} portalLabel="Manager" pageTitle={pageTitle}>
      {children}
    </PortalLayout>
  );
}
