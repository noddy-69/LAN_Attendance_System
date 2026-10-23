"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { ColumnDef } from "@tanstack/react-table";
import { Eye, Pencil, CheckCircle, XCircle } from "lucide-react";

import { PortalLayout } from "@/components/shared/Layout";
import { ADMIN_NAV } from "@/components/admin/nav";
import { DataTable } from "@/components/shared/DataTable";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { ProofImageModal } from "@/components/shared/ProofImageModal";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription, SheetFooter } from "@/components/ui/sheet";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { apiGet, apiPatch } from "@/lib/api";
import { istDateStr, toIST, formatMinutes } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

interface DailyAtt { id: string; employee_id: string; date: string; check_in: string | null; check_out: string | null; work_minutes: number | null; late_minutes: number; is_late: boolean; status: string; source: string; notes: string | null }
interface Proof { id: string; event_id: string; proof_type: string; url: string; captured_at: string }
interface Correction { daily_id: string; employee_id: string; date: string; correction_status: string; requested_check_in: string | null; requested_check_out: string | null; reason: string; manager_remarks: string | null; hr_remarks: string | null; proof_url: string | null }
interface Employee { id: string; first_name: string; last_name: string; employee_code: string }

// ── Override schema ───────────────────────────────────────────────────────────

const overrideSchema = z.object({
  check_in:  z.string().optional(),
  check_out: z.string().optional(),
  notes:     z.string().max(500).optional(),
});
type OverrideForm = z.infer<typeof overrideSchema>;

// ── Page ──────────────────────────────────────────────────────────────────────

export default function AdminAttendancePage() {
  const qc = useQueryClient();
  const [fromDate, setFromDate] = useState(() => { const d = new Date(); d.setDate(d.getDate() - 7); return istDateStr(d); });
  const [toDate, setToDate] = useState(istDateStr());
  const [statusFilter, setStatusFilter] = useState("all");
  const [overrideTarget, setOverrideTarget] = useState<DailyAtt | null>(null);

  // Proof modal
  const [proofOpen, setProofOpen] = useState(false);
  const [proofImages, setProofImages] = useState<Proof[]>([]);
  const [proofLoading, setProofLoading] = useState(false);
  const [corrProof, setCorrProof] = useState<string | null>(null);

  // Correction remarks
  const [corrRemarksTarget, setCorrRemarksTarget] = useState<{ id: string; approve: boolean } | null>(null);
  const [corrRemarks, setCorrRemarks] = useState("");

  const overrideForm = useForm<OverrideForm>({ resolver: zodResolver(overrideSchema) });

  const { data: attResp, isLoading } = useQuery({
    queryKey: ["admin-att-daily", fromDate, toDate, statusFilter],
    queryFn: () => apiGet<DailyAtt[]>("/attendance/daily", {
      from_date: fromDate, to_date: toDate, per_page: 500,
      ...(statusFilter !== "all" ? { status: statusFilter } : {}),
    }),
  });

  // Derive the id→name map straight from the query data. React Query v5 removed the
  // onSuccess callback, so the old setEmpMap(onSuccess) never ran — which left the
  // Employee column showing the raw employee id instead of the name.
  const { data: empMap = {} } = useQuery({
    queryKey: ["employees-map"],
    queryFn: async () => {
      const res = await apiGet<Employee[]>("/employees", { per_page: 100 });
      const map: Record<string, string> = {};
      (res.data ?? []).forEach(e => { map[e.id] = `${e.first_name} ${e.last_name}`.trim() || e.employee_code; });
      return map;
    },
  });

  const { data: corrResp, isLoading: corrLoading } = useQuery({
    queryKey: ["admin-corrections"],
    queryFn: () => apiGet<Correction[]>("/attendance/corrections"),
  });

  const overrideMut = useMutation({
    mutationFn: ({ empId, date, data }: { empId: string; date: string; data: OverrideForm }) => {
      const payload: Record<string, unknown> = {};
      if (data.check_in)  payload.check_in  = new Date(data.check_in).toISOString();
      if (data.check_out) payload.check_out = new Date(data.check_out).toISOString();
      if (data.notes) payload.notes = data.notes;
      return apiPatch(`/attendance/daily/${empId}/${date}`, payload);
    },
    onSuccess: () => { toast.success("Attendance updated"); setOverrideTarget(null); qc.invalidateQueries({ queryKey: ["admin-att-daily"] }); },
    onError: (e: Error) => toast.error(e.message),
  });

  const corrActionMut = useMutation({
    mutationFn: ({ id, approve, remarks }: { id: string; approve: boolean; remarks?: string }) =>
      apiPatch(`/attendance/corrections/${id}/${approve ? "hr-approve" : "reject"}`, { remarks }),
    onSuccess: (_, vars) => { toast.success(vars.approve ? "Correction approved" : "Correction rejected"); setCorrRemarksTarget(null); qc.invalidateQueries({ queryKey: ["admin-corrections"] }); qc.invalidateQueries({ queryKey: ["admin-att-daily"] }); },
    onError: (e: Error) => toast.error(e.message),
  });

  const openProofs = async (emp_id: string, date: string) => {
    setProofLoading(true); setProofImages([]); setProofOpen(true);
    try {
      const res = await apiGet<Proof[]>(`/attendance/daily/${emp_id}/${date}/proof`);
      setProofImages(res.data ?? []);
    } catch { toast.error("Could not load proof images"); }
    setProofLoading(false);
  };

  // Sort by attendance date, most recent first, so recent days show at the top.
  const records = [...(attResp?.data ?? [])].sort((a, b) => b.date.localeCompare(a.date));
  const corrections = (corrResp?.data ?? []).filter(c => c.correction_status === "pending" || c.correction_status === "pending_hr");

  const columns: ColumnDef<DailyAtt>[] = [
    { accessorKey: "date", header: "Date" },
    { id: "employee", header: "Employee", cell: ({ row }) => <span className="text-sm">{empMap[row.original.employee_id] ?? row.original.employee_id.slice(0, 8)}</span> },
    { accessorKey: "check_in",  header: "Check-In",  cell: ({ row }) => <span className="text-xs">{toIST(row.original.check_in)}</span> },
    { accessorKey: "check_out", header: "Check-Out", cell: ({ row }) => <span className="text-xs">{toIST(row.original.check_out)}</span> },
    { id: "work", header: "Work", cell: ({ row }) => <span className="text-xs">{formatMinutes(row.original.work_minutes)}</span> },
    { accessorKey: "status", header: "Status", cell: ({ row }) => <StatusBadge status={row.original.status} /> },
    { accessorKey: "is_late", header: "Late", cell: ({ row }) => row.original.is_late ? <span className="text-xs text-yellow-600">+{formatMinutes(row.original.late_minutes)}</span> : <span className="text-xs text-muted-foreground">—</span> },
    { accessorKey: "source", header: "Source", cell: ({ row }) => <span className="text-xs capitalize text-muted-foreground">{row.original.source.replace("_"," ")}</span> },
    {
      id: "actions", header: "",
      cell: ({ row }) => (
        <div className="flex gap-1">
          <Button variant="ghost" size="icon" className="h-7 w-7" title="View proofs" onClick={() => openProofs(row.original.employee_id, row.original.date)}><Eye className="h-3 w-3" /></Button>
          <Button variant="ghost" size="icon" className="h-7 w-7" title="Override" onClick={() => { setOverrideTarget(row.original); overrideForm.reset({ check_in: row.original.check_in ? new Date(row.original.check_in).toISOString().slice(0,16) : "", check_out: row.original.check_out ? new Date(row.original.check_out).toISOString().slice(0,16) : "" }); }}><Pencil className="h-3 w-3" /></Button>
        </div>
      ),
    },
  ];

  const corrColumns: ColumnDef<Correction>[] = [
    { accessorKey: "date", header: "Date" },
    { id: "employee", header: "Employee", cell: ({ row }) => <span className="text-sm">{empMap[row.original.employee_id] ?? row.original.employee_id.slice(0,8)}</span> },
    { accessorKey: "reason", header: "Reason", cell: ({ row }) => <span className="text-xs">{row.original.reason}</span> },
    { id: "req_times", header: "Requested Times", cell: ({ row }) => <div className="text-xs"><div>In: {toIST(row.original.requested_check_in)}</div><div>Out: {toIST(row.original.requested_check_out)}</div></div> },
    { id: "proof", header: "Proof", cell: ({ row }) => row.original.proof_url ? <button type="button" onClick={() => setCorrProof(row.original.proof_url)} className="text-xs font-medium text-primary hover:underline">View</button> : <span className="text-xs text-muted-foreground">—</span> },
    { accessorKey: "correction_status", header: "Status", cell: ({ row }) => <StatusBadge status={row.original.correction_status} /> },
    {
      id: "actions", header: "",
      cell: ({ row }) => (
        <div className="flex gap-1">
          <Button variant="ghost" size="icon" className="h-7 w-7 text-green-600" onClick={() => { setCorrRemarksTarget({ id: row.original.daily_id, approve: true }); setCorrRemarks(""); }}><CheckCircle className="h-3 w-3" /></Button>
          <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive" onClick={() => { setCorrRemarksTarget({ id: row.original.daily_id, approve: false }); setCorrRemarks(""); }}><XCircle className="h-3 w-3" /></Button>
        </div>
      ),
    },
  ];

  return (
    <PortalLayout navItems={ADMIN_NAV} portalLabel="Admin" pageTitle="Attendance">
      <Tabs defaultValue="records">
        <TabsList><TabsTrigger value="records">Daily Records</TabsTrigger><TabsTrigger value="corrections">Corrections ({corrections.length})</TabsTrigger></TabsList>

        <TabsContent value="records" className="mt-4 space-y-4">
          <div className="flex flex-wrap gap-3">
            <div className="flex items-center gap-2"><Label className="text-xs">From</Label><Input type="date" value={fromDate} onChange={e => setFromDate(e.target.value)} className="w-36 text-sm" /></div>
            <div className="flex items-center gap-2"><Label className="text-xs">To</Label><Input type="date" value={toDate} onChange={e => setToDate(e.target.value)} className="w-36 text-sm" /></div>
            <Select value={statusFilter} onValueChange={setStatusFilter}>
              <SelectTrigger className="w-40"><SelectValue placeholder="All statuses" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All statuses</SelectItem>
                {["PRESENT","ABSENT","LATE","HALF_DAY","ON_LEAVE","WEEKEND","HOLIDAY"].map(s => <SelectItem key={s} value={s}>{s.replace("_"," ")}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          {isLoading ? <Skeleton className="h-64 w-full" /> : <DataTable columns={columns} data={records} pageSize={25} />}
        </TabsContent>

        <TabsContent value="corrections" className="mt-4">
          {corrLoading ? <Skeleton className="h-48 w-full" /> : (
            corrections.length === 0
              ? <div className="flex h-40 items-center justify-center text-muted-foreground">No pending corrections</div>
              : <DataTable columns={corrColumns} data={corrections} pageSize={20} />
          )}
        </TabsContent>
      </Tabs>

      {/* Correction proof modal */}
      <ProofImageModal open={!!corrProof} onOpenChange={o => !o && setCorrProof(null)} src={corrProof} title="Correction Proof" />

      {/* Proof modal */}
      {proofImages.length > 0 ? (
        <ProofImageModal open={proofOpen} onOpenChange={setProofOpen} proofs={proofImages} />
      ) : (
        <Dialog open={proofOpen} onOpenChange={setProofOpen}>
          <DialogContent>
            <DialogHeader><DialogTitle>Proof Images</DialogTitle><DialogDescription>{proofLoading ? "Loading…" : "No proof images available for this day."}</DialogDescription></DialogHeader>
          </DialogContent>
        </Dialog>
      )}

      {/* Override sheet */}
      <Sheet open={!!overrideTarget} onOpenChange={o => !o && setOverrideTarget(null)}>
        <SheetContent className="sm:max-w-md">
          <SheetHeader><SheetTitle>Manual Override</SheetTitle><SheetDescription>Adjust check-in / check-out for {overrideTarget?.date}</SheetDescription></SheetHeader>
          <form onSubmit={overrideForm.handleSubmit(d => overrideTarget && overrideMut.mutate({ empId: overrideTarget.employee_id, date: overrideTarget.date, data: d }))} className="mt-6 space-y-4">
            <div className="space-y-1"><Label>Check-In (local time)</Label><Input type="datetime-local" {...overrideForm.register("check_in")} /></div>
            <div className="space-y-1"><Label>Check-Out (local time)</Label><Input type="datetime-local" {...overrideForm.register("check_out")} /></div>
            <div className="space-y-1"><Label>Notes</Label><Input {...overrideForm.register("notes")} placeholder="Reason for override" /></div>
            <SheetFooter className="pt-2">
              <Button type="button" variant="outline" onClick={() => setOverrideTarget(null)}>Cancel</Button>
              <Button type="submit" disabled={overrideMut.isPending}>{overrideMut.isPending ? "Saving…" : "Apply Override"}</Button>
            </SheetFooter>
          </form>
        </SheetContent>
      </Sheet>

      {/* Correction action dialog */}
      <Dialog open={!!corrRemarksTarget} onOpenChange={o => !o && setCorrRemarksTarget(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader><DialogTitle>{corrRemarksTarget?.approve ? "Approve Correction" : "Reject Correction"}</DialogTitle><DialogDescription>Optionally add remarks</DialogDescription></DialogHeader>
          <div className="space-y-3">
            <Input placeholder="Remarks (optional)" value={corrRemarks} onChange={e => setCorrRemarks(e.target.value)} />
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setCorrRemarksTarget(null)}>Cancel</Button>
              <Button variant={corrRemarksTarget?.approve ? "default" : "destructive"}
                disabled={corrActionMut.isPending}
                onClick={() => corrRemarksTarget && corrActionMut.mutate({ id: corrRemarksTarget.id, approve: corrRemarksTarget.approve, remarks: corrRemarks || undefined })}>
                {corrActionMut.isPending ? "…" : (corrRemarksTarget?.approve ? "Approve" : "Reject")}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </PortalLayout>
  );
}
