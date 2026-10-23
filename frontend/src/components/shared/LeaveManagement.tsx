"use client";

// Shared Leave management screen used by BOTH the HR and Admin portals.
// The portal only differs by the sidebar nav passed in. HR and Admin are both
// "final approvers": the Approve action calls hr-approve, which now finalizes a
// request whether it is still awaiting the manager or already awaiting HR.

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm, Controller } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { ColumnDef } from "@tanstack/react-table";
import { CheckCircle, XCircle, Plus, Pencil, Trash2 } from "lucide-react";

import { PortalLayout } from "@/components/shared/Layout";
import type { NavEntry } from "@/components/shared/sidebar";
import { DataTable } from "@/components/shared/DataTable";
import { ConfirmDialog } from "@/components/shared/ConfirmDialog";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetFooter } from "@/components/ui/sheet";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { apiGet, apiPost, apiPatch, apiDelete } from "@/lib/api";

interface LeaveRequest { id: string; employee_name: string; leave_type_name: string; leave_type_code: string; start_date: string; end_date: string; days_requested: number; reason: string; status: string; manager_name: string | null; hr_name: string | null }
interface LeaveType { id: string; name: string; code: string; days_per_year: number; is_paid: boolean; requires_approval: boolean; carry_forward: boolean; max_carry_forward_days: number }
interface Employee { id: string; first_name: string; last_name: string; employee_code: string }

const leaveTypeSchema = z.object({
  name: z.string().min(1).max(100),
  code: z.string().min(1).max(10),
  days_per_year: z.coerce.number().int().min(0),
  is_paid: z.boolean().default(true),
  requires_approval: z.boolean().default(true),
  carry_forward: z.boolean().default(false),
  max_carry_forward_days: z.coerce.number().int().min(0).default(0),
});
type LeaveTypeForm = z.infer<typeof leaveTypeSchema>;

const balanceSchema = z.object({
  employee_id: z.string().uuid("Select an employee"),
  leave_type_id: z.string().uuid("Select a leave type"),
  year: z.coerce.number().int().min(2020).max(2100),
  allocated_days: z.coerce.number().int().min(0),
  carried_forward_days: z.coerce.number().int().min(0).default(0),
});
type BalanceForm = z.infer<typeof balanceSchema>;

// Leave requests awaiting any approval step — a higher role can finalize either.
const PENDING_STATUSES = ["pending_manager", "pending_hr"];

export function LeaveManagement({ navItems, portalLabel }: { navItems: NavEntry[]; portalLabel: string }) {
  const qc = useQueryClient();
  const [statusFilter, setStatusFilter] = useState("all");
  const [approveTarget, setApproveTarget] = useState<{ id: string; approve: boolean } | null>(null);
  const [remarks, setRemarks] = useState("");
  const [typeSheet, setTypeSheet] = useState<"create" | "edit" | null>(null);
  const [editType, setEditType] = useState<LeaveType | null>(null);
  const [deleteType, setDeleteType] = useState<LeaveType | null>(null);

  const { data: reqResp, isLoading } = useQuery({
    queryKey: ["leave-requests-manage", statusFilter],
    queryFn: () => apiGet<LeaveRequest[]>("/leave/requests", {
      per_page: 100, ...(statusFilter !== "all" ? { status: statusFilter } : {}),
    }),
  });
  const { data: typesResp, isLoading: typesLoading } = useQuery({ queryKey: ["leave-types"], queryFn: () => apiGet<LeaveType[]>("/leave/types") });
  const { data: empResp } = useQuery({ queryKey: ["employees-list"], queryFn: () => apiGet<Employee[]>("/employees", { per_page: 100 }) });

  const requests = reqResp?.data ?? [];
  const leaveTypes = typesResp?.data ?? [];
  const employees = empResp?.data ?? [];

  const typeForm = useForm<LeaveTypeForm>({ resolver: zodResolver(leaveTypeSchema), defaultValues: { is_paid: true, requires_approval: true, carry_forward: false, max_carry_forward_days: 0 } });
  const balanceForm = useForm<BalanceForm>({ resolver: zodResolver(balanceSchema), defaultValues: { year: new Date().getFullYear() } });

  const approveMut = useMutation({
    mutationFn: ({ id, approve, rem }: { id: string; approve: boolean; rem: string }) =>
      apiPost(`/leave/requests/${id}/${approve ? "hr-approve" : "hr-reject"}`, { remarks: rem || undefined }),
    onSuccess: (_, v) => { toast.success(v.approve ? "Leave approved" : "Leave rejected"); setApproveTarget(null); qc.invalidateQueries({ queryKey: ["leave-requests-manage"] }); },
    onError: (e: Error) => toast.error(e.message),
  });

  const createTypeMut = useMutation({
    mutationFn: (d: LeaveTypeForm) => apiPost("/leave/types", d),
    onSuccess: () => { toast.success("Leave type created"); setTypeSheet(null); typeForm.reset(); qc.invalidateQueries({ queryKey: ["leave-types"] }); },
    onError: (e: Error) => toast.error(e.message),
  });
  const editTypeMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: LeaveTypeForm }) => apiPatch(`/leave/types/${id}`, data),
    onSuccess: () => { toast.success("Leave type updated"); setTypeSheet(null); setEditType(null); qc.invalidateQueries({ queryKey: ["leave-types"] }); },
    onError: (e: Error) => toast.error(e.message),
  });
  const deleteTypeMut = useMutation({
    mutationFn: (id: string) => apiDelete(`/leave/types/${id}`),
    onSuccess: () => { toast.success("Leave type deleted"); setDeleteType(null); qc.invalidateQueries({ queryKey: ["leave-types"] }); },
    onError: (e: Error) => toast.error(e.message),
  });
  const adjustBalanceMut = useMutation({
    mutationFn: (d: BalanceForm) => apiPost("/leave/balance/adjust", d),
    onSuccess: () => { toast.success("Balance adjusted"); balanceForm.reset(); },
    onError: (e: Error) => toast.error(e.message),
  });

  function openEditType(lt: LeaveType) {
    setEditType(lt);
    typeForm.reset({ name: lt.name, code: lt.code, days_per_year: lt.days_per_year, is_paid: lt.is_paid, requires_approval: lt.requires_approval, carry_forward: lt.carry_forward, max_carry_forward_days: lt.max_carry_forward_days });
    setTypeSheet("edit");
  }

  const reqColumns: ColumnDef<LeaveRequest>[] = [
    { accessorKey: "employee_name", header: "Employee" },
    { accessorKey: "leave_type_name", header: "Leave Type" },
    { accessorKey: "start_date", header: "Start" },
    { accessorKey: "end_date", header: "End" },
    { accessorKey: "days_requested", header: "Days" },
    { accessorKey: "status", header: "Status", cell: ({ row }) => <StatusBadge status={row.original.status} /> },
    { accessorKey: "reason", header: "Reason", cell: ({ row }) => <span className="text-xs max-w-[200px] truncate block">{row.original.reason}</span> },
    {
      id: "actions", header: "",
      cell: ({ row }) => (PENDING_STATUSES.includes(row.original.status) && (
        <div className="flex gap-1">
          <Button variant="ghost" size="icon" className="h-7 w-7 text-green-600" title="Approve" onClick={() => { setApproveTarget({ id: row.original.id, approve: true }); setRemarks(""); }}><CheckCircle className="h-3 w-3" /></Button>
          <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive" title="Reject" onClick={() => { setApproveTarget({ id: row.original.id, approve: false }); setRemarks(""); }}><XCircle className="h-3 w-3" /></Button>
        </div>
      )),
    },
  ];

  const typeColumns: ColumnDef<LeaveType>[] = [
    { accessorKey: "name", header: "Name" },
    { accessorKey: "code", header: "Code", cell: ({ row }) => <code className="text-xs bg-muted px-1 rounded">{row.original.code}</code> },
    { accessorKey: "days_per_year", header: "Days/Year" },
    { accessorKey: "is_paid", header: "Paid", cell: ({ row }) => <StatusBadge status={row.original.is_paid ? "APPROVED" : "REJECTED"} /> },
    { accessorKey: "carry_forward", header: "Carry Fwd", cell: ({ row }) => row.original.carry_forward ? `✓ up to ${row.original.max_carry_forward_days}d` : "No" },
    {
      id: "actions", header: "",
      cell: ({ row }) => (
        <div className="flex gap-1">
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => openEditType(row.original)}><Pencil className="h-3 w-3" /></Button>
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setDeleteType(row.original)}><Trash2 className="h-3 w-3 text-destructive" /></Button>
        </div>
      ),
    },
  ];

  return (
    <PortalLayout navItems={navItems} portalLabel={portalLabel} pageTitle="Leave Management">
      <Tabs defaultValue="requests">
        <TabsList>
          <TabsTrigger value="requests">Requests</TabsTrigger>
          <TabsTrigger value="types">Leave Types</TabsTrigger>
          <TabsTrigger value="balance">Adjust Balance</TabsTrigger>
        </TabsList>

        <TabsContent value="requests" className="mt-4 space-y-4">
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="w-48"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All requests</SelectItem>
              <SelectItem value="pending_hr">Awaiting HR Approval</SelectItem>
              <SelectItem value="pending_manager">Awaiting Manager</SelectItem>
              <SelectItem value="approved">Approved</SelectItem>
              <SelectItem value="rejected">Rejected</SelectItem>
              <SelectItem value="cancelled">Cancelled</SelectItem>
            </SelectContent>
          </Select>
          {isLoading ? <Skeleton className="h-64 w-full" /> : <DataTable columns={reqColumns} data={requests} pageSize={20} />}
        </TabsContent>

        <TabsContent value="types" className="mt-4 space-y-4">
          <div className="flex justify-end"><Button onClick={() => { typeForm.reset(); setTypeSheet("create"); }}><Plus className="mr-2 h-4 w-4" />Add Leave Type</Button></div>
          {typesLoading ? <Skeleton className="h-48 w-full" /> : <DataTable columns={typeColumns} data={leaveTypes} pageSize={15} />}
        </TabsContent>

        <TabsContent value="balance" className="mt-4">
          <div className="rounded-lg border bg-card p-6 max-w-md">
            <h3 className="mb-4 font-semibold">Manually Adjust Leave Balance</h3>
            <form onSubmit={balanceForm.handleSubmit(d => adjustBalanceMut.mutate(d))} className="space-y-4">
              <div className="space-y-1"><Label>Employee*</Label>
                <Controller control={balanceForm.control} name="employee_id" render={({ field }) => (
                  <Select value={field.value} onValueChange={field.onChange}><SelectTrigger><SelectValue placeholder="Select employee" /></SelectTrigger><SelectContent>{employees.map(e => <SelectItem key={e.id} value={e.id}>{e.first_name} {e.last_name} ({e.employee_code})</SelectItem>)}</SelectContent></Select>
                )} />
                <p className="text-xs text-destructive">{balanceForm.formState.errors.employee_id?.message}</p>
              </div>
              <div className="space-y-1"><Label>Leave Type*</Label>
                <Controller control={balanceForm.control} name="leave_type_id" render={({ field }) => (
                  <Select value={field.value} onValueChange={field.onChange}><SelectTrigger><SelectValue placeholder="Select type" /></SelectTrigger><SelectContent>{leaveTypes.map(t => <SelectItem key={t.id} value={t.id}>{t.name}</SelectItem>)}</SelectContent></Select>
                )} />
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div className="space-y-1"><Label>Year*</Label><Input type="number" {...balanceForm.register("year")} /></div>
                <div className="space-y-1"><Label>Allocated Days</Label><Input type="number" {...balanceForm.register("allocated_days")} /></div>
                <div className="space-y-1"><Label>Carry Forward</Label><Input type="number" {...balanceForm.register("carried_forward_days")} /></div>
              </div>
              <Button type="submit" disabled={adjustBalanceMut.isPending}>{adjustBalanceMut.isPending ? "Saving…" : "Adjust Balance"}</Button>
            </form>
          </div>
        </TabsContent>
      </Tabs>

      {/* Approve / Reject dialog */}
      <Dialog open={!!approveTarget} onOpenChange={o => !o && setApproveTarget(null)}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader><DialogTitle>{approveTarget?.approve ? "Approve Leave" : "Reject Leave"}</DialogTitle><DialogDescription>Optionally add remarks</DialogDescription></DialogHeader>
          <Input placeholder="Remarks (optional)" value={remarks} onChange={e => setRemarks(e.target.value)} />
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setApproveTarget(null)}>Cancel</Button>
            <Button variant={approveTarget?.approve ? "default" : "destructive"}
              disabled={approveMut.isPending}
              onClick={() => approveTarget && approveMut.mutate({ id: approveTarget.id, approve: approveTarget.approve, rem: remarks })}>
              {approveTarget?.approve ? "Approve" : "Reject"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Leave type sheet */}
      <Sheet open={!!typeSheet} onOpenChange={o => !o && (setTypeSheet(null), setEditType(null))}>
        <SheetContent className="sm:max-w-md overflow-y-auto">
          <SheetHeader><SheetTitle>{typeSheet === "create" ? "Add Leave Type" : "Edit Leave Type"}</SheetTitle></SheetHeader>
          <form onSubmit={typeForm.handleSubmit(d => typeSheet === "create" ? createTypeMut.mutate(d) : editType && editTypeMut.mutate({ id: editType.id, data: d }))} className="mt-6 space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1"><Label>Name*</Label><Input {...typeForm.register("name")} /></div>
              <div className="space-y-1"><Label>Code*</Label><Input {...typeForm.register("code")} placeholder="e.g. CL" /></div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1"><Label>Days/Year</Label><Input type="number" {...typeForm.register("days_per_year")} /></div>
              <div className="space-y-1"><Label>Max Carry Fwd</Label><Input type="number" {...typeForm.register("max_carry_forward_days")} /></div>
            </div>
            <div className="space-y-3">
              <Controller control={typeForm.control} name="is_paid" render={({ field }) => (
                <div className="flex items-center justify-between rounded border p-3">
                  <div><p className="text-sm font-medium">Paid Leave</p><p className="text-xs text-muted-foreground">Counts as paid workday</p></div>
                  <Switch checked={field.value} onCheckedChange={field.onChange} />
                </div>
              )} />
              <Controller control={typeForm.control} name="requires_approval" render={({ field }) => (
                <div className="flex items-center justify-between rounded border p-3">
                  <div><p className="text-sm font-medium">Requires Approval</p><p className="text-xs text-muted-foreground">Needs manager + HR sign-off</p></div>
                  <Switch checked={field.value} onCheckedChange={field.onChange} />
                </div>
              )} />
              <Controller control={typeForm.control} name="carry_forward" render={({ field }) => (
                <div className="flex items-center justify-between rounded border p-3">
                  <div><p className="text-sm font-medium">Carry Forward</p><p className="text-xs text-muted-foreground">Unused days roll to next year</p></div>
                  <Switch checked={field.value} onCheckedChange={field.onChange} />
                </div>
              )} />
            </div>
            <SheetFooter>
              <Button type="button" variant="outline" onClick={() => setTypeSheet(null)}>Cancel</Button>
              <Button type="submit" disabled={createTypeMut.isPending || editTypeMut.isPending}>Save</Button>
            </SheetFooter>
          </form>
        </SheetContent>
      </Sheet>

      <ConfirmDialog open={!!deleteType} onOpenChange={o => !o && setDeleteType(null)}
        title={`Delete leave type "${deleteType?.name}"?`} destructive confirmLabel="Delete"
        onConfirm={() => deleteType && deleteTypeMut.mutate(deleteType.id)} isLoading={deleteTypeMut.isPending} />
    </PortalLayout>
  );
}
