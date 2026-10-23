import {
  LayoutDashboard,
  Users,
  Clock,
  CalendarDays,
  DollarSign,
  FileText,
  Receipt,
  Palmtree,
} from "lucide-react";
import type { NavEntry } from "@/components/shared/sidebar";

export const HR_NAV: NavEntry[] = [
  { label: "Dashboard", href: "/hr/dashboard", icon: LayoutDashboard },
  {
    group: "Workforce",
    icon: Users,
    items: [
      { label: "Employees",      href: "/hr/employees",      icon: Users },
      { label: "Attendance",     href: "/hr/attendance",     icon: Clock },
      { label: "Leave",          href: "/hr/leave",          icon: CalendarDays },
      { label: "Reimbursements", href: "/hr/reimbursements", icon: Receipt },
      { label: "Payroll",        href: "/hr/payroll",        icon: DollarSign },
    ],
  },
  { label: "Reports",  href: "/hr/reports",  icon: FileText },
  { label: "Holidays", href: "/hr/holidays", icon: Palmtree },
];
