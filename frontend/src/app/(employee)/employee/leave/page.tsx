"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { CalendarDays, X } from "lucide-react";
import { useAuthStore } from "@/stores/auth-store";
import { useMe } from "@/hooks/use-auth";
import { apiGet, apiPost } from "@/lib/api";
import { EmployeeLayout } from "@/components/employee/EmployeeLayout";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Sheet, SheetContent, SheetHeader, SheetTitle,
} from "@/components/ui/sheet";
import { istDateStr, formatDate } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

interface LeaveType {
  id: string;
  name: string;
  code: string;
  days_per_year: number;
  is_paid: boolean;
}

interface LeaveBalance {
  id: string;
  leave_type_id: string;
  leave_type_name: string;
  leave_type_code: string;
  available_days: number;
  used_days: number;
  allocated_days: number;
}

interface LeaveRequest {
  id: string;
  leave_type_name: string;
  leave_type_code: string;
  start_date: string;
  end_date: string;
  days_requested: number;
  reason: string;
  status: string;
  manager_remarks: string | null;
  hr_remarks: string | null;
  created_at: string;
}

// ── Timeline step ─────────────────────────────────────────────────────────────

function StatusTimeline({ status }: { status: string }) {
  // Backend LeaveStatus enum values are lowercase: pending_manager / pending_hr / approved / …
  type Step = { label: string; done: boolean };
  const steps: Step[] = [
    { label: "Applied", done: true },
    { label: "Manager", done: ["pending_hr", "approved"].includes(status) },
    { label: "HR / Final", done: status === "approved" },
  ];

  if (status === "rejected")  return <span className="text-xs text-red-500 font-medium">Rejected</span>;
  if (status === "cancelled") return <span className="text-xs text-muted-foreground">Cancelled</span>;

  return (
    <div className="flex items-center gap-1">
      {steps.map((step, i) => (
        <div key={step.label} className="flex items-center gap-1">
          <div className={`h-2 w-2 rounded-full ${step.done ? "bg-green-500" : "bg-muted-foreground/30"}`} />
          <span className={`text-[10px] ${step.done ? "text-green-700 dark:text-green-400 font-medium" : "text-muted-foreground"}`}>
            {step.label}
          </span>
          {i < steps.length - 1 && (
            <div className={`h-px w-3 ${step.done ? "bg-green-500" : "bg-muted-foreground/30"}`} />
          )}
        </div>
      ))}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function LeavePage() {
  const router = useRouter();
  const { isAuthenticated } = useAuthStore();
  const { data: user, isLoading: userLoading } = useMe();
  const qc = useQueryClient();

  const [applyOpen, setApplyOpen] = useState(false);
  const [leaveTypeId, setLeaveTypeId] = useState("");
  const [startDate, setStartDate]     = useState("");
  const [endDate, setEndDate]         = useState("");
  const [reason, setReason]           = useState("");
  const [applyErr, setApplyErr]       = useState("");

  useEffect(() => {
    if (!isAuthenticated && !userLoading) router.replace("/login");
  }, [isAuthenticated, userLoading, router]);

  const { data: typesResp } = useQuery({
    queryKey: ["leave-types"],
    queryFn: () => apiGet<LeaveType[]>("/leave/types"),
    enabled: !!user?.id,
  });

  const { data: balResp, isLoading: balLoading } = useQuery({
    queryKey: ["emp-balance"],
    queryFn: () => apiGet<LeaveBalance[]>("/leave/balance"),
    enabled: !!user?.id,
  });

  const { data: reqResp, isLoading: reqLoading } = useQuery({
    queryKey: ["emp-leave-requests"],
    queryFn: () => apiGet<LeaveRequest[]>("/leave/requests", { per_page: 30 }),
    enabled: !!user?.id,
  });

  const { mutate: applyLeave, isPending: applying } = useMutation({
    mutationFn: () =>
      apiPost("/leave/apply", {
        leave_type_id: leaveTypeId,
        start_date: startDate,
        end_date: endDate,
        reason,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["emp-leave-requests"] });
      qc.invalidateQueries({ queryKey: ["emp-balance"] });
      setApplyOpen(false);
      setLeaveTypeId(""); setStartDate(""); setEndDate(""); setReason(""); setApplyErr("");
    },
    onError: (e: Error) => setApplyErr(e.message ?? "Failed to apply"),
  });

  const { mutate: cancelLeave } = useMutation({
    mutationFn: (id: string) => apiPost(`/leave/requests/${id}/cancel`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["emp-leave-requests"] });
      qc.invalidateQueries({ queryKey: ["emp-balance"] });
    },
  });

  const today = istDateStr();

  if (userLoading || !user) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
      </div>
    );
  }

  const types    = typesResp?.data ?? [];
  const balances = balResp?.data ?? [];
  const requests = reqResp?.data ?? [];
  const pending  = requests.filter(r => ["pending_manager", "pending_hr"].includes(r.status)).length;

  function submitApply() {
    setApplyErr("");
    if (!leaveTypeId) return setApplyErr("Select a leave type");
    if (!startDate || !endDate) return setApplyErr("Select start and end dates");
    if (endDate < startDate) return setApplyErr("End date must be ≥ start date");
    if (!reason.trim()) return setApplyErr("Reason is required");
    applyLeave();
  }

  return (
    <EmployeeLayout pageTitle="Leave">
      <div className="mx-auto max-w-xl space-y-5">

        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-bold">Leave</h2>
            {pending > 0 && (
              <p className="text-xs text-muted-foreground">{pending} pending approval</p>
            )}
          </div>
          <Button onClick={() => setApplyOpen(true)} size="sm" className="h-10 px-4">
            + Apply
          </Button>
        </div>

        {/* Balance cards */}
        <div>
          <h3 className="mb-2 text-sm font-semibold text-muted-foreground uppercase tracking-wide">
            Balances
          </h3>
          {balLoading ? (
            <div className="flex gap-3 overflow-x-auto pb-1">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-20 w-28 shrink-0 rounded-xl" />
              ))}
            </div>
          ) : balances.length === 0 ? (
            <p className="text-sm text-muted-foreground">No balances configured.</p>
          ) : (
            <div className="flex gap-3 overflow-x-auto pb-1">
              {balances.map(b => {
                const pct = b.allocated_days > 0 ? b.available_days / b.allocated_days : 0;
                const color =
                  pct > 0.5 ? "text-green-700 dark:text-green-400"
                  : pct > 0.2 ? "text-yellow-700 dark:text-yellow-400"
                  : "text-red-600 dark:text-red-400";
                return (
                  <div key={b.id} className="flex min-w-[110px] shrink-0 flex-col rounded-xl border bg-card p-3 shadow-sm">
                    <p className="truncate text-[11px] font-medium text-muted-foreground">{b.leave_type_name}</p>
                    <p className={`mt-1 text-2xl font-bold ${color}`}>{b.available_days}</p>
                    <p className="text-[10px] text-muted-foreground">
                      used {b.used_days} / {b.allocated_days}
                    </p>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Requests list */}
        <div>
          <h3 className="mb-2 text-sm font-semibold text-muted-foreground uppercase tracking-wide">
            My Requests
          </h3>
          {reqLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-24 rounded-xl" />
              ))}
            </div>
          ) : requests.length === 0 ? (
            <div className="flex flex-col items-center rounded-xl border border-dashed py-10 text-muted-foreground">
              <CalendarDays className="mb-1 h-8 w-8 opacity-40" />
              <p className="text-sm">No leave requests yet.</p>
            </div>
          ) : (
            <div className="space-y-3">
              {requests.map(req => (
                <div key={req.id} className="rounded-xl border bg-card p-4 shadow-sm">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium">{req.leave_type_name}</span>
                        <StatusBadge status={req.status} />
                      </div>
                      <p className="mt-1 text-sm text-muted-foreground">
                        {formatDate(req.start_date)}
                        {req.start_date !== req.end_date && ` – ${formatDate(req.end_date)}`}
                        {" · "}
                        {req.days_requested} day{req.days_requested !== 1 ? "s" : ""}
                      </p>
                      {req.reason && (
                        <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{req.reason}</p>
                      )}
                      <div className="mt-2">
                        <StatusTimeline status={req.status} />
                      </div>
                      {(req.manager_remarks || req.hr_remarks) && (
                        <p className="mt-1.5 text-xs text-muted-foreground italic">
                          {req.hr_remarks ?? req.manager_remarks}
                        </p>
                      )}
                    </div>
                    {["pending_manager", "pending_hr"].includes(req.status) && (
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 shrink-0 text-muted-foreground hover:text-destructive"
                        title="Cancel request"
                        onClick={() => cancelLeave(req.id)}
                      >
                        <X className="h-4 w-4" />
                        <span className="sr-only">Cancel</span>
                      </Button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Apply leave sheet */}
      <Sheet open={applyOpen} onOpenChange={setApplyOpen}>
        <SheetContent side="bottom" className="max-h-[92vh] rounded-t-2xl overflow-y-auto">
          <SheetHeader className="mb-5">
            <SheetTitle>Apply for Leave</SheetTitle>
          </SheetHeader>

          <div className="space-y-4 pb-4">
            {/* Leave type */}
            <div className="space-y-1.5">
              <Label>Leave Type</Label>
              <Select value={leaveTypeId} onValueChange={setLeaveTypeId}>
                <SelectTrigger className="h-12">
                  <SelectValue placeholder="Select type…" />
                </SelectTrigger>
                <SelectContent>
                  {types.map(t => (
                    <SelectItem key={t.id} value={t.id}>
                      {t.name}
                      {balances.find(b => b.leave_type_id === t.id) && (
                        <span className="ml-1 text-muted-foreground">
                          ({balances.find(b => b.leave_type_id === t.id)?.available_days} left)
                        </span>
                      )}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="start-date">From</Label>
                <Input
                  id="start-date"
                  type="date"
                  min={today}
                  value={startDate}
                  onChange={e => { setStartDate(e.target.value); if (endDate < e.target.value) setEndDate(e.target.value); }}
                  className="h-12"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="end-date">To</Label>
                <Input
                  id="end-date"
                  type="date"
                  min={startDate || today}
                  value={endDate}
                  onChange={e => setEndDate(e.target.value)}
                  className="h-12"
                />
              </div>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="reason">Reason</Label>
              <Textarea
                id="reason"
                placeholder="Briefly describe the reason…"
                value={reason}
                onChange={e => setReason(e.target.value)}
                rows={3}
                className="resize-none"
              />
            </div>

            {applyErr && (
              <p className="text-sm font-medium text-destructive">{applyErr}</p>
            )}

            <Button
              className="h-12 w-full text-base"
              onClick={submitApply}
              disabled={applying}
            >
              {applying ? "Submitting…" : "Submit Request"}
            </Button>
          </div>
        </SheetContent>
      </Sheet>
    </EmployeeLayout>
  );
}
