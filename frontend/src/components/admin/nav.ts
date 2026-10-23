import {
  LayoutDashboard,
  Users,
  Settings,
  Building2,
  Shield,
  BookOpen,
  ClipboardList,
  Camera,
  Video,
  Palmtree,
  CalendarCheck,
  CalendarDays,
  Receipt,
  DollarSign,
  MonitorSmartphone,
} from "lucide-react";
import type { NavEntry } from "@/components/shared/sidebar";

export const ADMIN_NAV: NavEntry[] = [
  { label: "Dashboard", href: "/admin/dashboard", icon: LayoutDashboard },
  {
    group: "Workforce",
    icon: Users,
    items: [
      { label: "Employees",      href: "/admin/employees",     icon: Users },
      { label: "Attendance",     href: "/admin/attendance",    icon: CalendarCheck },
      { label: "Leave",          href: "/admin/leave",         icon: CalendarDays },
      { label: "Reimbursements", href: "/admin/reimbursements",icon: Receipt },
      { label: "Payroll",        href: "/admin/payroll",       icon: DollarSign },
    ],
  },
  {
    group: "Devices",
    icon: MonitorSmartphone,
    items: [
      { label: "Devices", href: "/admin/devices", icon: Camera },
      { label: "Camera",  href: "/admin/camera",  icon: Video },
    ],
  },
  {
    group: "Organization",
    icon: Building2,
    items: [
      { label: "Branches",    href: "/admin/branches",    icon: Building2 },
      { label: "Departments", href: "/admin/departments", icon: BookOpen },
      { label: "Roles",       href: "/admin/roles",       icon: Shield },
      { label: "Holidays",    href: "/admin/holidays",    icon: Palmtree },
    ],
  },
  {
    group: "System",
    icon: Settings,
    items: [
      { label: "Audit Logs", href: "/admin/audit-logs", icon: ClipboardList },
      { label: "Settings",   href: "/admin/settings",   icon: Settings },
    ],
  },
];
