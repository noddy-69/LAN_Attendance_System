"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Clock, User } from "lucide-react";
import { useAuthStore } from "@/stores/auth-store";
import { useMe } from "@/hooks/use-auth";
import { apiGet } from "@/lib/api";
import { ManagerLayout } from "@/components/manager/ManagerLayout";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { Skeleton } from "@/components/ui/skeleton";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { istDateStr, formatMinutes } from "@/lib/utils";

interface DirectReport {
  id: string;
  employee_code: string;
  first_name: string;
  last_name: string;
  email: string;
  role_name: string;
  is_active: boolean;
}

interface DailyAtt {
  id: string;
  employee_id: string;
  date: string;
  check_in: string | null;
  check_out: string | null;
  work_minutes: number | null;
  late_minutes: number;
  is_late: boolean;
  status: string;
}

function formatTimeIST(utc: string | null): string {
  if (!utc) return "—";
  return new Date(utc).toLocaleTimeString("en-IN", {
    timeZone: "Asia/Kolkata",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export default function ManagerDashboardPage() {
  const router = useRouter();
  const { isAuthenticated } = useAuthStore();
  const { data: user, isLoading: userLoading } = useMe();

  useEffect(() => {
    if (!isAuthenticated && !userLoading) router.replace("/login");
  }, [isAuthenticated, userLoading, router]);

  const today = istDateStr();

  const { data: reportsResp, isLoading: reportsLoading } = useQuery({
    queryKey: ["direct-reports", user?.id],
    queryFn: () => apiGet<DirectReport[]>(`/employees/${user!.id}/direct-reports`),
    enabled: !!user?.id,
  });

  const { data: attResp, isLoading: attLoading } = useQuery({
    queryKey: ["manager-today-att", today],
    queryFn: () =>
      apiGet<DailyAtt[]>("/attendance/daily", {
        from_date: today,
        to_date: today,
        per_page: 100,
      }),
    enabled: !!user?.id,
    refetchInterval: 60_000,
  });

  if (userLoading || !user) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
      </div>
    );
  }

  const directReports = (reportsResp?.data ?? []).filter(e => e.is_active);
  const attendance = attResp?.data ?? [];

  const attMap = new Map<string, DailyAtt>();
  for (const rec of attendance) attMap.set(rec.employee_id, rec);

  const teamCards = directReports
    .map(emp => ({ emp, att: attMap.get(emp.id) ?? null }))
    .sort((a, b) => {
      const aLate = a.att?.is_late ? (a.att.late_minutes ?? 0) : 0;
      const bLate = b.att?.is_late ? (b.att.late_minutes ?? 0) : 0;
      if (aLate !== bLate) return bLate - aLate;
      const aIn = a.att?.check_in ? 1 : 0;
      const bIn = b.att?.check_in ? 1 : 0;
      return bIn - aIn;
    });

  const presentCount = teamCards.filter(c =>
    c.att && ["PRESENT", "LATE", "HALF_DAY"].includes(c.att.status)
  ).length;
  const lateCount  = teamCards.filter(c => c.att?.is_late).length;
  const absentCount = teamCards.filter(c => !c.att || c.att.status === "ABSENT").length;

  const isLoading = reportsLoading || attLoading;

  return (
    <ManagerLayout pageTitle="Team Dashboard">
      <div className="space-y-6">
        {/* Header */}
        <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-2xl font-bold">Good day, {user.first_name}!</h2>
            <p className="text-sm text-muted-foreground">
              {new Date().toLocaleDateString("en-IN", {
                weekday: "long",
                day: "2-digit",
                month: "long",
                year: "numeric",
              })}
            </p>
          </div>
          <p className="text-sm font-medium text-muted-foreground">
            Your team: {directReports.length} member{directReports.length !== 1 ? "s" : ""}
          </p>
        </div>

        {/* Summary */}
        <div className="grid gap-4 sm:grid-cols-3">
          <div className="rounded-lg border bg-card p-4 shadow-sm">
            <p className="text-sm text-muted-foreground">Present Today</p>
            <p className="mt-1 text-3xl font-bold text-green-600 dark:text-green-400">
              {isLoading ? <Skeleton className="h-9 w-10 inline-block" /> : presentCount}
            </p>
          </div>
          <div className="rounded-lg border bg-card p-4 shadow-sm">
            <p className="text-sm text-muted-foreground">Late Arrivals</p>
            <p className="mt-1 text-3xl font-bold text-yellow-600 dark:text-yellow-400">
              {isLoading ? <Skeleton className="h-9 w-10 inline-block" /> : lateCount}
            </p>
          </div>
          <div className="rounded-lg border bg-card p-4 shadow-sm">
            <p className="text-sm text-muted-foreground">Absent / No Data</p>
            <p className="mt-1 text-3xl font-bold text-red-600 dark:text-red-400">
              {isLoading ? <Skeleton className="h-9 w-10 inline-block" /> : absentCount}
            </p>
          </div>
        </div>

        {/* Cards */}
        <div>
          <h3 className="mb-4 text-lg font-semibold">
            Today&apos;s Attendance
            {lateCount > 0 && (
              <span className="ml-2 text-sm font-normal text-yellow-600 dark:text-yellow-400">
                — {lateCount} late arrival{lateCount !== 1 ? "s" : ""} sorted by delay
              </span>
            )}
          </h3>

          {isLoading ? (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-28 rounded-xl" />
              ))}
            </div>
          ) : teamCards.length === 0 ? (
            <div className="flex flex-col items-center justify-center rounded-xl border border-dashed py-12 text-muted-foreground">
              <User className="mb-2 h-8 w-8 opacity-40" />
              <p className="text-sm">No direct reports found.</p>
              <p className="mt-1 text-xs opacity-60">
                Employees reporting to you will appear here.
              </p>
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {teamCards.map(({ emp, att }) => (
                <div
                  key={emp.id}
                  className={`flex items-start gap-3 rounded-xl border bg-card p-4 shadow-sm transition-colors ${
                    att?.is_late
                      ? "border-yellow-200 dark:border-yellow-900/50"
                      : att?.check_in
                      ? "border-green-200 dark:border-green-900/50"
                      : "border-red-200 dark:border-red-900/50"
                  }`}
                >
                  <Avatar className="h-10 w-10 shrink-0">
                    <AvatarFallback className="text-xs">
                      {emp.first_name[0]}{emp.last_name[0]}
                    </AvatarFallback>
                  </Avatar>

                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold">
                      {emp.first_name} {emp.last_name}
                    </p>
                    <p className="truncate text-xs text-muted-foreground">{emp.role_name}</p>

                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <StatusBadge status={att?.status ?? "ABSENT"} />
                      {att?.is_late && att.late_minutes > 0 && (
                        <span className="flex items-center gap-1 text-xs font-medium text-yellow-600 dark:text-yellow-400">
                          <AlertTriangle className="h-3 w-3" />
                          {formatMinutes(att.late_minutes)} late
                        </span>
                      )}
                    </div>

                    <div className="mt-1 flex items-center gap-1 text-xs text-muted-foreground">
                      <Clock className="h-3 w-3 shrink-0" />
                      {att?.check_in
                        ? `In: ${formatTimeIST(att.check_in)}`
                        : "Not checked in"}
                      {att?.check_out && (
                        <span className="ml-1">
                          · Out: {formatTimeIST(att.check_out)}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </ManagerLayout>
  );
}
