"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Camera, Bell, CheckCheck, ScanFace } from "lucide-react";
import Link from "next/link";
import { useAuthStore } from "@/stores/auth-store";
import { useMe } from "@/hooks/use-auth";
import { apiGet, apiPost } from "@/lib/api";
import { EmployeeLayout } from "@/components/employee/EmployeeLayout";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { ProofImageModal } from "@/components/shared/ProofImageModal";
import { Skeleton } from "@/components/ui/skeleton";
import { istDateStr, formatMinutes, toIST } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

interface DailyAtt {
  id: string;
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

interface LeaveBalance {
  id: string;
  leave_type_name: string;
  leave_type_code: string;
  available_days: number;
  used_days: number;
  allocated_days: number;
}

interface Notification {
  id: string;
  title: string;
  body: string;
  status: string;
  event_type: string;
  created_at: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function timeIST(utc: string | null) {
  if (!utc) return "—";
  return new Date(utc).toLocaleTimeString("en-IN", {
    timeZone: "Asia/Kolkata",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function greeting() {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function EmployeeDashboardPage() {
  const router = useRouter();
  const { isAuthenticated } = useAuthStore();
  const { data: user, isLoading: userLoading } = useMe();
  const qc = useQueryClient();

  const [proofOpen, setProofOpen] = useState(false);
  const [proofSrc, setProofSrc] = useState<string | null>(null);
  const [proofTitle, setProofTitle] = useState("Proof");
  const [proofTs, setProofTs] = useState<string | undefined>();

  useEffect(() => {
    if (!isAuthenticated && !userLoading) router.replace("/login");
  }, [isAuthenticated, userLoading, router]);

  const today = istDateStr();

  const { data: attResp, isLoading: attLoading } = useQuery({
    queryKey: ["emp-today", user?.id, today],
    queryFn: () => apiGet<DailyAtt>(`/attendance/daily/${user!.id}/${today}`),
    enabled: !!user?.id,
    staleTime: 60_000,
  });

  const { data: proofResp, isLoading: proofLoading } = useQuery({
    queryKey: ["emp-today-proof", user?.id, today],
    queryFn: () => apiGet<ProofItem[]>(`/attendance/daily/${user!.id}/${today}/proof`),
    enabled: !!user?.id,
  });

  const { data: balResp, isLoading: balLoading } = useQuery({
    queryKey: ["emp-balance"],
    queryFn: () => apiGet<LeaveBalance[]>("/leave/balance"),
    enabled: !!user?.id,
  });

  const { data: notifResp, isLoading: notifLoading } = useQuery({
    queryKey: ["emp-notifications"],
    queryFn: () => apiGet<Notification[]>("/notifications", { per_page: 5 }),
    enabled: !!user?.id,
  });

  const { mutate: markRead } = useMutation({
    mutationFn: (id: string) => apiPost(`/notifications/${id}/read`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["emp-notifications"] }),
  });

  if (userLoading || !user) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
      </div>
    );
  }

  const att = attResp?.data ?? null;
  const proofs = proofResp?.data ?? [];
  const balances = balResp?.data ?? [];
  const notifications = notifResp?.data ?? [];
  const entryProof = proofs.find(p => p.proof_type === "entry");
  const exitProof  = proofs.find(p => p.proof_type === "exit");

  function openProof(proof: ProofItem, label: string) {
    setProofSrc(proof.url);
    setProofTitle(label);
    setProofTs(proof.captured_at);
    setProofOpen(true);
  }

  return (
    <EmployeeLayout pageTitle="My Dashboard">
      <div className="mx-auto max-w-xl space-y-5">

        {/* Greeting */}
        <div>
          <h2 className="text-xl font-bold">
            {greeting()}, {user.first_name}!
          </h2>
          <p className="text-sm text-muted-foreground">
            {new Date().toLocaleDateString("en-IN", {
              weekday: "long",
              day: "2-digit",
              month: "long",
              year: "numeric",
            })}
          </p>
        </div>

        {/* Selfie check-in CTA */}
        <Link
          href="/employee/checkin"
          className="flex items-center gap-3 rounded-2xl border border-primary/30 bg-primary/5 p-4 shadow-sm transition-colors active:bg-primary/10"
        >
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
            <ScanFace className="h-6 w-6" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="font-semibold">Mark attendance with a selfie</p>
            <p className="text-xs text-muted-foreground">
              Quick live selfie check-in from the office network.
            </p>
          </div>
          <span className="text-primary">→</span>
        </Link>

        {/* Today's Attendance Card */}
        <div className="rounded-2xl border bg-card p-4 shadow-sm">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="font-semibold">Today&apos;s Attendance</h3>
            {attLoading ? (
              <Skeleton className="h-5 w-20 rounded-full" />
            ) : (
              <StatusBadge status={att?.status ?? "ABSENT"} />
            )}
          </div>

          {attLoading ? (
            <div className="grid grid-cols-2 gap-3">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-16 rounded-xl" />
              ))}
            </div>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-3">
                {/* Check-in */}
                <div className="rounded-xl bg-muted/50 p-3">
                  <p className="text-xs text-muted-foreground">Check-in</p>
                  <p className="mt-1 text-lg font-bold tabular-nums">
                    {timeIST(att?.check_in ?? null)}
                  </p>
                  {att?.is_late && att.late_minutes > 0 && (
                    <p className="mt-0.5 text-xs font-medium text-yellow-600 dark:text-yellow-400">
                      {formatMinutes(att.late_minutes)} late
                    </p>
                  )}
                </div>

                {/* Check-out */}
                <div className="rounded-xl bg-muted/50 p-3">
                  <p className="text-xs text-muted-foreground">Check-out</p>
                  <p className="mt-1 text-lg font-bold tabular-nums">
                    {timeIST(att?.check_out ?? null)}
                  </p>
                </div>

                {/* Work hours */}
                <div className="rounded-xl bg-muted/50 p-3">
                  <p className="text-xs text-muted-foreground">Work Hours</p>
                  <p className="mt-1 text-lg font-bold">
                    {att?.work_minutes != null ? formatMinutes(att.work_minutes) : "—"}
                  </p>
                </div>

                {/* Overtime */}
                <div className="rounded-xl bg-muted/50 p-3">
                  <p className="text-xs text-muted-foreground">Overtime</p>
                  <p className="mt-1 text-lg font-bold">
                    {att?.overtime_minutes ? formatMinutes(att.overtime_minutes) : "—"}
                  </p>
                </div>
              </div>

              {/* Proof thumbnails */}
              {!proofLoading && (entryProof || exitProof) && (
                <div className="mt-3 flex gap-3">
                  {entryProof && (
                    <button
                      onClick={() => openProof(entryProof, "Entry Proof")}
                      className="flex flex-1 items-center gap-2 rounded-xl border bg-muted/30 p-2 text-left active:bg-muted"
                    >
                      <div className="relative h-10 w-10 shrink-0 overflow-hidden rounded-lg bg-muted">
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img src={entryProof.url} alt="Entry" className="h-full w-full object-cover" />
                      </div>
                      <div>
                        <p className="text-xs font-medium">Entry</p>
                        <p className="text-[10px] text-muted-foreground">
                          {timeIST(entryProof.captured_at)}
                        </p>
                      </div>
                      <Camera className="ml-auto h-4 w-4 shrink-0 text-muted-foreground" />
                    </button>
                  )}
                  {exitProof && (
                    <button
                      onClick={() => openProof(exitProof, "Exit Proof")}
                      className="flex flex-1 items-center gap-2 rounded-xl border bg-muted/30 p-2 text-left active:bg-muted"
                    >
                      <div className="relative h-10 w-10 shrink-0 overflow-hidden rounded-lg bg-muted">
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img src={exitProof.url} alt="Exit" className="h-full w-full object-cover" />
                      </div>
                      <div>
                        <p className="text-xs font-medium">Exit</p>
                        <p className="text-[10px] text-muted-foreground">
                          {timeIST(exitProof.captured_at)}
                        </p>
                      </div>
                      <Camera className="ml-auto h-4 w-4 shrink-0 text-muted-foreground" />
                    </button>
                  )}
                </div>
              )}
            </>
          )}
        </div>

        {/* Leave Balances */}
        <div>
          <div className="mb-2 flex items-center justify-between">
            <h3 className="font-semibold">Leave Balances</h3>
            <Link
              href="/employee/leave"
              className="flex min-h-[44px] items-center px-2 text-xs font-medium text-primary"
            >
              Apply →
            </Link>
          </div>
          {balLoading ? (
            <div className="flex gap-3 overflow-x-auto pb-1">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-20 w-28 shrink-0 rounded-xl" />
              ))}
            </div>
          ) : balances.length === 0 ? (
            <p className="text-sm text-muted-foreground">No leave balances found.</p>
          ) : (
            <div className="flex gap-3 overflow-x-auto pb-1">
              {balances.map(b => {
                const pct = b.allocated_days > 0 ? b.available_days / b.allocated_days : 0;
                const color =
                  pct > 0.5
                    ? "text-green-700 dark:text-green-400"
                    : pct > 0.2
                    ? "text-yellow-700 dark:text-yellow-400"
                    : "text-red-700 dark:text-red-400";
                return (
                  <div
                    key={b.id}
                    className="flex min-w-[100px] shrink-0 flex-col rounded-xl border bg-card p-3 shadow-sm"
                  >
                    <p className="truncate text-[11px] font-medium text-muted-foreground">
                      {b.leave_type_code}
                    </p>
                    <p className={`mt-1 text-2xl font-bold ${color}`}>{b.available_days}</p>
                    <p className="text-[10px] text-muted-foreground">
                      of {b.allocated_days} days
                    </p>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Recent Notifications */}
        <div>
          <div className="mb-2 flex items-center justify-between">
            <h3 className="font-semibold">Recent Notifications</h3>
            <span className="text-xs text-muted-foreground">
              {notifications.filter(n => n.status !== "SENT").length > 0
                ? `${notifications.filter(n => n.status !== "SENT").length} unread`
                : "All read"}
            </span>
          </div>

          {notifLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-14 rounded-xl" />
              ))}
            </div>
          ) : notifications.length === 0 ? (
            <div className="flex flex-col items-center rounded-xl border border-dashed py-8 text-muted-foreground">
              <Bell className="mb-1 h-6 w-6 opacity-40" />
              <p className="text-sm">No notifications yet.</p>
            </div>
          ) : (
            <div className="space-y-2">
              {notifications.map(n => {
                const unread = n.status !== "SENT";
                return (
                  <button
                    key={n.id}
                    onClick={() => unread && markRead(n.id)}
                    className={`flex w-full items-start gap-3 rounded-xl border p-3 text-left transition-colors active:bg-muted ${
                      unread
                        ? "border-primary/20 bg-primary/5"
                        : "bg-card"
                    }`}
                  >
                    <div className={`mt-0.5 h-2 w-2 shrink-0 rounded-full ${unread ? "bg-primary" : "bg-transparent"}`} />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{n.title}</p>
                      <p className="line-clamp-2 text-xs text-muted-foreground">{n.body}</p>
                      <p className="mt-0.5 text-[10px] text-muted-foreground">{toIST(n.created_at)}</p>
                    </div>
                    {!unread && <CheckCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>

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
