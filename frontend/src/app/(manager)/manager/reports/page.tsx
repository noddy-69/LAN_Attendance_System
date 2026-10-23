"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Download, FileSpreadsheet, FileText } from "lucide-react";
import { useAuthStore } from "@/stores/auth-store";
import { useMe } from "@/hooks/use-auth";
import { apiGet } from "@/lib/api";
import { ManagerLayout } from "@/components/manager/ManagerLayout";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { API_BASE } from "@/lib/constants";
import { istDateStr, formatMinutes, formatDate } from "@/lib/utils";

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
  source: string;
}

interface DirectReport {
  id: string;
  first_name: string;
  last_name: string;
  employee_code: string;
  role_name: string;
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

function getDefaultRange() {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  return {
    from: `${y}-${m}-01`,
    to: istDateStr(now),
  };
}

export default function ReportsPage() {
  const router = useRouter();
  const { isAuthenticated, token } = useAuthStore();
  const { data: user, isLoading: userLoading } = useMe();

  useEffect(() => {
    if (!isAuthenticated && !userLoading) router.replace("/login");
  }, [isAuthenticated, userLoading, router]);

  const def = getDefaultRange();
  const [fromDate, setFromDate] = useState(def.from);
  const [toDate, setToDate]     = useState(def.to);
  const [applied, setApplied]   = useState(def);
  const [downloading, setDownloading] = useState<"csv" | "xlsx" | null>(null);

  const { data: reportsResp, isLoading: reportsLoading } = useQuery({
    queryKey: ["direct-reports", user?.id],
    queryFn: () => apiGet<DirectReport[]>(`/employees/${user!.id}/direct-reports`),
    enabled: !!user?.id,
  });

  const directReports = (reportsResp?.data ?? []);

  const { data: attResp, isLoading: attLoading } = useQuery({
    queryKey: ["manager-report-att", applied.from, applied.to, directReports.map(e => e.id).join(",")],
    queryFn: async () => {
      const results: DailyAtt[] = [];
      await Promise.all(
        directReports.map(async emp => {
          const res = await apiGet<DailyAtt[]>("/attendance/daily", {
            employee_id: emp.id,
            from_date: applied.from,
            to_date: applied.to,
            per_page: 100,
          });
          if (res.data) results.push(...res.data);
        })
      );
      return results;
    },
    enabled: directReports.length > 0,
  });

  if (userLoading || !user) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
      </div>
    );
  }

  const empMap = new Map<string, DirectReport>();
  for (const emp of directReports) empMap.set(emp.id, emp);

  const rows: Array<{ emp: DirectReport; att: DailyAtt }> = [];
  for (const att of (attResp ?? [])) {
    const emp = empMap.get(att.employee_id);
    if (emp) rows.push({ emp, att });
  }

  rows.sort((a, b) => {
    if (a.emp.last_name !== b.emp.last_name) return a.emp.last_name.localeCompare(b.emp.last_name);
    return a.att.date.localeCompare(b.att.date);
  });

  const isLoading = reportsLoading || attLoading;

  async function downloadReport(format: "csv" | "xlsx") {
    setDownloading(format);
    try {
      const params = new URLSearchParams({
        from_date: applied.from,
        to_date: applied.to,
        format,
      });
      const url = `${API_BASE}/reports/attendance?${params}`;
      const res = await fetch(url, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) throw new Error(`Download failed: ${res.status}`);
      const blob = await res.blob();
      const href = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = href;
      a.download = `team_attendance_${applied.from}_${applied.to}.${format}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(href);
    } catch (err) {
      console.error("Download error:", err);
    } finally {
      setDownloading(null);
    }
  }

  return (
    <ManagerLayout pageTitle="Team Reports">
      <div className="space-y-6">
        <div>
          <h2 className="text-2xl font-bold">Team Reports</h2>
          <p className="text-sm text-muted-foreground">
            Attendance history for your {directReports.length} direct report{directReports.length !== 1 ? "s" : ""}.
          </p>
        </div>

        {/* Filters + export */}
        <div className="flex flex-wrap items-end gap-4 rounded-lg border bg-card p-4 shadow-sm">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="rpt-from">From</Label>
            <Input
              id="rpt-from"
              type="date"
              value={fromDate}
              onChange={e => setFromDate(e.target.value)}
              className="w-40"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="rpt-to">To</Label>
            <Input
              id="rpt-to"
              type="date"
              value={toDate}
              max={istDateStr()}
              onChange={e => setToDate(e.target.value)}
              className="w-40"
            />
          </div>
          <Button
            onClick={() => setApplied({ from: fromDate, to: toDate })}
            disabled={!fromDate || !toDate || fromDate > toDate}
          >
            Apply
          </Button>

          <div className="ml-auto flex gap-2">
            <Button
              variant="outline"
              className="gap-2"
              disabled={!!downloading || rows.length === 0}
              onClick={() => downloadReport("csv")}
            >
              {downloading === "csv" ? (
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
              ) : (
                <FileText className="h-4 w-4" />
              )}
              CSV
            </Button>
            <Button
              variant="outline"
              className="gap-2"
              disabled={!!downloading || rows.length === 0}
              onClick={() => downloadReport("xlsx")}
            >
              {downloading === "xlsx" ? (
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
              ) : (
                <FileSpreadsheet className="h-4 w-4" />
              )}
              Excel
            </Button>
          </div>
        </div>

        {/* Summary line */}
        {!isLoading && rows.length > 0 && (
          <div className="flex flex-wrap gap-6 rounded-lg border bg-card p-4 shadow-sm text-sm">
            <div>
              <span className="text-muted-foreground">Records: </span>
              <span className="font-semibold">{rows.length}</span>
            </div>
            <div>
              <span className="text-muted-foreground">Present days: </span>
              <span className="font-semibold text-green-600 dark:text-green-400">
                {rows.filter(r => ["PRESENT", "LATE", "HALF_DAY"].includes(r.att.status)).length}
              </span>
            </div>
            <div>
              <span className="text-muted-foreground">Late arrivals: </span>
              <span className="font-semibold text-yellow-600 dark:text-yellow-400">
                {rows.filter(r => r.att.is_late).length}
              </span>
            </div>
            <div>
              <span className="text-muted-foreground">Absent: </span>
              <span className="font-semibold text-red-600 dark:text-red-400">
                {rows.filter(r => r.att.status === "ABSENT").length}
              </span>
            </div>
            <div>
              <span className="text-muted-foreground">Period: </span>
              <span className="font-semibold">{formatDate(applied.from)} – {formatDate(applied.to)}</span>
            </div>
          </div>
        )}

        {/* Table */}
        <div className="rounded-lg border bg-card shadow-sm">
          {isLoading ? (
            <div className="space-y-3 p-4">
              {Array.from({ length: 8 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full rounded" />
              ))}
            </div>
          ) : rows.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
              <Download className="mb-2 h-8 w-8 opacity-40" />
              <p className="text-sm">No records found for selected range.</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b bg-muted/40 text-left text-muted-foreground">
                    <th className="px-4 py-3 font-medium">Employee</th>
                    <th className="px-4 py-3 font-medium">Date</th>
                    <th className="px-4 py-3 font-medium">Status</th>
                    <th className="px-4 py-3 font-medium">Check-in</th>
                    <th className="px-4 py-3 font-medium">Check-out</th>
                    <th className="px-4 py-3 font-medium">Work</th>
                    <th className="px-4 py-3 font-medium">Late</th>
                    <th className="px-4 py-3 font-medium">Source</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map(({ emp, att }) => (
                    <tr key={att.id} className="border-b last:border-0 hover:bg-muted/20">
                      <td className="px-4 py-2.5">
                        <div>
                          <p className="font-medium">{emp.first_name} {emp.last_name}</p>
                          <p className="text-xs text-muted-foreground">{emp.employee_code}</p>
                        </div>
                      </td>
                      <td className="px-4 py-2.5 font-mono text-xs">{att.date}</td>
                      <td className="px-4 py-2.5">
                        <StatusBadge status={att.status} />
                      </td>
                      <td className="px-4 py-2.5 font-mono text-xs">
                        {formatTimeIST(att.check_in)}
                      </td>
                      <td className="px-4 py-2.5 font-mono text-xs">
                        {formatTimeIST(att.check_out)}
                      </td>
                      <td className="px-4 py-2.5 text-xs text-muted-foreground">
                        {att.work_minutes != null ? formatMinutes(att.work_minutes) : "—"}
                      </td>
                      <td className="px-4 py-2.5">
                        {att.is_late && att.late_minutes > 0 ? (
                          <span className="text-xs font-medium text-yellow-600 dark:text-yellow-400">
                            {formatMinutes(att.late_minutes)}
                          </span>
                        ) : (
                          <span className="text-xs text-muted-foreground">—</span>
                        )}
                      </td>
                      <td className="px-4 py-2.5">
                        <span className="text-xs capitalize text-muted-foreground">
                          {att.source.replace(/_/g, " ")}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </ManagerLayout>
  );
}
