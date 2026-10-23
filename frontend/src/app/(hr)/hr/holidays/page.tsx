"use client";

import { HolidaysManager } from "@/components/shared/HolidaysManager";
import { HR_NAV } from "@/components/hr/nav";

export default function HRHolidaysPage() {
  return <HolidaysManager navItems={HR_NAV} portalLabel="HR" />;
}
