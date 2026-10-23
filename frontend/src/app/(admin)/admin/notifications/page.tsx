"use client";

import { PortalLayout } from "@/components/shared/Layout";
import { ADMIN_NAV } from "@/components/admin/nav";
import { NotificationsView } from "@/components/shared/NotificationsView";

export default function AdminNotificationsPage() {
  return (
    <PortalLayout navItems={ADMIN_NAV} portalLabel="Admin" pageTitle="Notifications">
      <NotificationsView />
    </PortalLayout>
  );
}
