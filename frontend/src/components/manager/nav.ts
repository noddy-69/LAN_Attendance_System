import { LayoutDashboard, Users, CheckSquare, FileText } from "lucide-react";
import type { NavItem } from "@/components/shared/sidebar";

export const MANAGER_NAV_BASE: NavItem[] = [
  { label: "Dashboard", href: "/manager/dashboard", icon: LayoutDashboard },
  { label: "Team",      href: "/manager/team",      icon: Users },
  { label: "Approvals", href: "/manager/approvals", icon: CheckSquare },
  { label: "Reports",   href: "/manager/reports",   icon: FileText },
];
