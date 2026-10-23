"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { CalendarDays, ChevronRight } from "lucide-react";
import { useAuthStore } from "@/stores/auth-store";
import { useMe } from "@/hooks/use-auth";
import { apiGet } from "@/lib/api";
import { ManagerLayout } from "@/components/manager/ManagerLayout";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { istDateStr, formatMinutes, formatDate } from "@/lib/utils";

interface DirectReport {
  id: string;
  employee_code: string;
  first_name: string;
  last_name: string;
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

function getDefaultRange() {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  return {
    from: `${y}-${m}-01`,
    to: istDateStr(now),
  };
}

function getDatesInRange(start: string, end: string): string[] {
  const dates: string[] = [];
  const cur = new Date(start + "T00:00:00");
  const endDate = new Date(end + "T00:00:00");
  while (cur <= endDate) {
    dates.push(istDateStr(cur));
    cur.setDate(cur.getDate() + 1);
  }
  return dates;
}

interface CalendarModalProps {
  open: boolean;
  onClose: () => void;
  employee: DirectReport | null;
  records: DailyAtt[];
  fromDate: string;
  toDate: string;
}

function CalendarModal({ open, onClose, employee, records, fromDate, toDate }: CalendarModalProps) {
  if (!employee) return null;

  const attMap = new Map<string, DailyAtt>();
  for (const r of records) attMap.set(r.date, r);

  const dates = getDatesInRange(fromDate, toDate);

  return (
    <Dialog open={open} onOpenChange={v => !v && onClose()}>
      <DialogContent className="max-h-[80vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {employee.first_name} {employee.last_name} — Attendance Calendar
          </DialogTitle>
          <p className="text-sm text-muted-foreground">
            {formatDate(fromDate)} – {formatDate(toDate)}
          </p>
        </DialogHeader>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-muted-foreground">
                <th className="pb-2 pr-4 font-medium">Date</th>
                <th className="pb-2 pr-4 font-medium">Day</th>
                <th className="pb-2 pr-4 font-medium">Status</th>
                <th className="pb-2 pr-4 font-medium">Check-in</th>
                <th className="pb-2 pr-4 font-medium">Check-out</th>
                <th className="pb-2 font-medium">Work</th>
              </tr>
            </thead>
            <tbody>
              {dates.map(date => {
                const rec = attMap.get(date);
                const dayName = new Date(date + "T00:00:00").toLocaleDateString("en-IN", { weekday: "short" });
                const isWeekend = ["Sat", "Sun"].includes(dayName);
                return (
                  <tr
                    key={date}
                    className={`border-b last:border-0 ${isWeekend ? "text-muted-foreground" : ""}`}
                  >
                    <td className="py-2 pr-4 font-mono text-xs">{date}</td>
                    <td className="py-2 pr-4">{dayName}</td>
                    <td className="py-2 pr-4">
                      {rec ? (
                        <StatusBadge status={rec.status} />
                      ) : isWeekend ? (
                        <StatusBadge status="WEEKEND" />
                      ) : (
                        <span className="text-xs text-muted-foreground">—</span>
                      )}
                    </td>
                    <td className="py-2 pr-4 font-mono text-xs">
                      {formatTimeIST(rec?.check_in ?? null)}
                    </td>
                    <td className="py-2 pr-4 font-mono text-xs">
                      {formatTimeIST(rec?.check_out ?? null)}
                    </td>
                    <td className="py-2 text-xs">
                      {rec?.work_minutes != null ? formatMinutes(rec.work_minutes) : "—"}
                      {rec?.is_late && rec.late_minutes > 0 && (
                        <span className="ml-1 text-yellow-600 dark:text-yellow-400">
                          +{formatMinutes(rec.late_minutes)} late
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export default function TeamPage() {
  const router = useRouter();
  const { isAuthenticated } = useAuthStore();
  const { data: user, isLoading: userLoading } = useMe();

  useEffect(() => {
    if (!isAuthenticated && !userLoading) router.replace("/login");
  }, [isAuthenticated, userLoading, router]);

  const def = getDefaultRange();
  const [fromDate, setFromDate] = useState(def.from);
  const [toDate, setToDate]     = useState(def.to);
  const [applied, setApplied]   = useState(def);
  const [calOpen, setCalOpen]   = useState(false);
  const [selectedEmp, setSelectedEmp] = useState<DirectReport | null>(null);

  const { data: reportsResp, isLoading: reportsLoading } = useQuery({
    queryKey: ["direct-reports", user?.id],
    queryFn: () => apiGet<DirectReport[]>(`/employees/${user!.id}/direct-reports`),
    enabled: !!user?.id,
  });

  // Fetch attendance per team member for the applied range
  const directReports = (reportsResp?.data ?? []).filter(e => e.is_active);

  const { data: attResp, isLoading: attLoading } = useQuery({
    queryKey: ["manager-team-att", applied.from, applied.to, directReports.map(e => e.id).join(",")],
    queryFn: async () => {
      // Fetch attendance for each direct report
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

  const allAtt = attResp ?? [];

  // Build per-employee summary
  const empAttMap = new Map<string, DailyAtt[]>();
  for (const rec of allAtt) {
    const list = empAttMap.get(rec.employee_id) ?? [];
    list.push(rec);
    empAttMap.set(rec.employee_id, list);
  }

  const rows = directReports.map(emp => {
    const recs = empAttMap.get(emp.id) ?? [];
    const present = recs.filter(r => ["PRESENT", "LATE", "HALF_DAY"].includes(r.status)).length;
    const late    = recs.filter(r => r.is_late).length;
    const absent  = recs.filter(r => r.status === "ABSENT").length;
    const onLeave = recs.filter(r => r.status === "ON_LEAVE").length;
    const totalWork = recs.reduce((s, r) => s + (r.work_minutes ?? 0), 0);
    return { emp, recs, present, late, absent, onLeave, totalWork };
  });

  const isLoading = reportsLoading || attLoading;

  function openCalendar(emp: DirectReport) {
    setSelectedEmp(emp);
    setCalOpen(true);
  }

  return (
    <ManagerLayout pageTitle="Team Attendance">
      <div className="space-y-6">
        <div className="flex items-center gap-2">
          <CalendarDays className="h-5 w-5 text-muted-foreground" />
          <h2 className="text-2xl font-bold">Team Attendance</h2>
          <span className="ml-1 text-sm text-muted-foreground">
            — {directReports.length} member{directReports.length !== 1 ? "s" : ""}
          </span>
        </div>

        {/* Date range filter */}
        <div className="flex flex-wrap items-end gap-4 rounded-lg border bg-card p-4 shadow-sm">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="from-date">From</Label>
            <Input
              id="from-date"
              type="date"
              value={fromDate}
              onChange={e => setFromDate(e.target.value)}
              className="w-40"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="to-date">To</Label>
            <Input
              id="to-date"
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
        </div>

        {/* Table */}
        <div className="rounded-lg border bg-card shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-muted/40 text-left text-muted-foreground">
                  <th className="px-4 py-3 font-medium">Employee</th>
                  <th className="px-4 py-3 text-center font-medium">Present</th>
                  <th className="px-4 py-3 text-center font-medium">Late</th>
                  <th className="px-4 py-3 text-center font-medium">Absent</th>
                  <th className="px-4 py-3 text-center font-medium">On Leave</th>
                  <th className="px-4 py-3 text-center font-medium">Total Hours</th>
                  <th className="px-4 py-3 text-center font-medium">Calendar</th>
                </tr>
              </thead>
              <tbody>
                {isLoading ? (
                  Array.from({ length: 5 }).map((_, i) => (
                    <tr key={i} className="border-b">
                      {Array.from({ length: 7 }).map((__, j) => (
                        <td key={j} className="px-4 py-3">
                          <Skeleton className="h-5 w-full" />
                        </td>
                      ))}
                    </tr>
                  ))
                ) : rows.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-8 text-center text-muted-foreground">
                      No team members found.
                    </td>
                  </tr>
                ) : (
                  rows.map(({ emp, recs, present, late, absent, onLeave, totalWork }) => (
                    <tr key={emp.id} className="border-b last:border-0 hover:bg-muted/20">
                      <td className="px-4 py-3">
                        <div>
                          <p className="font-medium">{emp.first_name} {emp.last_name}</p>
                          <p className="text-xs text-muted-foreground">{emp.role_name}</p>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-center">
                        <span className="font-medium text-green-600 dark:text-green-400">
                          {present}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-center">
                        <span className={`font-medium ${late > 0 ? "text-yellow-600 dark:text-yellow-400" : ""}`}>
                          {late}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-center">
                        <span className={`font-medium ${absent > 0 ? "text-red-600 dark:text-red-400" : ""}`}>
                          {absent}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-center">
                        <span className="font-medium text-blue-600 dark:text-blue-400">
                          {onLeave}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-center text-muted-foreground">
                        {formatMinutes(totalWork)}
                      </td>
                      <td className="px-4 py-3 text-center">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => openCalendar(emp)}
                          disabled={recs.length === 0}
                          className="gap-1"
                        >
                          View <ChevronRight className="h-3 w-3" />
                        </Button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>

        <CalendarModal
          open={calOpen}
          onClose={() => setCalOpen(false)}
          employee={selectedEmp}
          records={selectedEmp ? (empAttMap.get(selectedEmp.id) ?? []) : []}
          fromDate={applied.from}
          toDate={applied.to}
        />
      </div>
    </ManagerLayout>
  );
}
