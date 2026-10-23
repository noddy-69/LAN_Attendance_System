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
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
  SheetFooter,
} from "@/components/ui/sheet";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { apiGet, apiPost, apiPatch, apiDelete } from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────────────────────

interface Branch {
  id: string;
  name: string;
}

interface EmployeeSummary {
  id: string;
  first_name: string;
  last_name: string;
}

interface Department {
  id: string;
  name: string;
  branch_id: string;
  branch_name: string;
  head_employee_id: string | null;
  head_employee_name: string | null;
  employee_count: number;
}

// ── Schema ────────────────────────────────────────────────────────────────────

const schema = z.object({
  name: z.string().min(1, "Name is required").max(150),
  branch_id: z.string().uuid("Branch is required"),
  head_employee_id: z.string().uuid().optional().or(z.literal("")),
});

type FormValues = z.infer<typeof schema>;

// ── DepartmentForm ────────────────────────────────────────────────────────────

function DepartmentForm({
  branches,
  employees,
  defaultValues,
  onSubmit,
  isLoading,
}: {
  branches: Branch[];
  employees: EmployeeSummary[];
  defaultValues: Partial<FormValues>;
  onSubmit: (values: FormValues) => void;
  isLoading: boolean;
}) {
  const {
    register,
    handleSubmit,
    setValue,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues,
  });

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4">
      <div className="space-y-1">
        <Label htmlFor="name">Department Name *</Label>
        <Input id="name" {...register("name")} placeholder="Engineering" />
        {errors.name && <p className="text-xs text-destructive">{errors.name.message}</p>}
      </div>

      <div className="space-y-1">
        <Label>Branch *</Label>
        <Select
          defaultValue={defaultValues.branch_id}
          onValueChange={(v) => setValue("branch_id", v)}
        >
          <SelectTrigger>
            <SelectValue placeholder="Select branch" />
          </SelectTrigger>
          <SelectContent>
            {branches.map((b) => (
              <SelectItem key={b.id} value={b.id}>
                {b.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {errors.branch_id && (
          <p className="text-xs text-destructive">{errors.branch_id.message}</p>
        )}
      </div>

      <div className="space-y-1">
        <Label>Department Head (optional)</Label>
        <Select
          defaultValue={defaultValues.head_employee_id ?? "none"}
          onValueChange={(v) => setValue("head_employee_id", v === "none" ? "" : v)}
        >
          <SelectTrigger>
            <SelectValue placeholder="Select employee" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="none">— None —</SelectItem>
            {employees.map((e) => (
              <SelectItem key={e.id} value={e.id}>
                {e.first_name} {e.last_name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <SheetFooter className="mt-4">
        <Button type="submit" disabled={isLoading} className="w-full">
          {isLoading ? "Saving…" : "Save Department"}
        </Button>
      </SheetFooter>
    </form>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function DepartmentsPage() {
  const qc = useQueryClient();
  const [sheetOpen, setSheetOpen] = useState(false);
  const [editingDept, setEditingDept] = useState<Department | null>(null);
  const [deleteDept, setDeleteDept] = useState<Department | null>(null);

  const { data: deptResp, isLoading: deptLoading } = useQuery({
    queryKey: ["departments"],
    queryFn: () => apiGet<Department[]>("/departments"),
  });

  const { data: branchesResp } = useQuery({
    queryKey: ["branches"],
    queryFn: () => apiGet<Branch[]>("/branches"),
  });

  const { data: employeesResp } = useQuery({
    queryKey: ["employees-list"],
    queryFn: () => apiGet<EmployeeSummary[]>("/employees", { per_page: 200 }),
  });

  const departments = deptResp?.data ?? [];
  const branches = branchesResp?.data ?? [];
  const employees = employeesResp?.data ?? [];

  const createMutation = useMutation({
    mutationFn: (body: FormValues) =>
      apiPost<Department>("/departments", {
        ...body,
        head_employee_id: body.head_employee_id || null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["departments"] });
      toast.success("Department created");
      setSheetOpen(false);
    },
    onError: (err: Error) => toast.error(err.message || "Failed to create department"),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<FormValues> }) =>
      apiPatch<Department>(`/departments/${id}`, {
        ...body,
        head_employee_id: body.head_employee_id || null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["departments"] });
      toast.success("Department updated");
      setSheetOpen(false);
      setEditingDept(null);
    },
    onError: (err: Error) => toast.error(err.message || "Failed to update department"),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiDelete(`/departments/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["departments"] });
      toast.success("Department deleted");
      setDeleteDept(null);
    },
    onError: (err: Error) => toast.error(err.message || "Failed to delete department"),
  });

  const columns: ColumnDef<Department>[] = [
    {
      accessorKey: "name",
      header: "Name",
      cell: ({ row }) => <span className="font-medium">{row.original.name}</span>,
    },
    { accessorKey: "branch_name", header: "Branch" },
    {
      accessorKey: "head_employee_name",
      header: "Head",
      cell: ({ row }) => row.original.head_employee_name ?? <span className="text-muted-foreground">—</span>,
    },
    { accessorKey: "employee_count", header: "Employees" },
    {
      id: "actions",
      header: "Actions",
      cell: ({ row }) => (
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => {
              setEditingDept(row.original);
              setSheetOpen(true);
            }}
          >
            <Pencil className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="text-destructive hover:text-destructive"
            onClick={() => setDeleteDept(row.original)}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      ),
    },
  ];

  const handleSubmit = (values: FormValues) => {
    if (editingDept) {
      updateMutation.mutate({ id: editingDept.id, body: values });
    } else {
      createMutation.mutate(values);
    }
  };

  const isMutating = createMutation.isPending || updateMutation.isPending;

  return (
    <PortalLayout navItems={ADMIN_NAV} portalLabel="Admin" pageTitle="Departments">
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-bold">Departments</h2>
            <p className="text-muted-foreground">Manage departments across all branches</p>
          </div>
          <Button
            onClick={() => {
              setEditingDept(null);
              setSheetOpen(true);
            }}
          >
            <Plus className="mr-2 h-4 w-4" />
            Add Department
          </Button>
        </div>

        {deptLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        ) : (
          <DataTable
            columns={columns}
            data={departments}
            filterColumn="name"
            filterPlaceholder="Search departments…"
          />
        )}
      </div>

      <Sheet
        open={sheetOpen}
        onOpenChange={(open) => {
          setSheetOpen(open);
          if (!open) setEditingDept(null);
        }}
      >
        <SheetContent className="overflow-y-auto">
          <SheetHeader className="mb-4">
            <SheetTitle>{editingDept ? "Edit Department" : "Add Department"}</SheetTitle>
            <SheetDescription>
              {editingDept ? "Update department details." : "Create a new department."}
            </SheetDescription>
          </SheetHeader>
          <DepartmentForm
            branches={branches}
            employees={employees}
            defaultValues={
              editingDept
                ? {
                    name: editingDept.name,
                    branch_id: editingDept.branch_id,
                    head_employee_id: editingDept.head_employee_id ?? "",
                  }
                : {}
            }
            onSubmit={handleSubmit}
            isLoading={isMutating}
          />
        </SheetContent>
      </Sheet>

      <ConfirmDialog
        open={!!deleteDept}
        onOpenChange={(open) => !open && setDeleteDept(null)}
        title="Delete Department"
        description={`Delete "${deleteDept?.name}"? This cannot be undone.`}
        confirmLabel="Delete"
        destructive
        onConfirm={() => deleteDept && deleteMutation.mutate(deleteDept.id)}
        isLoading={deleteMutation.isPending}
      />
    </PortalLayout>
  );
}
