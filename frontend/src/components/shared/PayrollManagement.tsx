"use client";

// Shared Payroll management screen for BOTH the HR and Admin portals.

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm, Controller } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { ColumnDef } from "@tanstack/react-table";
import { Download, Play } from "lucide-react";

import { PortalLayout } from "@/components/shared/Layout";
import type { NavEntry } from "@/components/shared/sidebar";
import { DataTable } from "@/components/shared/DataTable";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { apiGet, apiPost } from "@/lib/api";
import { formatPaise, downloadFile } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth-store";
import { API_BASE } from "@/lib/constants";

interface Policy { late_days_per_unit: number; penalty_percent_per_unit: number; grace_days: number; salary_days_per_month: number }
interface SalaryDeduction { id: string; employee_code: string; employee_name: string; month: number; year: number; late_count: number; penalty_units: number; net_penalty_days: number; monthly_salary_paise: number; daily_salary_paise: number; total_deduction_paise: number }
interface Employee { id: string; first_name: string; last_name: string; employee_code: string }

const calcSchema = z.object({
  employee_id: z.string().uuid("Select an employee"),
  month: z.coerce.number().int().min(1).max(12),
  year: z.coerce.number().int().min(2020).max(2100),
});
type CalcForm = z.infer<typeof calcSchema>;

const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

export function PayrollManagement({ navItems, portalLabel }: { navItems: NavEntry[]; portalLabel: string }) {
  const qc = useQueryClient();
  const { token } = useAuthStore();
  const [dedMonth, setDedMonth] = useState(String(new Date().getMonth() + 1));
  const [dedYear, setDedYear] = useState(String(new Date().getFullYear()));
  const [dlFormat, setDlFormat] = useState<"xlsx"|"csv">("xlsx");
  const [dlMonth, setDlMonth] = useState(String(new Date().getMonth() + 1));
  const [dlYear, setDlYear] = useState(String(new Date().getFullYear()));

  const { data: policyResp, isLoading: policyLoading } = useQuery({ queryKey: ["payroll-policy"], queryFn: () => apiGet<Policy>("/payroll/policy") });
  const { data: dedsResp, isLoading: dedsLoading } = useQuery({
    queryKey: ["payroll-deductions", dedMonth, dedYear],
    queryFn: () => apiGet<SalaryDeduction[]>("/payroll/deductions", { month: Number(dedMonth), year: Number(dedYear), per_page: 100 }),
  });
  const { data: empResp } = useQuery({ queryKey: ["employees-list"], queryFn: () => apiGet<Employee[]>("/employees", { per_page: 100 }) });

  const policy = policyResp?.data;
  const deductions = dedsResp?.data ?? [];
  const employees = empResp?.data ?? [];

  const calcForm = useForm<CalcForm>({
    resolver: zodResolver(calcSchema),
    defaultValues: { month: new Date().getMonth() + 1, year: new Date().getFullYear() },
  });

  const calcMut = useMutation({
    mutationFn: (d: CalcForm) => apiPost("/payroll/deductions/calculate", d),
    onSuccess: () => { toast.success("Deduction calculated"); qc.invalidateQueries({ queryKey: ["payroll-deductions"] }); calcForm.reset(); },
    onError: (e: Error) => toast.error(e.message),
  });

  const handleDownload = async () => {
    const url = `${API_BASE}/payroll/reports/monthly?month=${dlMonth}&year=${dlYear}&format=${dlFormat}`;
    try {
      await downloadFile(url, `payroll_${dlYear}_${String(dlMonth).padStart(2,"0")}.${dlFormat}`, token);
    } catch (e: unknown) {
      toast.error((e as Error).message || "Download failed");
    }
  };

  const dedCols: ColumnDef<SalaryDeduction>[] = [
    { accessorKey: "employee_code", header: "Code", cell: ({ row }) => <code className="text-xs bg-muted px-1 rounded">{row.original.employee_code}</code> },
    { accessorKey: "employee_name", header: "Employee" },
    { id: "period", header: "Period", cell: ({ row }) => <span className="text-xs">{MONTHS[row.original.month-1]} {row.original.year}</span> },
    { accessorKey: "late_count", header: "Late Days" },
    { accessorKey: "penalty_units", header: "Units" },
    { accessorKey: "net_penalty_days", header: "Net Days", cell: ({ row }) => <span className="text-xs">{row.original.net_penalty_days}</span> },
    { accessorKey: "monthly_salary_paise", header: "Monthly Salary", cell: ({ row }) => <span className="text-xs">{formatPaise(row.original.monthly_salary_paise)}</span> },
    { accessorKey: "total_deduction_paise", header: "Total Deduction", cell: ({ row }) => <span className="font-semibold text-destructive">{formatPaise(row.original.total_deduction_paise)}</span> },
  ];

  return (
    <PortalLayout navItems={navItems} portalLabel={portalLabel} pageTitle="Payroll">
      <Tabs defaultValue="deductions">
        <TabsList>
          <TabsTrigger value="deductions">Deduction Records</TabsTrigger>
          <TabsTrigger value="policy">Policy</TabsTrigger>
          <TabsTrigger value="calculate">Run Calculation</TabsTrigger>
          <TabsTrigger value="download">Download Report</TabsTrigger>
        </TabsList>

        <TabsContent value="deductions" className="mt-4 space-y-4">
          <div className="flex flex-wrap gap-3">
            <Select value={dedMonth} onValueChange={setDedMonth}>
              <SelectTrigger className="w-32"><SelectValue /></SelectTrigger>
              <SelectContent>{MONTHS.map((m,i) => <SelectItem key={i+1} value={String(i+1)}>{m}</SelectItem>)}</SelectContent>
            </Select>
            <Input type="number" value={dedYear} onChange={e => setDedYear(e.target.value)} className="w-24" />
          </div>
          {dedsLoading ? <Skeleton className="h-48 w-full" /> : (
            deductions.length === 0
              ? <div className="flex h-32 items-center justify-center text-muted-foreground">No deductions for {MONTHS[Number(dedMonth)-1]} {dedYear}</div>
              : <DataTable columns={dedCols} data={deductions} pageSize={20} />
          )}
        </TabsContent>

        <TabsContent value="policy" className="mt-4">
          {policyLoading ? <Skeleton className="h-32 w-full max-w-md" /> : (
            <div className="rounded-lg border bg-card p-6 max-w-md space-y-4">
              <h3 className="font-semibold">Late Penalty Policy</h3>
              <p className="text-sm text-muted-foreground">
                For every <b>N</b> late days, deduct <b>P%</b> of a day&apos;s salary. The first
                <b> G</b> penalty-days each month are forgiven. A day&apos;s salary = monthly salary ÷ <b>D</b>.
              </p>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
                <div>
                  <dt className="text-muted-foreground">Late days per penalty (N)</dt>
                  <dd className="font-semibold">{policy?.late_days_per_unit ?? "—"}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">% of day per penalty (P)</dt>
                  <dd className="font-semibold">{policy?.penalty_percent_per_unit ?? "—"}%</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Grace days / month (G)</dt>
                  <dd className="font-semibold">{policy?.grace_days ?? "—"}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Salary days / month (D)</dt>
                  <dd className="font-semibold">{policy?.salary_days_per_month ?? "—"}</dd>
                </div>
              </dl>
              <p className="rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">
                These values are configured in <b>Admin → Settings → Attendance Rules</b> —
                the single place for penalty rules — and shown here for reference.
              </p>
            </div>
          )}
        </TabsContent>

        <TabsContent value="calculate" className="mt-4">
          <div className="rounded-lg border bg-card p-6 max-w-md space-y-4">
            <h3 className="font-semibold">Calculate Deduction</h3>
            <p className="text-sm text-muted-foreground">Compute (or recompute) the late penalty for one employee for a specific month.</p>
            <form onSubmit={calcForm.handleSubmit(d => calcMut.mutate(d))} className="space-y-4">
              <div className="space-y-1"><Label>Employee*</Label>
                <Controller control={calcForm.control} name="employee_id" render={({ field }) => (
                  <Select value={field.value} onValueChange={field.onChange}><SelectTrigger><SelectValue placeholder="Select employee" /></SelectTrigger><SelectContent>{employees.map(e => <SelectItem key={e.id} value={e.id}>{e.first_name} {e.last_name} ({e.employee_code})</SelectItem>)}</SelectContent></Select>
                )} />
                <p className="text-xs text-destructive">{calcForm.formState.errors.employee_id?.message}</p>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1"><Label>Month</Label>
                  <Controller control={calcForm.control} name="month" render={({ field }) => (
                    <Select value={String(field.value)} onValueChange={v => field.onChange(Number(v))}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{MONTHS.map((m,i) => <SelectItem key={i+1} value={String(i+1)}>{m}</SelectItem>)}</SelectContent></Select>
                  )} />
                </div>
                <div className="space-y-1"><Label>Year</Label><Input type="number" {...calcForm.register("year")} /></div>
              </div>
              <Button type="submit" disabled={calcMut.isPending}><Play className="mr-2 h-4 w-4" />{calcMut.isPending ? "Calculating…" : "Run Calculation"}</Button>
            </form>
          </div>
        </TabsContent>

        <TabsContent value="download" className="mt-4">
          <div className="rounded-lg border bg-card p-6 max-w-md space-y-4">
            <h3 className="font-semibold">Download Payroll Report</h3>
            <div className="flex gap-3">
              <Select value={dlMonth} onValueChange={setDlMonth}>
                <SelectTrigger className="flex-1"><SelectValue /></SelectTrigger>
                <SelectContent>{MONTHS.map((m,i) => <SelectItem key={i+1} value={String(i+1)}>{m}</SelectItem>)}</SelectContent>
              </Select>
              <Input type="number" value={dlYear} onChange={e => setDlYear(e.target.value)} className="w-24" />
              <Select value={dlFormat} onValueChange={v => setDlFormat(v as "xlsx"|"csv")}>
                <SelectTrigger className="w-24"><SelectValue /></SelectTrigger>
                <SelectContent><SelectItem value="xlsx">Excel</SelectItem><SelectItem value="csv">CSV</SelectItem></SelectContent>
              </Select>
            </div>
            <Button onClick={handleDownload}><Download className="mr-2 h-4 w-4" />Download {MONTHS[Number(dlMonth)-1]} {dlYear} Report</Button>
          </div>
        </TabsContent>
      </Tabs>
    </PortalLayout>
  );
}
