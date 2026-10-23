"use client";

import { PortalLayout } from "@/components/shared/Layout";
import { HR_NAV } from "@/components/hr/nav";
import { NotificationsView } from "@/components/shared/NotificationsView";

export default function HRNotificationsPage() {
  return (
    <PortalLayout navItems={HR_NAV} portalLabel="HR" pageTitle="Notifications">
      <NotificationsView />
    </PortalLayout>
  );
}
