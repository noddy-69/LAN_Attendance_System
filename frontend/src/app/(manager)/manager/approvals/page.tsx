"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle, XCircle, Paperclip } from "lucide-react";
import { useAuthStore } from "@/stores/auth-store";
import { useMe } from "@/hooks/use-auth";
import { apiGet, apiPost, apiPatch } from "@/lib/api";
import { ManagerLayout } from "@/components/manager/ManagerLayout";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { ProofImageModal } from "@/components/shared/ProofImageModal";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { formatDate, formatPaise } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

interface LeaveRequest {
  id: string;
  employee_id: string;
  employee_name: string;
  leave_type_name: string;
  start_date: string;
  end_date: string;
  days_requested: number;
  reason: string;
  status: string;
  created_at: string;
}

interface Reimbursement {
  id: string;
  employee_id: string;
  employee_name: string;
  title: string;
  description: string;
  amount_paise: number;
  category: string;
  expense_date: string;
  status: string;
  created_at: string;
  document_count: number;
  documents: Array<{ id: string; file_name: string; url: string | null; mime_type?: string }>;
}

interface Correction {
  daily_id: string;
  employee_id: string;
  date: string;
  correction_status: string;
  requested_check_in: string | null;
  requested_check_out: string | null;
  reason: string;
  current_attendance_status: string;
  proof_url: string | null;
}

// ── Action Dialog ─────────────────────────────────────────────────────────────

interface ActionDialogProps {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  title: string;
  description?: string;
  approve: boolean;
  isLoading: boolean;
  onSubmit: (remarks: string) => void;
}

function ActionDialog({
  open, onOpenChange, title, description, approve, isLoading, onSubmit,
}: ActionDialogProps) {
  const [remarks, setRemarks] = useState("");

  function handleSubmit() {
    onSubmit(remarks);
    setRemarks("");
  }

  return (
    <Dialog open={open} onOpenChange={v => { if (!isLoading) { onOpenChange(v); setRemarks(""); } }}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description && <DialogDescription>{description}</DialogDescription>}
        </DialogHeader>
        <div className="space-y-2">
          <Label htmlFor="remarks">
            Remarks {approve ? "(optional)" : "(required)"}
          </Label>
          <Textarea
            id="remarks"
            placeholder={approve ? "Add a comment…" : "Reason for rejection…"}
            value={remarks}
            onChange={e => setRemarks(e.target.value)}
            rows={3}
          />
        </div>
        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isLoading}>
            Cancel
          </Button>
          <Button
            variant={approve ? "default" : "destructive"}
            onClick={handleSubmit}
            disabled={isLoading || (!approve && !remarks.trim())}
          >
            {isLoading ? "Please wait…" : approve ? "Approve" : "Reject"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Leave Tab ─────────────────────────────────────────────────────────────────

function LeaveTab() {
  const qc = useQueryClient();
  const [dialog, setDialog] = useState<{ id: string; approve: boolean; name: string } | null>(null);

  const { data: resp, isLoading } = useQuery({
    queryKey: ["manager-leave-pending"],
    queryFn: () => apiGet<LeaveRequest[]>("/leave/requests", { status: "pending_manager", per_page: 50 }),
    staleTime: 30_000,
  });

  const { mutate: doAction, isPending } = useMutation({
    mutationFn: ({ id, approve, remarks }: { id: string; approve: boolean; remarks: string }) =>
      approve
        ? apiPost(`/leave/requests/${id}/manager-approve`, { remarks })
        : apiPost(`/leave/requests/${id}/manager-reject`, { remarks }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["manager-leave-pending"] });
      qc.invalidateQueries({ queryKey: ["nav-pending"] });
      setDialog(null);
    },
  });

  const requests = resp?.data ?? [];

  return (
    <>
      {isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-20 rounded-lg" />)}
        </div>
      ) : requests.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed py-12 text-muted-foreground">
          <CheckCircle className="mb-2 h-8 w-8 opacity-40" />
          <p className="text-sm">No pending leave requests.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {requests.map(req => (
            <div key={req.id} className="rounded-lg border bg-card p-4 shadow-sm">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="font-semibold">{req.employee_name}</p>
                    <StatusBadge status={req.status} />
                  </div>
                  <p className="mt-0.5 text-sm text-muted-foreground">
                    {req.leave_type_name} · {req.days_requested} day{req.days_requested !== 1 ? "s" : ""}
                    · {formatDate(req.start_date)} – {formatDate(req.end_date)}
                  </p>
                  {req.reason && (
                    <p className="mt-1 text-xs text-muted-foreground line-clamp-2">{req.reason}</p>
                  )}
                  <p className="mt-1 text-xs text-muted-foreground">
                    Applied {formatDate(req.created_at)}
                  </p>
                </div>
                <div className="flex shrink-0 gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    className="gap-1 border-red-200 text-red-600 hover:bg-red-50 dark:border-red-900 dark:text-red-400 dark:hover:bg-red-950"
                    onClick={() => setDialog({ id: req.id, approve: false, name: req.employee_name })}
                  >
                    <XCircle className="h-3.5 w-3.5" /> Reject
                  </Button>
                  <Button
                    size="sm"
                    className="gap-1"
                    onClick={() => setDialog({ id: req.id, approve: true, name: req.employee_name })}
                  >
                    <CheckCircle className="h-3.5 w-3.5" /> Approve
                  </Button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {dialog && (
        <ActionDialog
          open
          onOpenChange={v => !v && setDialog(null)}
          title={dialog.approve ? "Approve Leave Request" : "Reject Leave Request"}
          description={`${dialog.approve ? "Approve" : "Reject"} leave request for ${dialog.name}?`}
          approve={dialog.approve}
          isLoading={isPending}
          onSubmit={remarks => doAction({ id: dialog.id, approve: dialog.approve, remarks })}
        />
      )}
    </>
  );
}

// ── Reimbursements Tab ────────────────────────────────────────────────────────

function ReimbursementsTab() {
  const qc = useQueryClient();
  const [dialog, setDialog] = useState<{ id: string; approve: boolean; name: string } | null>(null);
  const [detailId, setDetailId] = useState<string | null>(null);

  const { data: resp, isLoading } = useQuery({
    queryKey: ["manager-reimb-pending"],
    queryFn: () => apiGet<Reimbursement[]>("/reimbursements", { status: "pending_manager", per_page: 50 }),
    staleTime: 30_000,
  });

  // The list omits receipt URLs; the detail endpoint returns presigned links.
  const { data: detailResp } = useQuery({
    queryKey: ["manager-reimb-detail", detailId],
    queryFn: () => (detailId ? apiGet<Reimbursement>(`/reimbursements/${detailId}`) : null),
    enabled: !!detailId,
  });
  const detail = detailResp?.data;

  const { mutate: doAction, isPending } = useMutation({
    mutationFn: ({ id, approve, remarks }: { id: string; approve: boolean; remarks: string }) =>
      approve
        ? apiPatch(`/reimbursements/${id}/manager-approve`, { remarks })
        : apiPatch(`/reimbursements/${id}/manager-reject`, { remarks }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["manager-reimb-pending"] });
      qc.invalidateQueries({ queryKey: ["nav-pending"] });
      setDialog(null);
    },
  });

  const claims = resp?.data ?? [];

  return (
    <>
      {isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-20 rounded-lg" />)}
        </div>
      ) : claims.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed py-12 text-muted-foreground">
          <CheckCircle className="mb-2 h-8 w-8 opacity-40" />
          <p className="text-sm">No pending reimbursement claims.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {claims.map(claim => (
            <div key={claim.id} className="rounded-lg border bg-card p-4 shadow-sm">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="font-semibold">{claim.employee_name}</p>
                    <StatusBadge status={claim.status} />
                    <span className="font-medium text-green-700 dark:text-green-400">
                      {formatPaise(claim.amount_paise)}
                    </span>
                  </div>
                  <p className="mt-0.5 text-sm text-muted-foreground">
                    {claim.title} · {claim.category} · {formatDate(claim.expense_date)}
                  </p>
                  {claim.description && (
                    <p className="mt-1 text-xs text-muted-foreground line-clamp-2">
                      {claim.description}
                    </p>
                  )}
                  {claim.document_count > 0 && (
                    <button
                      type="button"
                      onClick={() => setDetailId(claim.id)}
                      className="mt-1 inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
                    >
                      <Paperclip className="h-3 w-3" /> View receipt{claim.document_count > 1 ? "s" : ""} ({claim.document_count})
                    </button>
                  )}
                </div>
                <div className="flex shrink-0 gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    className="gap-1 border-red-200 text-red-600 hover:bg-red-50 dark:border-red-900 dark:text-red-400 dark:hover:bg-red-950"
                    onClick={() => setDialog({ id: claim.id, approve: false, name: claim.employee_name })}
                  >
                    <XCircle className="h-3.5 w-3.5" /> Reject
                  </Button>
                  <Button
                    size="sm"
                    className="gap-1"
                    onClick={() => setDialog({ id: claim.id, approve: true, name: claim.employee_name })}
                  >
                    <CheckCircle className="h-3.5 w-3.5" /> Approve
                  </Button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {dialog && (
        <ActionDialog
          open
          onOpenChange={v => !v && setDialog(null)}
          title={dialog.approve ? "Approve Reimbursement" : "Reject Reimbursement"}
          description={`${dialog.approve ? "Approve" : "Reject"} reimbursement for ${dialog.name}?`}
          approve={dialog.approve}
          isLoading={isPending}
          onSubmit={remarks => doAction({ id: dialog.id, approve: dialog.approve, remarks })}
        />
      )}

      {/* Receipts — shown in the image popup (clicking opens full-size in a new tab). */}
      <ProofImageModal
        open={!!detailId}
        onOpenChange={o => !o && setDetailId(null)}
        proofs={(detail?.documents ?? [])
          .filter(d => d.url)
          .map(d => ({ url: d.url as string, proof_type: d.file_name, mime_type: d.mime_type }))}
      />
    </>
  );
}

// ── Corrections Tab ───────────────────────────────────────────────────────────

function CorrectionsTab() {
  const qc = useQueryClient();
  const [dialog, setDialog] = useState<{ id: string; approve: boolean } | null>(null);
  const [proofUrl, setProofUrl] = useState<string | null>(null);

  const { data: resp, isLoading } = useQuery({
    queryKey: ["manager-corrections"],
    queryFn: () => apiGet<Correction[]>("/attendance/corrections"),
    staleTime: 30_000,
  });

  const { mutate: doAction, isPending } = useMutation({
    mutationFn: ({ id, approve, remarks }: { id: string; approve: boolean; remarks: string }) =>
      approve
        ? apiPatch(`/attendance/corrections/${id}/manager-approve`, { remarks })
        : apiPatch(`/attendance/corrections/${id}/reject`, { remarks }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["manager-corrections"] });
      qc.invalidateQueries({ queryKey: ["nav-pending"] });
      setDialog(null);
    },
  });

  const pending = (resp?.data ?? []).filter(c => c.correction_status === "pending");

  function formatTimeIST(utc: string | null): string {
    if (!utc) return "—";
    return new Date(utc).toLocaleTimeString("en-IN", {
      timeZone: "Asia/Kolkata",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  }

  return (
    <>
      {isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-20 rounded-lg" />)}
        </div>
      ) : pending.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed py-12 text-muted-foreground">
          <CheckCircle className="mb-2 h-8 w-8 opacity-40" />
          <p className="text-sm">No pending correction requests.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {pending.map(corr => (
            <div key={corr.daily_id} className="rounded-lg border bg-card p-4 shadow-sm">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="font-mono text-sm font-semibold">{corr.date}</p>
                    <StatusBadge status={corr.current_attendance_status} />
                    <span className="rounded-full bg-orange-100 px-2.5 py-0.5 text-xs font-medium text-orange-800 dark:bg-orange-900/30 dark:text-orange-400">
                      correction pending
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Requested check-in: <span className="font-medium">{formatTimeIST(corr.requested_check_in)}</span>
                    {" · "}
                    check-out: <span className="font-medium">{formatTimeIST(corr.requested_check_out)}</span>
                  </p>
                  {corr.reason && (
                    <p className="mt-1 text-xs text-muted-foreground line-clamp-2">{corr.reason}</p>
                  )}
                  {corr.proof_url && (
                    <button
                      type="button"
                      onClick={() => setProofUrl(corr.proof_url)}
                      className="mt-1 inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
                    >
                      <Paperclip className="h-3 w-3" /> View proof
                    </button>
                  )}
                </div>
                <div className="flex shrink-0 gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    className="gap-1 border-red-200 text-red-600 hover:bg-red-50 dark:border-red-900 dark:text-red-400 dark:hover:bg-red-950"
                    onClick={() => setDialog({ id: corr.daily_id, approve: false })}
                  >
                    <XCircle className="h-3.5 w-3.5" /> Reject
                  </Button>
                  <Button
                    size="sm"
                    className="gap-1"
                    onClick={() => setDialog({ id: corr.daily_id, approve: true })}
                  >
                    <CheckCircle className="h-3.5 w-3.5" /> Approve
                  </Button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {dialog && (
        <ActionDialog
          open
          onOpenChange={v => !v && setDialog(null)}
          title={dialog.approve ? "Approve Correction" : "Reject Correction"}
          description={
            dialog.approve
              ? "Forward to HR for final approval."
              : "Reject this correction request."
          }
          approve={dialog.approve}
          isLoading={isPending}
          onSubmit={remarks => doAction({ id: dialog.id, approve: dialog.approve, remarks })}
        />
      )}

      <ProofImageModal open={!!proofUrl} onOpenChange={o => !o && setProofUrl(null)} src={proofUrl} title="Correction Proof" />
    </>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ApprovalsPage() {
  const router  = useRouter();
  const { isAuthenticated } = useAuthStore();
  const { data: user, isLoading: userLoading } = useMe();

  useEffect(() => {
    if (!isAuthenticated && !userLoading) router.replace("/login");
  }, [isAuthenticated, userLoading, router]);

  // Count badges per tab
  const { data: leaveResp }  = useQuery({
    queryKey: ["manager-leave-pending"],
    queryFn: () => apiGet<LeaveRequest[]>("/leave/requests", { status: "pending_manager", per_page: 50 }),
    staleTime: 30_000,
  });
  const { data: reimbResp }  = useQuery({
    queryKey: ["manager-reimb-pending"],
    queryFn: () => apiGet<Reimbursement[]>("/reimbursements", { status: "pending_manager", per_page: 50 }),
    staleTime: 30_000,
  });
  const { data: corrResp }   = useQuery({
    queryKey: ["manager-corrections"],
    queryFn: () => apiGet<Correction[]>("/attendance/corrections"),
    staleTime: 30_000,
  });

  const leaveCount = (leaveResp?.data ?? []).length;
  const reimbCount = (reimbResp?.data ?? []).length;
  const corrCount  = (corrResp?.data ?? []).filter(c => c.correction_status === "pending").length;

  function TabBadge({ n }: { n: number }) {
    if (n === 0) return null;
    return (
      <span className="ml-1.5 inline-flex h-5 min-w-[20px] items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-bold text-white">
        {n > 99 ? "99+" : n}
      </span>
    );
  }

  if (userLoading || !user) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
      </div>
    );
  }

  return (
    <ManagerLayout pageTitle="Approvals">
      <div className="space-y-6">
        <div>
          <h2 className="text-2xl font-bold">Approvals</h2>
          <p className="text-sm text-muted-foreground">
            Review and action your team&apos;s pending requests.
          </p>
        </div>

        <Tabs defaultValue="leave">
          <TabsList className="mb-4 w-full justify-start sm:w-auto">
            <TabsTrigger value="leave">
              Leave <TabBadge n={leaveCount} />
            </TabsTrigger>
            <TabsTrigger value="reimbursements">
              Reimbursements <TabBadge n={reimbCount} />
            </TabsTrigger>
            <TabsTrigger value="corrections">
              Corrections <TabBadge n={corrCount} />
            </TabsTrigger>
          </TabsList>

          <TabsContent value="leave">
            <LeaveTab />
          </TabsContent>
          <TabsContent value="reimbursements">
            <ReimbursementsTab />
          </TabsContent>
          <TabsContent value="corrections">
            <CorrectionsTab />
          </TabsContent>
        </Tabs>
      </div>
    </ManagerLayout>
  );
}
