"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { PenLine, Paperclip, Upload, X } from "lucide-react";
import { useAuthStore } from "@/stores/auth-store";
import { useMe } from "@/hooks/use-auth";
import { apiGet, apiPost, apiDelete, api } from "@/lib/api";
import { istDateStr } from "@/lib/utils";
import { EmployeeLayout } from "@/components/employee/EmployeeLayout";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { ProofImageModal } from "@/components/shared/ProofImageModal";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Sheet, SheetContent, SheetHeader, SheetTitle,
} from "@/components/ui/sheet";

// ── Types ─────────────────────────────────────────────────────────────────────

interface Correction {
  daily_id: string;
  employee_id: string;
  date: string;
  correction_status: string;
  requested_check_in: string | null;
  requested_check_out: string | null;
  reason: string;
  manager_remarks: string | null;
  hr_remarks: string | null;
  current_attendance_status: string;
  proof_url: string | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const STATUS_LABELS: Record<string, string> = {
  pending:     "Pending Manager",
  pending_hr:  "Pending HR",
  approved:    "Approved",
  rejected:    "Rejected",
};

function correctionStatusColor(s: string) {
  if (s === "approved")   return "text-green-600 dark:text-green-400";
  if (s === "rejected")   return "text-red-600 dark:text-red-400";
  if (s === "pending_hr") return "text-teal-600 dark:text-teal-400";
  return "text-yellow-600 dark:text-yellow-400";
}

function timeIST(utc: string | null) {
  if (!utc) return "—";
  return new Date(utc).toLocaleTimeString("en-IN", {
    timeZone: "Asia/Kolkata",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

// Convert an IST wall-clock time (date + HH:MM) to a UTC ISO string for the API.
// Build the instant from the parsed components via Date.UTC so the result does NOT
// depend on the browser's local timezone. IST is UTC+5:30, so the UTC instant for
// an IST wall-clock is Date.UTC(...) − 5h30m.
// (The previous version used `new Date("YYYY-MM-DDTHH:MM")`, which parses in the
//  browser's LOCAL zone; on an IST machine that subtracted the offset twice, so a
//  09:00 entry was stored — and shown back — as 03:30.)
function istToUTC(date: string, time: string): string {
  const [y, m, d] = date.split("-").map(Number);
  const [hh, mm] = time.split(":").map(Number);
  const utcMs = Date.UTC(y, m - 1, d, hh, mm) - 5.5 * 60 * 60 * 1000;
  return new Date(utcMs).toISOString();
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function CorrectionsPage() {
  const router = useRouter();
  const { isAuthenticated } = useAuthStore();
  const { data: user, isLoading: userLoading } = useMe();
  const qc = useQueryClient();

  const [formOpen, setFormOpen] = useState(false);
  const [corrDate, setCorrDate]       = useState("");
  const [checkInTime, setCheckInTime] = useState("");
  const [checkOutTime, setCheckOutTime] = useState("");
  const [reason, setReason]           = useState("");
  const [proof, setProof]             = useState<File | null>(null);
  const [formErr, setFormErr]         = useState("");
  const [proofView, setProofView]     = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!isAuthenticated && !userLoading) router.replace("/login");
  }, [isAuthenticated, userLoading, router]);

  const { data: corrResp, isLoading } = useQuery({
    queryKey: ["emp-corrections", user?.id],
    queryFn: () =>
      apiGet<Correction[]>("/attendance/corrections", {
        employee_id: user!.id,
      }),
    enabled: !!user?.id,
  });

  const { mutate: submit, isPending: submitting } = useMutation({
    mutationFn: async () => {
      const res = await apiPost<Correction>("/attendance/corrections", {
        date: corrDate,
        requested_check_in: checkInTime ? istToUTC(corrDate, checkInTime) : null,
        requested_check_out: checkOutTime ? istToUTC(corrDate, checkOutTime) : null,
        reason: reason.trim(),
      });
      if (!res.success || !res.data) throw new Error(res.error ?? "Submit failed");

      // Upload the optional supporting proof against the created correction.
      if (proof) {
        const fd = new FormData();
        fd.append("file", proof);
        await api.post(`/attendance/corrections/${res.data.daily_id}/proof`, fd, {
          headers: { "Content-Type": "multipart/form-data" },
        });
      }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["emp-corrections"] });
      setFormOpen(false);
      setCorrDate(""); setCheckInTime(""); setCheckOutTime(""); setReason("");
      setProof(null); setFormErr("");
      if (fileRef.current) fileRef.current.value = "";
    },
    onError: (e: Error) => setFormErr(e.message ?? "Failed to submit"),
  });

  const { mutate: cancelCorrection } = useMutation({
    mutationFn: (dailyId: string) => apiDelete(`/attendance/corrections/${dailyId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["emp-corrections"] }),
  });

  function handleSubmit() {
    setFormErr("");
    if (!corrDate)       return setFormErr("Select the date to correct");
    if (!checkInTime && !checkOutTime)
      return setFormErr("Enter at least a check-in or check-out time");
    if (!reason.trim())  return setFormErr("Reason is required");
    submit();
  }

  const today = istDateStr();

  if (userLoading || !user) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
      </div>
    );
  }

  const corrections = corrResp?.data ?? [];
  const pending = corrections.filter(c => c.correction_status === "pending").length;

  return (
    <EmployeeLayout pageTitle="Corrections">
      <div className="mx-auto max-w-xl space-y-5">

        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-bold">Attendance Corrections</h2>
            {pending > 0 && (
              <p className="text-xs text-muted-foreground">{pending} pending review</p>
            )}
          </div>
          <Button onClick={() => setFormOpen(true)} size="sm" className="h-10 px-4">
            + Request
          </Button>
        </div>

        {/* Corrections list */}
        {isLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-24 rounded-xl" />
            ))}
          </div>
        ) : corrections.length === 0 ? (
          <div className="flex flex-col items-center rounded-xl border border-dashed py-12 text-muted-foreground">
            <PenLine className="mb-2 h-8 w-8 opacity-40" />
            <p className="text-sm">No correction requests yet.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {corrections.map(corr => (
              <div key={corr.daily_id} className="rounded-xl border bg-card p-4 shadow-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-sm font-medium">{corr.date}</span>
                  <StatusBadge status={corr.current_attendance_status} />
                  <span className={`text-xs font-medium ${correctionStatusColor(corr.correction_status)}`}>
                    {STATUS_LABELS[corr.correction_status] ?? corr.correction_status}
                  </span>
                  {["pending", "pending_hr"].includes(corr.correction_status) && (
                    <Button
                      variant="ghost"
                      size="icon"
                      className="ml-auto h-7 w-7 shrink-0 text-muted-foreground hover:text-destructive"
                      title="Cancel correction request"
                      onClick={() => cancelCorrection(corr.daily_id)}
                    >
                      <X className="h-4 w-4" />
                      <span className="sr-only">Cancel</span>
                    </Button>
                  )}
                </div>

                <div className="mt-2 grid grid-cols-2 gap-2 text-sm">
                  <div>
                    <span className="text-xs text-muted-foreground">Req. check-in</span>
                    <p className="font-medium tabular-nums">{timeIST(corr.requested_check_in)}</p>
                  </div>
                  <div>
                    <span className="text-xs text-muted-foreground">Req. check-out</span>
                    <p className="font-medium tabular-nums">{timeIST(corr.requested_check_out)}</p>
                  </div>
                </div>

                {corr.reason && (
                  <p className="mt-2 line-clamp-2 text-xs text-muted-foreground">{corr.reason}</p>
                )}

                {corr.proof_url && (
                  <button
                    type="button"
                    onClick={() => setProofView(corr.proof_url)}
                    className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
                  >
                    <Paperclip className="h-3 w-3" /> View proof
                  </button>
                )}

                {(corr.manager_remarks || corr.hr_remarks) && (
                  <p className="mt-1.5 text-xs italic text-muted-foreground">
                    {corr.hr_remarks ?? corr.manager_remarks}
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Correction form sheet */}
      <Sheet open={formOpen} onOpenChange={v => { if (!submitting) { setFormOpen(v); } }}>
        <SheetContent side="bottom" className="max-h-[90vh] rounded-t-2xl overflow-y-auto">
          <SheetHeader className="mb-5">
            <SheetTitle>Request Attendance Correction</SheetTitle>
          </SheetHeader>

          <div className="space-y-4 pb-4">
            {/* Date */}
            <div className="space-y-1.5">
              <Label htmlFor="corr-date">Date to Correct</Label>
              <Input
                id="corr-date"
                type="date"
                max={today}
                value={corrDate}
                onChange={e => setCorrDate(e.target.value)}
                className="h-12"
              />
            </div>

            {/* Times */}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="check-in-time">Check-in Time (IST)</Label>
                <Input
                  id="check-in-time"
                  type="time"
                  value={checkInTime}
                  onChange={e => setCheckInTime(e.target.value)}
                  className="h-12"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="check-out-time">Check-out Time (IST)</Label>
                <Input
                  id="check-out-time"
                  type="time"
                  value={checkOutTime}
                  onChange={e => setCheckOutTime(e.target.value)}
                  className="h-12"
                />
              </div>
            </div>

            <p className="text-xs text-muted-foreground">
              Enter only the fields you want to correct. Leave blank to keep the original time.
            </p>

            {/* Reason */}
            <div className="space-y-1.5">
              <Label htmlFor="corr-reason">Reason for Correction</Label>
              <Textarea
                id="corr-reason"
                placeholder="Briefly explain why the correction is needed…"
                value={reason}
                onChange={e => setReason(e.target.value)}
                rows={3}
                className="resize-none"
              />
            </div>

            {/* Optional proof */}
            <div className="space-y-1.5">
              <Label>Proof (optional)</Label>
              <button
                type="button"
                onClick={() => fileRef.current?.click()}
                className="flex h-12 w-full items-center gap-3 rounded-md border border-dashed px-3 text-sm text-muted-foreground transition-colors hover:border-primary hover:text-primary active:bg-muted"
              >
                <Upload className="h-4 w-4 shrink-0" />
                {proof ? (
                  <span className="truncate text-foreground">{proof.name}</span>
                ) : (
                  "Upload image or PDF (max 10 MB)"
                )}
              </button>
              <input
                ref={fileRef}
                type="file"
                accept="image/*,application/pdf"
                className="hidden"
                onChange={e => setProof(e.target.files?.[0] ?? null)}
              />
            </div>

            {formErr && (
              <p className="text-sm font-medium text-destructive">{formErr}</p>
            )}

            <Button
              className="h-12 w-full text-base"
              onClick={handleSubmit}
              disabled={submitting}
            >
              {submitting ? "Submitting…" : "Submit Correction"}
            </Button>
          </div>
        </SheetContent>
      </Sheet>

      <ProofImageModal open={!!proofView} onOpenChange={o => !o && setProofView(null)} src={proofView} title="Correction Proof" />
    </EmployeeLayout>
  );
}
