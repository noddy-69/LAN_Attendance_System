"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Camera } from "lucide-react";
import { useAuthStore } from "@/stores/auth-store";
import { useMe } from "@/hooks/use-auth";
import { apiGet } from "@/lib/api";
import { EmployeeLayout } from "@/components/employee/EmployeeLayout";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { ProofImageModal } from "@/components/shared/ProofImageModal";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import {
  Sheet, SheetContent, SheetHeader, SheetTitle,
} from "@/components/ui/sheet";
import { istDateStr, formatMinutes } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

interface DailyAtt {
  id: string;
  employee_id: string;
  date: string;
  check_in: string | null;
  check_out: string | null;
  work_minutes: number | null;
  overtime_minutes: number;
  late_minutes: number;
  is_late: boolean;
  status: string;
  source: string;
}

interface ProofItem {
  id: string;
  proof_type: "entry" | "exit";
  url: string;
  captured_at: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const DAY_LABELS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];
const MONTH_NAMES = [
  "January","February","March","April","May","June",
  "July","August","September","October","November","December",
];

// Map status → light background color for calendar cells
const CELL_BG: Record<string, string> = {
  PRESENT:            "bg-green-100 text-green-900 dark:bg-green-900/40 dark:text-green-300",
  LATE:               "bg-yellow-100 text-yellow-900 dark:bg-yellow-900/40 dark:text-yellow-300",
  ABSENT:             "bg-red-100 text-red-900 dark:bg-red-900/40 dark:text-red-300",
  HALF_DAY:           "bg-orange-100 text-orange-900 dark:bg-orange-900/40 dark:text-orange-300",
  ON_LEAVE:           "bg-blue-100 text-blue-900 dark:bg-blue-900/40 dark:text-blue-300",
  HOLIDAY:            "bg-purple-100 text-purple-900 dark:bg-purple-900/40 dark:text-purple-300",
  WEEKEND:            "bg-transparent text-muted-foreground",
  PENDING_CORRECTION: "bg-pink-100 text-pink-900 dark:bg-pink-900/40 dark:text-pink-300",
};

function timeIST(utc: string | null) {
  if (!utc) return "—";
  return new Date(utc).toLocaleTimeString("en-IN", {
    timeZone: "Asia/Kolkata",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function toISO(date: Date) {
  return istDateStr(date);
}

// ── Legend ────────────────────────────────────────────────────────────────────

const LEGEND = [
  { status: "PRESENT",  label: "Present" },
  { status: "LATE",     label: "Late" },
  { status: "ABSENT",   label: "Absent" },
  { status: "ON_LEAVE", label: "Leave" },
  { status: "HOLIDAY",  label: "Holiday" },
  { status: "HALF_DAY", label: "Half Day" },
];

// ── Page ──────────────────────────────────────────────────────────────────────

export default function AttendancePage() {
  const router = useRouter();
  const { isAuthenticated } = useAuthStore();
  const { data: user, isLoading: userLoading } = useMe();

  const now = new Date();
  const [year,  setYear]  = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1); // 1-12

  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);

  const [proofOpen, setProofOpen] = useState(false);
  const [proofSrc, setProofSrc]   = useState<string | null>(null);
  const [proofTitle, setProofTitle] = useState("Proof");
  const [proofTs, setProofTs]     = useState<string | undefined>();

  useEffect(() => {
    if (!isAuthenticated && !userLoading) router.replace("/login");
  }, [isAuthenticated, userLoading, router]);

  // First and last day of the month
  const firstDay = `${year}-${String(month).padStart(2, "0")}-01`;
  const lastDay  = toISO(new Date(year, month, 0));

  const { data: attResp, isLoading: attLoading } = useQuery({
    queryKey: ["emp-att-month", user?.id, year, month],
    queryFn: () =>
      apiGet<DailyAtt[]>("/attendance/daily", {
        employee_id: user!.id,
        from_date: firstDay,
        to_date: lastDay,
        per_page: 40,
      }),
    enabled: !!user?.id,
  });

  // Proof for selected day (lazy)
  const { data: proofResp, isLoading: proofLoading } = useQuery({
    queryKey: ["emp-att-proof", user?.id, selectedDate],
    queryFn: () =>
      apiGet<ProofItem[]>(`/attendance/daily/${user!.id}/${selectedDate}/proof`),
    enabled: !!user?.id && !!selectedDate,
  });

  if (userLoading || !user) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
      </div>
    );
  }

  const records = attResp?.data ?? [];
  const attMap  = new Map<string, DailyAtt>();
  for (const r of records) attMap.set(r.date, r);

  // Build calendar grid
  const firstDow = new Date(year, month - 1, 1).getDay(); // 0=Sun
  const startOffset = firstDow === 0 ? 6 : firstDow - 1;  // Convert to Mon=0
  const daysInMonth = new Date(year, month, 0).getDate();
  const today = istDateStr(now);

  const cells: Array<{ date: string | null; day: number | null }> = [];
  for (let i = 0; i < startOffset; i++) cells.push({ date: null, day: null });
  for (let d = 1; d <= daysInMonth; d++) {
    const date = `${year}-${String(month).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
    cells.push({ date, day: d });
  }
  // Fill last row
  while (cells.length % 7 !== 0) cells.push({ date: null, day: null });

  function prevMonth() {
    if (month === 1) { setYear(y => y - 1); setMonth(12); }
    else setMonth(m => m - 1);
  }
  function nextMonth() {
    if (month === 12) { setYear(y => y + 1); setMonth(1); }
    else setMonth(m => m + 1);
  }
  function canGoNext() {
    return year < now.getFullYear() || (year === now.getFullYear() && month < now.getMonth() + 1);
  }

  function openDay(date: string) {
    setSelectedDate(date);
    setDrawerOpen(true);
  }

  const selectedAtt   = selectedDate ? attMap.get(selectedDate) ?? null : null;
  const selectedProofs = proofResp?.data ?? [];

  function openProof(p: ProofItem, label: string) {
    setDrawerOpen(false);
    setTimeout(() => {
      setProofSrc(p.url);
      setProofTitle(label);
      setProofTs(p.captured_at);
      setProofOpen(true);
    }, 100);
  }

  return (
    <EmployeeLayout pageTitle="Attendance">
      <div className="mx-auto max-w-xl space-y-4">
        {/* Month navigator */}
        <div className="flex items-center justify-between rounded-xl border bg-card p-3">
          <Button variant="ghost" size="icon" onClick={prevMonth} className="h-10 w-10">
            <ChevronLeft className="h-5 w-5" />
          </Button>
          <h2 className="text-base font-semibold">
            {MONTH_NAMES[month - 1]} {year}
          </h2>
          <Button variant="ghost" size="icon" onClick={nextMonth} disabled={!canGoNext()} className="h-10 w-10">
            <ChevronRight className="h-5 w-5" />
          </Button>
        </div>

        {/* Summary strip */}
        {!attLoading && records.length > 0 && (
          <div className="flex gap-2 overflow-x-auto pb-1">
            {/* Count by status so each counter's colour matches the day's colour in the
                calendar below (both keyed off CELL_BG[status]). A late half-day is
                status=HALF_DAY (orange) — its lateness still shows as the "LATE" tag on
                the calendar cell and in the day drawer. */}
            {[
              { status: "PRESENT",  count: records.filter(r => r.status === "PRESENT").length,  label: "Present" },
              { status: "LATE",     count: records.filter(r => r.status === "LATE").length,     label: "Late" },
              { status: "HALF_DAY", count: records.filter(r => r.status === "HALF_DAY").length, label: "Half Day" },
              { status: "ABSENT",   count: records.filter(r => r.status === "ABSENT").length,   label: "Absent" },
              { status: "ON_LEAVE", count: records.filter(r => r.status === "ON_LEAVE").length, label: "Leave" },
            ].map(({ status, count, label }) => (
              <div key={status} className={`flex shrink-0 flex-col items-center rounded-xl px-4 py-2 ${CELL_BG[status] ?? ""}`}>
                <span className="text-lg font-bold leading-none">{count}</span>
                <span className="mt-0.5 text-[11px]">{label}</span>
              </div>
            ))}
          </div>
        )}

        {/* Calendar */}
        {attLoading ? (
          <Skeleton className="h-64 w-full rounded-xl" />
        ) : (
          <div className="rounded-xl border bg-card shadow-sm">
            {/* Day headers */}
            <div className="grid grid-cols-7 border-b">
              {DAY_LABELS.map(d => (
                <div key={d} className="py-2 text-center text-[11px] font-medium text-muted-foreground">
                  {d}
                </div>
              ))}
            </div>

            {/* Cells */}
            <div className="grid grid-cols-7">
              {cells.map((cell, idx) => {
                if (!cell.date) {
                  return <div key={`empty-${idx}`} className="border-r border-b last:border-r-0 p-1 [&:nth-child(7n)]:border-r-0" />;
                }
                const rec = attMap.get(cell.date);
                const isToday = cell.date === today;
                const isFuture = cell.date > today;
                const bg = rec ? (CELL_BG[rec.status] ?? "") : "";

                return (
                  <button
                    key={cell.date}
                    onClick={() => !isFuture && openDay(cell.date!)}
                    disabled={isFuture}
                    className={`
                      flex min-h-[44px] flex-col items-center justify-center border-b border-r p-1
                      [&:nth-child(7n)]:border-r-0
                      transition-colors active:opacity-70
                      ${isFuture ? "cursor-default text-muted-foreground/30" : ""}
                      ${rec ? bg : ""}
                      ${isToday ? "ring-2 ring-inset ring-primary" : ""}
                    `}
                  >
                    <span className={`text-sm font-medium ${isToday ? "font-bold" : ""}`}>
                      {cell.day}
                    </span>
                    {rec?.is_late && (
                      <span className="text-[8px] font-semibold leading-none">LATE</span>
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {/* Legend */}
        <div className="flex flex-wrap gap-x-3 gap-y-1.5">
          {LEGEND.map(({ status, label }) => (
            <div key={status} className="flex items-center gap-1.5">
              <div className={`h-3 w-3 rounded-sm ${CELL_BG[status]?.split(" ")[0] ?? "bg-muted"}`} />
              <span className="text-[11px] text-muted-foreground">{label}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Day detail drawer */}
      <Sheet open={drawerOpen} onOpenChange={setDrawerOpen}>
        <SheetContent side="bottom" className="max-h-[80vh] rounded-t-2xl overflow-y-auto">
          <SheetHeader className="mb-4">
            <SheetTitle>
              {selectedDate
                ? new Date(selectedDate + "T00:00:00").toLocaleDateString("en-IN", {
                    weekday: "long", day: "2-digit", month: "long", year: "numeric",
                  })
                : "Attendance Details"}
            </SheetTitle>
          </SheetHeader>

          {selectedAtt ? (
            <div className="space-y-4">
              <div className="flex items-center gap-2">
                <StatusBadge status={selectedAtt.status} />
                {selectedAtt.is_late && (
                  <span className="text-xs font-medium text-yellow-600 dark:text-yellow-400">
                    {formatMinutes(selectedAtt.late_minutes)} late
                  </span>
                )}
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-xl bg-muted/50 p-3">
                  <p className="text-xs text-muted-foreground">Check-in</p>
                  <p className="mt-1 font-bold tabular-nums">{timeIST(selectedAtt.check_in)}</p>
                </div>
                <div className="rounded-xl bg-muted/50 p-3">
                  <p className="text-xs text-muted-foreground">Check-out</p>
                  <p className="mt-1 font-bold tabular-nums">{timeIST(selectedAtt.check_out)}</p>
                </div>
                <div className="rounded-xl bg-muted/50 p-3">
                  <p className="text-xs text-muted-foreground">Work Hours</p>
                  <p className="mt-1 font-bold">
                    {selectedAtt.work_minutes != null ? formatMinutes(selectedAtt.work_minutes) : "—"}
                  </p>
                </div>
                <div className="rounded-xl bg-muted/50 p-3">
                  <p className="text-xs text-muted-foreground">Source</p>
                  <p className="mt-1 text-sm capitalize">{selectedAtt.source.replace(/_/g, " ")}</p>
                </div>
              </div>

              {/* Proof images */}
              {proofLoading ? (
                <Skeleton className="h-16 rounded-xl" />
              ) : selectedProofs.length > 0 ? (
                <div>
                  <p className="mb-2 text-sm font-medium">Proof Images</p>
                  <div className="flex gap-3">
                    {selectedProofs.map(p => (
                      <button
                        key={p.id}
                        onClick={() => openProof(p, p.proof_type === "entry" ? "Entry Proof" : "Exit Proof")}
                        className="flex flex-1 items-center gap-2 rounded-xl border bg-muted/30 p-2 active:bg-muted"
                      >
                        <div className="relative h-12 w-12 shrink-0 overflow-hidden rounded-lg bg-muted">
                          {/* eslint-disable-next-line @next/next/no-img-element */}
                          <img src={p.url} alt={p.proof_type} className="h-full w-full object-cover" />
                        </div>
                        <div className="min-w-0">
                          <p className="text-xs font-medium capitalize">{p.proof_type}</p>
                          <p className="text-[10px] text-muted-foreground">{timeIST(p.captured_at)}</p>
                        </div>
                        <Camera className="ml-auto h-4 w-4 shrink-0 text-muted-foreground" />
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          ) : (
            <div className="flex flex-col items-center py-8 text-muted-foreground">
              <p className="text-sm">No attendance record for this day.</p>
            </div>
          )}
        </SheetContent>
      </Sheet>

      <ProofImageModal
        open={proofOpen}
        onOpenChange={setProofOpen}
        src={proofSrc}
        title={proofTitle}
        timestamp={proofTs}
      />
    </EmployeeLayout>
  );
}
