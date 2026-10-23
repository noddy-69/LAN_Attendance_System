"use client";

import { HolidaysManager } from "@/components/shared/HolidaysManager";
import { ADMIN_NAV } from "@/components/admin/nav";

export default function AdminHolidaysPage() {
  return <HolidaysManager navItems={ADMIN_NAV} portalLabel="Admin" />;
}
