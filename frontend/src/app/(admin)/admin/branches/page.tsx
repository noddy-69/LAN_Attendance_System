"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { ColumnDef } from "@tanstack/react-table";
import { Plus, Pencil, Trash2 } from "lucide-react";

import { PortalLayout } from "@/components/shared/Layout";
import { ADMIN_NAV } from "@/components/admin/nav";
import { DataTable } from "@/components/shared/DataTable";
import { ConfirmDialog } from "@/components/shared/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
  SheetFooter,
} from "@/components/ui/sheet";
import { apiGet, apiPost, apiPatch, apiDelete } from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────────────────────

interface Branch {
  id: string;
  name: string;
  city: string;
  state: string;
  address: string | null;
  office_start_time: string;
  office_end_time: string;
  grace_period_minutes: number | null; // null = inherit the org-wide default (Settings)
  employee_count: number;
}

// ── Zod Schema ────────────────────────────────────────────────────────────────

const schema = z.object({
  name: z.string().min(1, "Name is required").max(150),
  city: z.string().min(1, "City is required").max(100),
  state: z.string().min(1, "State is required").max(100),
  address: z.string().optional(),
  office_start_time: z
    .string()
    .regex(/^\d{2}:\d{2}$/, "Time must be in HH:MM format"),
  office_end_time: z
    .string()
    .regex(/^\d{2}:\d{2}$/, "Time must be in HH:MM format"),
  // Blank = inherit the org-wide default from Admin → Settings (stored as null).
  grace_period_minutes: z.preprocess(
    (v) => (v === "" || v === null || v === undefined ? null : v),
    z.coerce.number().int().min(0).max(120).nullable()
  ),
});

type FormValues = z.infer<typeof schema>;

// ── BranchForm ────────────────────────────────────────────────────────────────

function BranchForm({
  defaultValues,
  onSubmit,
  isLoading,
}: {
  defaultValues: Partial<FormValues>;
  onSubmit: (values: FormValues) => void;
  isLoading: boolean;
}) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      grace_period_minutes: null,
      office_start_time: "09:00",
      office_end_time: "18:00",
      ...defaultValues,
    },
  });

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4">
      <div className="space-y-1">
        <Label htmlFor="name">Branch Name *</Label>
        <Input id="name" {...register("name")} placeholder="Head Office" />
        {errors.name && <p className="text-xs text-destructive">{errors.name.message}</p>}
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-1">
          <Label htmlFor="city">City *</Label>
          <Input id="city" {...register("city")} placeholder="Mumbai" />
          {errors.city && <p className="text-xs text-destructive">{errors.city.message}</p>}
        </div>
        <div className="space-y-1">
          <Label htmlFor="state">State *</Label>
          <Input id="state" {...register("state")} placeholder="Maharashtra" />
          {errors.state && <p className="text-xs text-destructive">{errors.state.message}</p>}
        </div>
      </div>

      <div className="space-y-1">
        <Label htmlFor="address">Address</Label>
        <Textarea id="address" {...register("address")} placeholder="123, Business Park, Andheri East" />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-1">
          <Label htmlFor="office_start_time">Office Start *</Label>
          <Input id="office_start_time" type="time" {...register("office_start_time")} />
          {errors.office_start_time && (
            <p className="text-xs text-destructive">{errors.office_start_time.message}</p>
          )}
        </div>
        <div className="space-y-1">
          <Label htmlFor="office_end_time">Office End *</Label>
          <Input id="office_end_time" type="time" {...register("office_end_time")} />
          {errors.office_end_time && (
            <p className="text-xs text-destructive">{errors.office_end_time.message}</p>
          )}
        </div>
      </div>

      <div className="space-y-1">
        <Label htmlFor="grace_period_minutes">Grace Period (minutes)</Label>
        <Input
          id="grace_period_minutes"
          type="number"
          min={0}
          max={120}
          {...register("grace_period_minutes")}
          placeholder="Leave blank to use the default"
        />
        <p className="text-xs text-muted-foreground">
          Minutes after office start before a check-in counts as late. Leave blank to
          inherit the org-wide default from Admin → Settings.
        </p>
        {errors.grace_period_minutes && (
          <p className="text-xs text-destructive">{errors.grace_period_minutes.message}</p>
        )}
      </div>

      <SheetFooter className="mt-4">
        <Button type="submit" disabled={isLoading} className="w-full">
          {isLoading ? "Saving…" : "Save Branch"}
        </Button>
      </SheetFooter>
    </form>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function BranchesPage() {
  const qc = useQueryClient();
  const [sheetOpen, setSheetOpen] = useState(false);
  const [editingBranch, setEditingBranch] = useState<Branch | null>(null);
  const [deleteBranch, setDeleteBranch] = useState<Branch | null>(null);

  const { data: branchesResp, isLoading } = useQuery({
    queryKey: ["branches"],
    queryFn: () => apiGet<Branch[]>("/branches"),
  });

  const branches = branchesResp?.data ?? [];

  const createMutation = useMutation({
    mutationFn: (body: FormValues) => apiPost<Branch>("/branches", body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["branches"] });
      toast.success("Branch created successfully");
      setSheetOpen(false);
    },
    onError: (err: Error) => toast.error(err.message || "Failed to create branch"),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<FormValues> }) =>
      apiPatch<Branch>(`/branches/${id}`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["branches"] });
      toast.success("Branch updated successfully");
      setSheetOpen(false);
      setEditingBranch(null);
    },
    onError: (err: Error) => toast.error(err.message || "Failed to update branch"),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiDelete(`/branches/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["branches"] });
      toast.success("Branch deleted");
      setDeleteBranch(null);
    },
    onError: (err: Error) => toast.error(err.message || "Failed to delete branch"),
  });

  const columns: ColumnDef<Branch>[] = [
    {
      accessorKey: "name",
      header: "Name",
      cell: ({ row }) => <span className="font-medium">{row.original.name}</span>,
    },
    { accessorKey: "city", header: "City" },
    { accessorKey: "state", header: "State" },
    {
      id: "office_hours",
      header: "Office Hours",
      cell: ({ row }) => (
        <span className="text-sm">
          {row.original.office_start_time} – {row.original.office_end_time}
        </span>
      ),
    },
    {
      accessorKey: "grace_period_minutes",
      header: "Grace (min)",
      cell: ({ row }) =>
        row.original.grace_period_minutes === null ? (
          <span className="text-muted-foreground">Default</span>
        ) : (
          row.original.grace_period_minutes
        ),
    },
    {
      accessorKey: "employee_count",
      header: "Employees",
    },
    {
      id: "actions",
      header: "Actions",
      cell: ({ row }) => (
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => {
              setEditingBranch(row.original);
              setSheetOpen(true);
            }}
          >
            <Pencil className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="text-destructive hover:text-destructive"
            onClick={() => setDeleteBranch(row.original)}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      ),
    },
  ];

  const handleSubmit = (values: FormValues) => {
    if (editingBranch) {
      updateMutation.mutate({ id: editingBranch.id, body: values });
    } else {
      createMutation.mutate(values);
    }
  };

  const isMutating = createMutation.isPending || updateMutation.isPending;

  return (
    <PortalLayout navItems={ADMIN_NAV} portalLabel="Admin" pageTitle="Branches">
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-bold">Branches</h2>
            <p className="text-muted-foreground">Manage office branches and their settings</p>
          </div>
          <Button
            onClick={() => {
              setEditingBranch(null);
              setSheetOpen(true);
            }}
          >
            <Plus className="mr-2 h-4 w-4" />
            Add Branch
          </Button>
        </div>

        {isLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        ) : (
          <DataTable columns={columns} data={branches} filterColumn="name" filterPlaceholder="Search branches…" />
        )}
      </div>

      <Sheet
        open={sheetOpen}
        onOpenChange={(open) => {
          setSheetOpen(open);
          if (!open) setEditingBranch(null);
        }}
      >
        <SheetContent className="overflow-y-auto">
          <SheetHeader className="mb-4">
            <SheetTitle>{editingBranch ? "Edit Branch" : "Add Branch"}</SheetTitle>
            <SheetDescription>
              {editingBranch ? "Update branch details." : "Configure a new office branch."}
            </SheetDescription>
          </SheetHeader>
          <BranchForm
            defaultValues={
              editingBranch
                ? {
                    name: editingBranch.name,
                    city: editingBranch.city,
                    state: editingBranch.state,
                    address: editingBranch.address ?? undefined,
                    office_start_time: editingBranch.office_start_time,
                    office_end_time: editingBranch.office_end_time,
                    grace_period_minutes: editingBranch.grace_period_minutes,
                  }
                : {}
            }
            onSubmit={handleSubmit}
            isLoading={isMutating}
          />
        </SheetContent>
      </Sheet>

      <ConfirmDialog
        open={!!deleteBranch}
        onOpenChange={(open) => !open && setDeleteBranch(null)}
        title="Delete Branch"
        description={
          deleteBranch
            ? `Delete "${deleteBranch.name}"? This branch has ${deleteBranch.employee_count} employee(s). This action cannot be undone.`
            : ""
        }
        confirmLabel="Delete"
        destructive
        onConfirm={() => deleteBranch && deleteMutation.mutate(deleteBranch.id)}
        isLoading={deleteMutation.isPending}
      />
    </PortalLayout>
  );
}
