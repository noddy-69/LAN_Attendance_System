"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useAuthStore } from "@/stores/auth-store";
import { useMe } from "@/hooks/use-auth";
import { PortalLayout } from "@/components/shared/Layout";
import { ADMIN_NAV } from "@/components/admin/nav";
import { api, apiGet } from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import {
  Users,
  Building2,
  Camera,
  Activity,
  Clock,
} from "lucide-react";

interface HealthData {
  status: string;
  db: string;
  redis: string;
}

interface Device {
  id: string;
  name: string;
  device_type: string;
  branch_name: string;
  is_active: boolean;
  last_heartbeat: string | null;
}

interface AuditLog {
  id: string;
  table_name: string;
  action: string;
  performed_by_name: string | null;
  ip_address: string | null;
  created_at: string;
}

interface Employee {
  id: string;
}

interface Branch {
  id: string;
}

function toIST(utcString: string | null): string {
  if (!utcString) return "—";
  const d = new Date(utcString);
  // Add 5h30m for IST
  const ist = new Date(d.getTime() + 5.5 * 60 * 60 * 1000);
  return ist.toLocaleString("en-IN", { timeZone: "UTC" });
}

function HealthBadge({ status }: { status: string }) {
  const ok = status === "ok" || status === "healthy" || status === "connected";
  return (
    <Badge
      className={
        ok
          ? "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400"
          : "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400"
      }
    >
      {status}
    </Badge>
  );
}

const ACTION_COLORS: Record<string, string> = {
  create: "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400",
  update: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400",
  delete: "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400",
  restore: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400",
};

export default function AdminDashboardPage() {
  const router = useRouter();
  const { isAuthenticated } = useAuthStore();
  const { data: user, isLoading: userLoading } = useMe();

  useEffect(() => {
    if (!isAuthenticated && !userLoading) router.replace("/login");
  }, [isAuthenticated, userLoading, router]);

  // /health returns a bare JSON body (no ApiResponse envelope) — read it directly
  const { data: health, isLoading: healthLoading } = useQuery({
    queryKey: ["health"],
    queryFn: async () => (await api.get<HealthData>("/health")).data,
    refetchInterval: 30_000,
  });

  const { data: employeesResp, isLoading: empLoading } = useQuery({
    queryKey: ["employees-count"],
    queryFn: () => apiGet<Employee[]>("/employees", { per_page: 1 }),
  });

  const { data: branchesResp, isLoading: branchLoading } = useQuery({
    queryKey: ["branches"],
    queryFn: () => apiGet<Branch[]>("/branches"),
  });

  const { data: devicesResp, isLoading: devicesLoading } = useQuery({
    queryKey: ["devices"],
    queryFn: () => apiGet<Device[]>("/devices"),
  });

  const { data: auditResp, isLoading: auditLoading } = useQuery({
    queryKey: ["audit-logs-recent"],
    queryFn: () => apiGet<AuditLog[]>("/system/audit-logs", { per_page: 5 }),
  });

  if (userLoading || !user) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
      </div>
    );
  }

  // Count comes from pagination.total — the page itself only holds 1 row
  const employeeCount = employeesResp?.pagination?.total;
  const employees = employeesResp?.data ?? [];
  const branches = branchesResp?.data ?? [];
  const devices = devicesResp?.data ?? [];
  const auditLogs = auditResp?.data ?? [];

  return (
    <PortalLayout navItems={ADMIN_NAV} portalLabel="Admin" pageTitle="Admin Dashboard">
      <div className="space-y-6">
        <div>
          <h2 className="text-2xl font-bold">Welcome, {user.first_name}!</h2>
          <p className="text-muted-foreground">Admin Portal — full system access</p>
        </div>

        {/* Summary Cards */}
        <div className="grid gap-4 md:grid-cols-3">
          <div className="rounded-lg border bg-card p-6 shadow-sm">
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium text-muted-foreground">Total Employees</p>
              <Users className="h-4 w-4 text-muted-foreground" />
            </div>
            {empLoading ? (
              <Skeleton className="mt-2 h-9 w-16" />
            ) : (
              <p className="mt-2 text-3xl font-bold">{employeeCount ?? (Array.isArray(employees) ? employees.length : "—")}</p>
            )}
          </div>

          <div className="rounded-lg border bg-card p-6 shadow-sm">
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium text-muted-foreground">Total Branches</p>
              <Building2 className="h-4 w-4 text-muted-foreground" />
            </div>
            {branchLoading ? (
              <Skeleton className="mt-2 h-9 w-16" />
            ) : (
              <p className="mt-2 text-3xl font-bold">{Array.isArray(branches) ? branches.length : "—"}</p>
            )}
          </div>

          <div className="rounded-lg border bg-card p-6 shadow-sm">
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium text-muted-foreground">Total Devices</p>
              <Camera className="h-4 w-4 text-muted-foreground" />
            </div>
            {devicesLoading ? (
              <Skeleton className="mt-2 h-9 w-16" />
            ) : (
              <p className="mt-2 text-3xl font-bold">{Array.isArray(devices) ? devices.length : "—"}</p>
            )}
          </div>
        </div>

        {/* Health Status */}
        <div className="rounded-lg border bg-card p-6 shadow-sm">
          <div className="mb-4 flex items-center gap-2">
            <Activity className="h-5 w-5 text-muted-foreground" />
            <h3 className="text-lg font-semibold">System Health</h3>
          </div>
          {healthLoading ? (
            <div className="flex gap-4">
              <Skeleton className="h-6 w-24" />
              <Skeleton className="h-6 w-24" />
              <Skeleton className="h-6 w-24" />
            </div>
          ) : health ? (
            <div className="flex flex-wrap gap-4">
              <div className="flex items-center gap-2">
                <span className="text-sm text-muted-foreground">API:</span>
                <HealthBadge status={health.status} />
              </div>
              <div className="flex items-center gap-2">
                <span className="text-sm text-muted-foreground">Database:</span>
                <HealthBadge status={health.db} />
              </div>
              <div className="flex items-center gap-2">
                <span className="text-sm text-muted-foreground">Redis:</span>
                <HealthBadge status={health.redis} />
              </div>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">Health data unavailable</p>
          )}
        </div>

        <div className="grid gap-6 lg:grid-cols-2">
          {/* Recent Audit Logs */}
          <div className="rounded-lg border bg-card p-6 shadow-sm">
            <h3 className="mb-4 text-lg font-semibold">Recent Audit Logs</h3>
            {auditLoading ? (
              <div className="space-y-3">
                {Array.from({ length: 5 }).map((_, i) => (
                  <Skeleton key={i} className="h-8 w-full" />
                ))}
              </div>
            ) : auditLogs.length === 0 ? (
              <p className="text-sm text-muted-foreground">No audit logs found.</p>
            ) : (
              <div className="space-y-3">
                {auditLogs.map((log) => (
                  <div key={log.id} className="flex items-center justify-between gap-2 text-sm">
                    <div className="flex items-center gap-2 min-w-0">
                      <span
                        className={`inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-xs font-medium ${
                          ACTION_COLORS[log.action] ?? "bg-gray-100 text-gray-700"
                        }`}
                      >
                        {log.action}
                      </span>
                      <span className="truncate font-medium">{log.table_name}</span>
                      <span className="truncate text-muted-foreground">
                        by {log.performed_by_name ?? "system"}
                      </span>
                    </div>
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {toIST(log.created_at)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Device Status */}
          <div className="rounded-lg border bg-card p-6 shadow-sm">
            <div className="mb-4 flex items-center gap-2">
              <Clock className="h-5 w-5 text-muted-foreground" />
              <h3 className="text-lg font-semibold">Device Heartbeats</h3>
            </div>
            {devicesLoading ? (
              <div className="space-y-3">
                {Array.from({ length: 4 }).map((_, i) => (
                  <Skeleton key={i} className="h-8 w-full" />
                ))}
              </div>
            ) : devices.length === 0 ? (
              <p className="text-sm text-muted-foreground">No devices configured.</p>
            ) : (
              <div className="space-y-3">
                {devices.map((device) => (
                  <div key={device.id} className="flex items-center justify-between gap-2 text-sm">
                    <div className="flex items-center gap-2 min-w-0">
                      <span
                        className={`inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-xs font-medium ${
                          device.is_active
                            ? "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400"
                            : "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400"
                        }`}
                      >
                        {device.is_active ? "active" : "inactive"}
                      </span>
                      <span className="truncate font-medium">{device.name}</span>
                      <span className="truncate text-muted-foreground">{device.branch_name}</span>
                    </div>
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {device.last_heartbeat ? toIST(device.last_heartbeat) : "Never"}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </PortalLayout>
  );
}
