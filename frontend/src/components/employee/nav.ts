import { Home, ScanFace, Clock, CalendarDays, Receipt, PenLine, User } from "lucide-react";
import type { NavItem } from "@/components/shared/sidebar";

export const EMP_NAV: NavItem[] = [
  { label: "Home",        href: "/employee/dashboard",   icon: Home },
  { label: "Check In",    href: "/employee/checkin",     icon: ScanFace },
  { label: "Attendance",  href: "/employee/attendance",  icon: Clock },
  { label: "Leave",       href: "/employee/leave",       icon: CalendarDays },
  { label: "Claims",      href: "/employee/claims",      icon: Receipt },
  { label: "Corrections", href: "/employee/corrections", icon: PenLine },
  { label: "Profile",     href: "/employee/profile",     icon: User },
];
