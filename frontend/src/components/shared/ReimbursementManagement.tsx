"use client";

// Shared Reimbursement management screen for BOTH the HR and Admin portals.
// HR and Admin are final approvers: hr-approve finalizes a claim whether it is
// still awaiting the manager or already awaiting HR.

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ColumnDef } from "@tanstack/react-table";
import { CheckCircle, XCircle, DollarSign, Eye } from "lucide-react";

import { PortalLayout } from "@/components/shared/Layout";
import type { NavEntry } from "@/components/shared/sidebar";
import { DataTable } from "@/components/shared/DataTable";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { ProofImageModal } from "@/components/shared/ProofImageModal";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { apiGet, apiPatch } from "@/lib/api";
import { formatPaise, toIST } from "@/lib/utils";

interface Reimbursement {
  id: string; employee_name: string; title: string; description: string | null;
  amount_paise: number; category: string; expense_date: string; status: string;
  manager_name: string | null; hr_name: string | null; paid_at: string | null;
  document_count: number; manager_remarks: string | null; hr_remarks: string | null;
  documents: Array<{ id: string; file_name: string; url: string | null; file_size_bytes: number; mime_type: string }>;
}

// Claims awaiting any approval step — a higher role can finalize either.
const PENDING_STATUSES = ["pending_manager", "pending_hr"];

export function ReimbursementManagement({ navItems, portalLabel }: { navItems: NavEntry[]; portalLabel: string }) {
  const qc = useQueryClient();
  const [statusFilter, setStatusFilter] = useState("all");
  const [actionTarget, setActionTarget] = useState<{ id: string; action: "hr-approve" | "hr-reject" | "mark-paid" } | null>(null);
  const [remarks, setRemarks] = useState("");
  const [detailId, setDetailId] = useState<string | null>(null);
  const [receiptsOpen, setReceiptsOpen] = useState(false);

  const { data: claimsResp, isLoading } = useQuery({
    queryKey: ["reimbursements-manage", statusFilter],
    queryFn: () => apiGet<Reimbursement[]>("/reimbursements", { per_page: 100, ...(statusFilter !== "all" ? { status: statusFilter } : {}) }),
  });

  const { data: detailResp } = useQuery({
    queryKey: ["reimbursement-detail", detailId],
    queryFn: () => detailId ? apiGet<Reimbursement>(`/reimbursements/${detailId}`) : null,
    enabled: !!detailId,
  });

  const claims = claimsResp?.data ?? [];
  const detail = detailResp?.data;

  const actionMut = useMutation({
    mutationFn: ({ id, action, rem }: { id: string; action: string; rem?: string }) =>
      action === "mark-paid" ? apiPatch(`/reimbursements/${id}/mark-paid`) : apiPatch(`/reimbursements/${id}/${action}`, { remarks: rem }),
    onSuccess: (_, v) => {
      toast.success(v.action === "hr-approve" ? "Approved" : v.action === "hr-reject" ? "Rejected" : "Marked as paid");
      setActionTarget(null);
      qc.invalidateQueries({ queryKey: ["reimbursements-manage"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const columns: ColumnDef<Reimbursement>[] = [
    { accessorKey: "employee_name", header: "Employee" },
    { accessorKey: "title", header: "Title", cell: ({ row }) => <span className="max-w-[180px] truncate block text-sm">{row.original.title}</span> },
    { accessorKey: "category", header: "Category", cell: ({ row }) => <span className="capitalize text-xs">{row.original.category.replace("_"," ")}</span> },
    { accessorKey: "amount_paise", header: "Amount", cell: ({ row }) => <span className="font-medium">{formatPaise(row.original.amount_paise)}</span> },
    { accessorKey: "expense_date", header: "Date" },
    { accessorKey: "status", header: "Status", cell: ({ row }) => <StatusBadge status={row.original.status} /> },
    { accessorKey: "document_count", header: "Docs", cell: ({ row }) => <span className="text-xs">{row.original.document_count}</span> },
    {
      id: "actions", header: "",
      cell: ({ row }) => {
        const r = row.original;
        return (
          <div className="flex gap-1">
            <Button variant="ghost" size="icon" className="h-7 w-7" title="View" onClick={() => setDetailId(r.id)}><Eye className="h-3 w-3" /></Button>
            {PENDING_STATUSES.includes(r.status) && <>
              <Button variant="ghost" size="icon" className="h-7 w-7 text-green-600" title="Approve" onClick={() => { setActionTarget({ id: r.id, action: "hr-approve" }); setRemarks(""); }}><CheckCircle className="h-3 w-3" /></Button>
              <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive" title="Reject" onClick={() => { setActionTarget({ id: r.id, action: "hr-reject" }); setRemarks(""); }}><XCircle className="h-3 w-3" /></Button>
            </>}
            {r.status === "approved" && (
              <Button variant="ghost" size="icon" className="h-7 w-7 text-blue-600" title="Mark paid" onClick={() => setActionTarget({ id: r.id, action: "mark-paid" })}><DollarSign className="h-3 w-3" /></Button>
            )}
          </div>
        );
      },
    },
  ];

  return (
    <PortalLayout navItems={navItems} portalLabel={portalLabel} pageTitle="Reimbursements">
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-2xl font-bold">Reimbursements</h2>
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="w-48"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All</SelectItem>
              <SelectItem value="pending_hr">Awaiting HR</SelectItem>
              <SelectItem value="pending_manager">Awaiting Manager</SelectItem>
              <SelectItem value="approved">Approved</SelectItem>
              <SelectItem value="paid">Paid</SelectItem>
              <SelectItem value="rejected">Rejected</SelectItem>
            </SelectContent>
          </Select>
        </div>
        {isLoading ? <Skeleton className="h-64 w-full" /> : <DataTable columns={columns} data={claims} pageSize={20} />}
      </div>

      {/* Detail dialog */}
      <Dialog open={!!detailId} onOpenChange={o => !o && setDetailId(null)}>
        <DialogContent className="max-w-lg">
          <DialogHeader><DialogTitle>{detail?.title ?? "Claim Details"}</DialogTitle><DialogDescription>{detail?.employee_name} · {formatPaise(detail?.amount_paise ?? 0)}</DialogDescription></DialogHeader>
          {detail && (
            <div className="space-y-3 text-sm">
              <div className="grid grid-cols-2 gap-2 text-muted-foreground">
                <div><span className="font-medium text-foreground">Category:</span> <span className="capitalize">{detail.category.replace("_"," ")}</span></div>
                <div><span className="font-medium text-foreground">Expense Date:</span> {detail.expense_date}</div>
                <div><span className="font-medium text-foreground">Status:</span> <StatusBadge status={detail.status} /></div>
                {detail.paid_at && <div><span className="font-medium text-foreground">Paid at:</span> {toIST(detail.paid_at)}</div>}
              </div>
              {detail.description && <p className="text-muted-foreground">{detail.description}</p>}
              {detail.manager_remarks && <p><span className="font-medium">Manager:</span> {detail.manager_remarks}</p>}
              {detail.hr_remarks && <p><span className="font-medium">HR:</span> {detail.hr_remarks}</p>}
              {detail.documents.length > 0 && (
                <div>
                  <Button variant="outline" size="sm" onClick={() => setReceiptsOpen(true)}>
                    View receipt{detail.documents.length > 1 ? "s" : ""} ({detail.documents.length})
                  </Button>
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Receipts shown in the image popup (clicking opens full-size in a new tab). */}
      <ProofImageModal
        open={receiptsOpen}
        onOpenChange={setReceiptsOpen}
        proofs={(detail?.documents ?? [])
          .filter(d => d.url)
          .map(d => ({ url: d.url as string, proof_type: d.file_name, mime_type: d.mime_type }))}
      />

      {/* Action dialog */}
      <Dialog open={!!actionTarget} onOpenChange={o => !o && setActionTarget(null)}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>{actionTarget?.action === "hr-approve" ? "Approve Claim" : actionTarget?.action === "hr-reject" ? "Reject Claim" : "Mark as Paid"}</DialogTitle>
          </DialogHeader>
          {actionTarget?.action !== "mark-paid" && <Input placeholder="Remarks (optional)" value={remarks} onChange={e => setRemarks(e.target.value)} />}
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setActionTarget(null)}>Cancel</Button>
            <Button
              variant={actionTarget?.action === "hr-reject" ? "destructive" : "default"}
              disabled={actionMut.isPending}
              onClick={() => actionTarget && actionMut.mutate({ id: actionTarget.id, action: actionTarget.action, rem: remarks })}>
              {actionMut.isPending ? "…" : (actionTarget?.action === "hr-approve" ? "Approve" : actionTarget?.action === "hr-reject" ? "Reject" : "Mark Paid")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </PortalLayout>
  );
}
