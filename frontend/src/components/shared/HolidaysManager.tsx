"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm, Controller } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { ColumnDef } from "@tanstack/react-table";
import { Plus, Trash2, Palmtree } from "lucide-react";

import { PortalLayout } from "@/components/shared/Layout";
import { DataTable } from "@/components/shared/DataTable";
import { ConfirmDialog } from "@/components/shared/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription, SheetFooter } from "@/components/ui/sheet";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { apiGet, apiPost, apiPut, apiDelete } from "@/lib/api";

interface Holiday { id: string; name: string; date: string; branch_id: string | null; holiday_type: string; year: number }
interface Branch { id: string; name: string }

// Reuse PortalLayout's own navItems type so HR/Admin nav arrays both fit.
type NavItems = React.ComponentProps<typeof PortalLayout>["navItems"];

const schema = z.object({
  name: z.string().min(1).max(200),
  date: z.string().min(1, "Required"),
  holiday_type: z.enum(["national", "regional", "optional"]),
  branch_id: z.string().uuid().optional().or(z.literal("")),
});
type HolidayForm = z.infer<typeof schema>;

const TYPE_COLORS: Record<string, string> = {
  national: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400",
  regional: "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400",
  optional: "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-300",
};

/**
 * Holiday calendar management — shared by the HR and Admin portals.
 * Both portals render this with their own nav so the only difference is chrome.
 */
export function HolidaysManager({ navItems, portalLabel }: { navItems: NavItems; portalLabel: string }) {
  const qc = useQueryClient();
  const [year, setYear] = useState(String(new Date().getFullYear()));
  const [branchFilter, setBranchFilter] = useState("all");
  const [sheetOpen, setSheetOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Holiday | null>(null);

  const { data: branchResp } = useQuery({ queryKey: ["branches"], queryFn: () => apiGet<Branch[]>("/branches") });
  const { data: holidayResp, isLoading } = useQuery({
    queryKey: ["holidays", year, branchFilter],
    queryFn: () => apiGet<Holiday[]>("/system/holidays", {
      year: Number(year),
      ...(branchFilter !== "all" ? { branch_id: branchFilter } : {}),
    }),
  });

  const holidays = holidayResp?.data ?? [];
  const branches = branchResp?.data ?? [];

  // Weekly-off configuration: Sunday is always off; Saturday is toggleable.
  const { data: weekendResp } = useQuery({
    queryKey: ["weekend-config"],
    queryFn: () => apiGet<{ saturday_off: boolean }>("/system/weekend-config"),
  });
  const saturdayOff = weekendResp?.data?.saturday_off ?? true;
  const weekendMut = useMutation({
    mutationFn: (v: boolean) => apiPut("/system/weekend-config", { saturday_off: v }),
    onSuccess: () => { toast.success("Weekly-off setting updated"); qc.invalidateQueries({ queryKey: ["weekend-config"] }); },
    onError: (e: Error) => toast.error(e.message),
  });

  const form = useForm<HolidayForm>({
    resolver: zodResolver(schema),
    defaultValues: { holiday_type: "national" },
  });

  const createMut = useMutation({
    mutationFn: (d: HolidayForm) => apiPost("/system/holidays", {
      name: d.name,
      date: d.date,
      holiday_type: d.holiday_type,
      branch_id: d.branch_id || undefined,
    }),
    onSuccess: () => { toast.success("Holiday added"); setSheetOpen(false); form.reset({ holiday_type: "national" }); qc.invalidateQueries({ queryKey: ["holidays"] }); },
    onError: (e: Error) => toast.error(e.message),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => apiDelete(`/system/holidays/${id}`),
    onSuccess: () => { toast.success("Holiday removed"); setDeleteTarget(null); qc.invalidateQueries({ queryKey: ["holidays"] }); },
    onError: (e: Error) => toast.error(e.message),
  });

  const columns: ColumnDef<Holiday>[] = [
    { accessorKey: "date", header: "Date", cell: ({ row }) => <span className="font-medium">{new Date(row.original.date).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" })}</span> },
    { id: "day", header: "Day", cell: ({ row }) => <span className="text-sm text-muted-foreground">{new Date(row.original.date).toLocaleDateString("en-IN", { weekday: "long" })}</span> },
    { accessorKey: "name", header: "Holiday" },
    { accessorKey: "holiday_type", header: "Type", cell: ({ row }) => <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${TYPE_COLORS[row.original.holiday_type] ?? ""}`}>{row.original.holiday_type}</span> },
    { id: "branch", header: "Branch", cell: ({ row }) => row.original.branch_id ? <span className="text-xs">{branches.find(b => b.id === row.original.branch_id)?.name ?? "Unknown"}</span> : <span className="text-xs text-muted-foreground">All branches</span> },
    {
      id: "actions", header: "",
      cell: ({ row }) => <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setDeleteTarget(row.original)}><Trash2 className="h-3 w-3 text-destructive" /></Button>,
    },
  ];

  return (
    <PortalLayout navItems={navItems} portalLabel={portalLabel} pageTitle="Holiday Calendar">
      <div className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-2xl font-bold">Holiday Calendar</h2>
            <p className="text-sm text-muted-foreground">{holidays.length} holidays in {year}</p>
          </div>
          <Button onClick={() => { form.reset({ holiday_type: "national" }); setSheetOpen(true); }}>
            <Plus className="mr-2 h-4 w-4" />Add Holiday
          </Button>
        </div>

        {/* Weekly off — Sunday is always off; Saturday is configurable. */}
        <div className="flex items-center justify-between rounded-lg border bg-card p-4">
          <div>
            <p className="font-medium">Saturday is a weekly off</p>
            <p className="text-sm text-muted-foreground">
              Sunday is always off. Turn this on to also treat every Saturday as a weekly off
              (marked WEEKEND, not counted absent).
            </p>
          </div>
          <Switch
            checked={saturdayOff}
            disabled={weekendMut.isPending}
            onCheckedChange={(v) => weekendMut.mutate(v)}
          />
        </div>

        <div className="flex flex-wrap gap-3">
          <Input type="number" value={year} onChange={e => setYear(e.target.value)} className="w-24" placeholder="Year" />
          <Select value={branchFilter} onValueChange={setBranchFilter}>
            <SelectTrigger className="w-44"><SelectValue placeholder="All branches" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All branches</SelectItem>
              {branches.map(b => <SelectItem key={b.id} value={b.id}>{b.name}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>

        {isLoading ? <Skeleton className="h-64 w-full" /> : (
          holidays.length === 0
            ? <div className="flex h-40 flex-col items-center justify-center gap-2 text-muted-foreground"><Palmtree className="h-8 w-8" /><p>No holidays for {year}</p></div>
            : <DataTable columns={columns} data={holidays} pageSize={20} filterColumn="name" filterPlaceholder="Filter holidays…" />
        )}
      </div>

      <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
        <SheetContent className="sm:max-w-md">
          <SheetHeader><SheetTitle>Add Holiday</SheetTitle><SheetDescription>Add a public holiday to the calendar</SheetDescription></SheetHeader>
          <form onSubmit={form.handleSubmit(d => createMut.mutate(d))} className="mt-6 space-y-4">
            <div className="space-y-1"><Label>Holiday Name*</Label><Input {...form.register("name")} placeholder="e.g. Independence Day" /><p className="text-xs text-destructive">{form.formState.errors.name?.message}</p></div>
            <div className="space-y-1"><Label>Date*</Label><Input type="date" {...form.register("date")} /><p className="text-xs text-destructive">{form.formState.errors.date?.message}</p></div>
            <div className="space-y-1"><Label>Type*</Label>
              <Controller control={form.control} name="holiday_type" render={({ field }) => (
                <Select value={field.value} onValueChange={field.onChange}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="national">National (all branches)</SelectItem>
                    <SelectItem value="regional">Regional (state holiday)</SelectItem>
                    <SelectItem value="optional">Optional</SelectItem>
                  </SelectContent>
                </Select>
              )} />
            </div>
            <div className="space-y-1"><Label>Branch (leave blank for all)</Label>
              <Controller control={form.control} name="branch_id" render={({ field }) => (
                <Select value={field.value || "all"} onValueChange={(v) => field.onChange(v === "all" ? "" : v)}>
                  <SelectTrigger><SelectValue placeholder="All branches" /></SelectTrigger>
                  <SelectContent><SelectItem value="all">All branches</SelectItem>{branches.map(b => <SelectItem key={b.id} value={b.id}>{b.name}</SelectItem>)}</SelectContent>
                </Select>
              )} />
            </div>
            <SheetFooter>
              <Button type="button" variant="outline" onClick={() => setSheetOpen(false)}>Cancel</Button>
              <Button type="submit" disabled={createMut.isPending}>{createMut.isPending ? "Adding…" : "Add Holiday"}</Button>
            </SheetFooter>
          </form>
        </SheetContent>
      </Sheet>

      <ConfirmDialog open={!!deleteTarget} onOpenChange={o => !o && setDeleteTarget(null)}
        title={`Remove "${deleteTarget?.name}"?`}
        description="This will remove the holiday from the calendar for all employees."
        confirmLabel="Remove" destructive
        onConfirm={() => deleteTarget && deleteMut.mutate(deleteTarget.id)}
        isLoading={deleteMut.isPending} />
    </PortalLayout>
  );
}
