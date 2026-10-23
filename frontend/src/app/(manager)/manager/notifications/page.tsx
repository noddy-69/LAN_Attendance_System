"use client";

import { ManagerLayout } from "@/components/manager/ManagerLayout";
import { NotificationsView } from "@/components/shared/NotificationsView";

export default function ManagerNotificationsPage() {
  return (
    <ManagerLayout pageTitle="Notifications">
      <NotificationsView />
    </ManagerLayout>
  );
}
