"use client";

import { useQuery } from "@tanstack/react-query";
import { Navbar } from "@/components/shared/navbar";
import { Sidebar, NavEntry, NavItem } from "@/components/shared/sidebar";
import { apiGet } from "@/lib/api";
import { useAuthStore } from "@/stores/auth-store";

interface PortalLayoutProps {
  children: React.ReactNode;
  navItems: NavEntry[];
  portalLabel: string;
  pageTitle?: string;
}

interface CorrectionItem { correction_status: string }

// Pending-approval counts for the sidebar red badges. A portal shows the items
// awaiting ITS action: managers see the manager stage (scoped to their department by
// the backend); HR/Admin see the HR stage. The badges clear as items are approved.
function usePendingBadges(portalLabel: string) {
  const { isAuthenticated } = useAuthStore();
  const role = portalLabel.toLowerCase();
  const isManager = role === "manager";

  // Manager badge = the manager stage (the backend scopes it to their department).
  // HR/Admin badge = everything still pending — the manager stage AND the HR stage.
  // (Queried per-stage; per_page is capped at 100 by the API, so never exceed it.)
  const leaveM = useQuery({
    queryKey: ["nav-pending", "leave-m", role],
    queryFn: () => apiGet<unknown[]>("/leave/requests", { status: "pending_manager", per_page: 100 }),
    enabled: isAuthenticated,
    staleTime: 30_000,
  });
  const leaveH = useQuery({
    queryKey: ["nav-pending", "leave-h", role],
    queryFn: () => apiGet<unknown[]>("/leave/requests", { status: "pending_hr", per_page: 100 }),
    enabled: isAuthenticated && !isManager,
    staleTime: 30_000,
  });
  const reimbM = useQuery({
    queryKey: ["nav-pending", "reimb-m", role],
    queryFn: () => apiGet<unknown[]>("/reimbursements", { status: "pending_manager", per_page: 100 }),
    enabled: isAuthenticated,
    staleTime: 30_000,
  });
  const reimbH = useQuery({
    queryKey: ["nav-pending", "reimb-h", role],
    queryFn: () => apiGet<unknown[]>("/reimbursements", { status: "pending_hr", per_page: 100 }),
    enabled: isAuthenticated && !isManager,
    staleTime: 30_000,
  });
  const corr = useQuery({
    queryKey: ["nav-pending", "corr", role],
    queryFn: () => apiGet<CorrectionItem[]>("/attendance/corrections"),
    enabled: isAuthenticated,
    staleTime: 30_000,
  });

  const len = (q: { data?: { data: unknown[] | null } }) => (q.data?.data ?? []).length;
  const corrStatuses = isManager ? ["pending"] : ["pending", "pending_hr"];

  return {
    isManager,
    leave: len(leaveM) + (isManager ? 0 : len(leaveH)),
    reimbursements: len(reimbM) + (isManager ? 0 : len(reimbH)),
    corrections: (corr.data?.data ?? []).filter((c) => corrStatuses.includes(c.correction_status)).length,
  };
}

function injectBadges(
  items: NavEntry[],
  b: { isManager: boolean; leave: number; reimbursements: number; corrections: number },
): NavEntry[] {
  const total = b.leave + b.reimbursements + b.corrections;
  const badgeFor = (href: string): number | undefined => {
    if (b.isManager) return href.endsWith("/approvals") ? total || undefined : undefined;
    if (href.includes("/reimbursement")) return b.reimbursements || undefined;
    if (href.includes("/leave")) return b.leave || undefined;
    if (href.includes("/attendance")) return b.corrections || undefined;
    return undefined;
  };
  const mapItem = (i: NavItem): NavItem => ({ ...i, badge: badgeFor(i.href) ?? i.badge });
  return items.map((e) =>
    "items" in e ? { ...e, items: e.items.map(mapItem) } : mapItem(e),
  );
}

export function PortalLayout({
  children,
  navItems,
  portalLabel,
  pageTitle,
}: PortalLayoutProps) {
  const badges = usePendingBadges(portalLabel);
  const items = injectBadges(navItems, badges);
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar items={items} portalLabel={portalLabel} />
      <div className="flex flex-1 flex-col overflow-hidden">
        <Navbar title={pageTitle} />
        <main className="flex-1 overflow-y-auto p-6">{children}</main>
      </div>
    </div>
  );
}
