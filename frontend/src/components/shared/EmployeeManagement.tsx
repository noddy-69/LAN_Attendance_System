"use client";

// Shared Employee management screen for BOTH the HR and Admin portals — so they are
// identical (same columns, same Add/Edit Employee form).

import { useState, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { ColumnDef } from "@tanstack/react-table";
import { Plus, Pencil, Trash2, UserX, UserCheck, Camera } from "lucide-react";

import { PortalLayout } from "@/components/shared/Layout";
import type { NavEntry } from "@/components/shared/sidebar";
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
import { StatusBadge } from "@/components/shared/StatusBadge";
import { formatRoleName, istToday } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

interface Branch {
  id: string;
  name: string;
}

interface Department {
  id: string;
  name: string;
}

interface Role {
  id: string;
  name: string;
}

interface DailyAtt {
  employee_id: string;
  status: string;
}

interface Employee {
  id: string;
  employee_code: string;
  first_name: string;
  last_name: string;
  email: string;
  role_id: string;
  role_name: string;
  branch_id: string;
  branch_name: string;
  department_id: string | null;
  department_name: string | null;
  is_active: boolean;
  date_of_joining: string;
  monthly_salary_paise: number;
  phone: string | null;
}

// ── Schemas ───────────────────────────────────────────────────────────────────

const createSchema = z.object({
  employee_code: z.string().min(1, "Employee code is required").max(20),
  first_name: z.string().min(1, "First name is required").max(100),
  last_name: z.string().min(1, "Last name is required").max(100),
  email: z.string().email("Invalid email"),
  password: z.string().min(8, "Password must be at least 8 characters"),
  phone: z.string().optional(),
  role_id: z.string().uuid("Role is required"),
  branch_id: z.string().uuid("Branch is required"),
  department_id: z.string().uuid().optional().or(z.literal("")),
  date_of_joining: z.string().min(1, "Date of joining is required"),
  monthly_salary: z.coerce.number().min(0, "Must be ≥ 0").optional(),
});

const updateSchema = z.object({
  first_name: z.string().min(1).max(100).optional(),
  last_name: z.string().min(1).max(100).optional(),
  phone: z.string().optional(),
  // Optional admin password reset — blank means "leave the password unchanged".
  password: z.string().min(8, "Password must be at least 8 characters").optional().or(z.literal("")),
  role_id: z.string().uuid().optional(),
  branch_id: z.string().uuid().optional(),
  department_id: z.string().uuid().optional().or(z.literal("")),
  monthly_salary: z.coerce.number().min(0, "Must be ≥ 0").optional(),
});

type CreateValues = z.infer<typeof createSchema>;
type UpdateValues = z.infer<typeof updateSchema>;

// ── EmployeeForm ──────────────────────────────────────────────────────────────

function EmployeeCreateForm({
  branches,
  departments,
  roles,
  onSubmit,
  isLoading,
}: {
  branches: Branch[];
  departments: Department[];
  roles: Role[];
  onSubmit: (values: CreateValues) => void;
  isLoading: boolean;
}) {
  const {
    register,
    handleSubmit,
    setValue,
    formState: { errors },
  } = useForm<CreateValues>({
    resolver: zodResolver(createSchema),
  });

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-1">
          <Label htmlFor="employee_code">Employee Code *</Label>
          <Input id="employee_code" {...register("employee_code")} placeholder="EMP001" />
          {errors.employee_code && (
            <p className="text-xs text-destructive">{errors.employee_code.message}</p>
          )}
        </div>
        <div className="space-y-1">
          <Label htmlFor="date_of_joining">Date of Joining *</Label>
          <Input id="date_of_joining" type="date" {...register("date_of_joining")} />
          {errors.date_of_joining && (
            <p className="text-xs text-destructive">{errors.date_of_joining.message}</p>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-1">
          <Label htmlFor="first_name">First Name *</Label>
          <Input id="first_name" {...register("first_name")} placeholder="John" />
          {errors.first_name && (
            <p className="text-xs text-destructive">{errors.first_name.message}</p>
          )}
        </div>
        <div className="space-y-1">
          <Label htmlFor="last_name">Last Name *</Label>
          <Input id="last_name" {...register("last_name")} placeholder="Doe" />
          {errors.last_name && (
            <p className="text-xs text-destructive">{errors.last_name.message}</p>
          )}
        </div>
      </div>

      <div className="space-y-1">
        <Label htmlFor="email">Email *</Label>
        <Input id="email" type="email" {...register("email")} placeholder="john@company.com" />
        {errors.email && <p className="text-xs text-destructive">{errors.email.message}</p>}
      </div>

      <div className="space-y-1">
        <Label htmlFor="password">Password *</Label>
        <Input id="password" type="password" {...register("password")} placeholder="Min 8 characters" />
        {errors.password && <p className="text-xs text-destructive">{errors.password.message}</p>}
      </div>

      <div className="space-y-1">
        <Label htmlFor="phone">Phone</Label>
        <Input id="phone" {...register("phone")} placeholder="+91 9876543210" />
      </div>

      <div className="space-y-1">
        <Label>Role *</Label>
        <Select onValueChange={(v) => setValue("role_id", v)}>
          <SelectTrigger>
            <SelectValue placeholder="Select role" />
          </SelectTrigger>
          <SelectContent>
            {roles.map((r) => (
              <SelectItem key={r.id} value={r.id}>
                {formatRoleName(r.name)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {errors.role_id && <p className="text-xs text-destructive">{errors.role_id.message}</p>}
      </div>

      <div className="space-y-1">
        <Label>Branch *</Label>
        <Select onValueChange={(v) => setValue("branch_id", v)}>
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
        {errors.branch_id && <p className="text-xs text-destructive">{errors.branch_id.message}</p>}
      </div>

      <div className="space-y-1">
        <Label>Department</Label>
        <Select onValueChange={(v) => setValue("department_id", v === "none" ? "" : v)}>
          <SelectTrigger>
            <SelectValue placeholder="Select department (optional)" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="none">— None —</SelectItem>
            {departments.map((d) => (
              <SelectItem key={d.id} value={d.id}>
                {d.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-1">
        <Label htmlFor="monthly_salary">Monthly Salary (₹)</Label>
        <Input id="monthly_salary" type="number" min="0" step="1" {...register("monthly_salary")} placeholder="e.g. 30000" />
        <p className="text-xs text-muted-foreground">Gross monthly salary. Used for late-arrival deductions.</p>
      </div>

      <SheetFooter className="mt-4">
        <Button type="submit" disabled={isLoading} className="w-full">
          {isLoading ? "Creating…" : "Create Employee"}
        </Button>
      </SheetFooter>
    </form>
  );
}

function EmployeeEditForm({
  employee,
  branches,
  departments,
  roles,
  onSubmit,
  isLoading,
}: {
  employee: Employee;
  branches: Branch[];
  departments: Department[];
  roles: Role[];
  onSubmit: (values: UpdateValues) => void;
  isLoading: boolean;
}) {
  const {
    register,
    handleSubmit,
    setValue,
    formState: { errors },
  } = useForm<UpdateValues>({
    resolver: zodResolver(updateSchema),
    defaultValues: {
      first_name: employee.first_name,
      last_name: employee.last_name,
      phone: employee.phone ?? "",
      role_id: employee.role_id,
      branch_id: employee.branch_id,
      department_id: employee.department_id ?? "",
      monthly_salary: (employee.monthly_salary_paise ?? 0) / 100,
    },
  });

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-1">
          <Label htmlFor="edit_first_name">First Name</Label>
          <Input id="edit_first_name" {...register("first_name")} />
          {errors.first_name && (
            <p className="text-xs text-destructive">{errors.first_name.message}</p>
          )}
        </div>
        <div className="space-y-1">
          <Label htmlFor="edit_last_name">Last Name</Label>
          <Input id="edit_last_name" {...register("last_name")} />
          {errors.last_name && (
            <p className="text-xs text-destructive">{errors.last_name.message}</p>
          )}
        </div>
      </div>

      <div className="space-y-1">
        <Label htmlFor="edit_phone">Phone</Label>
        <Input id="edit_phone" {...register("phone")} />
      </div>

      <div className="space-y-1">
        <Label htmlFor="edit_monthly_salary">Monthly Salary (₹)</Label>
        <Input id="edit_monthly_salary" type="number" min="0" step="1" {...register("monthly_salary")} />
      </div>

      <div className="space-y-1">
        <Label htmlFor="edit_password">Reset Password</Label>
        <Input
          id="edit_password"
          type="password"
          autoComplete="new-password"
          placeholder="Leave blank to keep current password"
          {...register("password")}
        />
        {errors.password && <p className="text-xs text-destructive">{errors.password.message}</p>}
        <p className="text-xs text-muted-foreground">
          Enter a new password (min 8 characters) to reset this employee&apos;s login. Blank = unchanged.
        </p>
      </div>

      <div className="space-y-1">
        <Label>Role</Label>
        <Select
          defaultValue={employee.role_id}
          onValueChange={(v) => setValue("role_id", v)}
        >
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {roles.map((r) => (
              <SelectItem key={r.id} value={r.id}>
                {formatRoleName(r.name)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-1">
        <Label>Branch</Label>
        <Select
          defaultValue={employee.branch_id}
          onValueChange={(v) => setValue("branch_id", v)}
        >
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {branches.map((b) => (
              <SelectItem key={b.id} value={b.id}>
                {b.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-1">
        <Label>Department</Label>
        <Select
          defaultValue={employee.department_id ?? "none"}
          onValueChange={(v) => setValue("department_id", v === "none" ? "" : v)}
        >
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="none">— None —</SelectItem>
            {departments.map((d) => (
              <SelectItem key={d.id} value={d.id}>
                {d.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <SheetFooter className="mt-4">
        <Button type="submit" disabled={isLoading} className="w-full">
          {isLoading ? "Updating…" : "Update Employee"}
        </Button>
      </SheetFooter>
    </form>
  );
}

// ── Component ─────────────────────────────────────────────────────────────────

export function EmployeeManagement({
  navItems,
  portalLabel,
}: {
  navItems: NavEntry[];
  portalLabel: string;
}) {
  const qc = useQueryClient();
  const [sheetOpen, setSheetOpen] = useState(false);
  const [editingEmployee, setEditingEmployee] = useState<Employee | null>(null);
  const [deleteEmployee, setDeleteEmployee] = useState<Employee | null>(null);
  const [deactivateEmployee, setDeactivateEmployee] = useState<Employee | null>(null);
  const [enrollTarget, setEnrollTarget] = useState<Employee | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const [searchText, setSearchText] = useState("");
  const [filterBranch, setFilterBranch] = useState<string>("all");
  const [filterActive, setFilterActive] = useState<string>("all");

  const queryParams: Record<string, string | number> = { per_page: 50 };
  if (searchText) queryParams.search = searchText;
  if (filterBranch !== "all") queryParams.branch_id = filterBranch;
  if (filterActive !== "all") queryParams.is_active = filterActive === "active" ? 1 : 0;

  const { data: empResp, isLoading: empLoading } = useQuery({
    queryKey: ["employees", queryParams],
    queryFn: () => apiGet<Employee[]>("/employees", queryParams),
  });

  const { data: branchesResp } = useQuery({
    queryKey: ["branches"],
    queryFn: () => apiGet<Branch[]>("/branches"),
  });

  const { data: deptResp } = useQuery({
    queryKey: ["departments"],
    queryFn: () => apiGet<Department[]>("/departments"),
  });

  const { data: rolesResp } = useQuery({
    queryKey: ["roles"],
    queryFn: () => apiGet<Role[]>("/roles"),
  });

  // Today's attendance status for every employee (shown live in the table).
  const today = istToday();
  const { data: attResp } = useQuery({
    queryKey: ["employees-today-attendance", today],
    queryFn: () =>
      apiGet<DailyAtt[]>("/attendance/daily", { from_date: today, to_date: today, per_page: 500 }),
  });
  const todayStatus = new Map((attResp?.data ?? []).map((d) => [d.employee_id, d.status]));

  const employees = empResp?.data ?? [];
  const branches = branchesResp?.data ?? [];
  const departments = deptResp?.data ?? [];
  // Hide the internal 'service' role (the face-service machine account) — it must
  // never be assignable to a person.
  const roles = (rolesResp?.data ?? []).filter((r) => r.name.toLowerCase() !== "service");

  const createMutation = useMutation({
    mutationFn: ({ monthly_salary, ...body }: CreateValues) =>
      apiPost<Employee>("/employees", {
        ...body,
        department_id: body.department_id || null,
        monthly_salary_paise: Math.round((monthly_salary || 0) * 100),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["employees"] });
      toast.success("Employee created successfully");
      setSheetOpen(false);
    },
    onError: (err: Error) => toast.error(err.message || "Failed to create employee"),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: string; body: UpdateValues }) => {
      const { monthly_salary, password, ...rest } = body;
      return apiPatch<Employee>(`/employees/${id}`, {
        ...rest,
        department_id: body.department_id || null,
        ...(monthly_salary !== undefined ? { monthly_salary_paise: Math.round(monthly_salary * 100) } : {}),
        // Only send a password when the admin actually typed one (blank = unchanged).
        ...(password ? { password } : {}),
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["employees"] });
      toast.success("Employee updated");
      setSheetOpen(false);
      setEditingEmployee(null);
    },
    onError: (err: Error) => toast.error(err.message || "Failed to update employee"),
  });

  const deactivateMutation = useMutation({
    mutationFn: ({ id, active }: { id: string; active: boolean }) =>
      apiPatch(`/employees/${id}`, { is_active: active }),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ["employees"] });
      toast.success(vars.active ? "Employee activated" : "Employee deactivated");
      setDeactivateEmployee(null);
    },
    onError: (err: Error) => toast.error(err.message || "Failed to update employee"),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiDelete(`/employees/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["employees"] });
      toast.success("Employee deleted");
      setDeleteEmployee(null);
    },
    onError: (err: Error) => toast.error(err.message || "Failed to delete employee"),
  });

  const enrollMutation = useMutation({
    // Upload photos one at a time so each gets its own embedding. Enrolling
    // 2–3 varied photos per person materially improves recognition accuracy.
    mutationFn: async ({ id, files }: { id: string; files: File[] }) => {
      const { api } = await import("@/lib/api");
      let ok = 0;
      const failures: string[] = [];
      for (const file of files) {
        try {
          const fd = new FormData();
          fd.append("file", file);
          await api.post(`/face/employees/${id}/enroll`, fd, {
            headers: { "Content-Type": "multipart/form-data" },
          });
          ok += 1;
        } catch (err) {
          const msg = err instanceof Error ? err.message : "failed";
          failures.push(`${file.name}: ${msg}`);
        }
      }
      return { ok, failures };
    },
    onSuccess: ({ ok, failures }) => {
      if (ok > 0)
        toast.success(
          `Enrolled ${ok} photo${ok === 1 ? "" : "s"}${failures.length ? ` (${failures.length} skipped)` : ""}`,
        );
      if (failures.length) toast.error(failures[0]);
      setEnrollTarget(null);
    },
    onError: (err: Error) => toast.error(err.message || "Enrollment failed"),
  });

  const columns: ColumnDef<Employee>[] = [
    {
      accessorKey: "employee_code",
      header: "Code",
      cell: ({ row }) => (
        <span className="font-mono text-sm">{row.original.employee_code}</span>
      ),
    },
    {
      id: "full_name",
      header: "Name",
      cell: ({ row }) => (
        <span className="font-medium">
          {row.original.first_name} {row.original.last_name}
        </span>
      ),
    },
    { accessorKey: "email", header: "Email" },
    {
      accessorKey: "role_name",
      header: "Role",
      cell: ({ row }) => (
        <span className="inline-flex items-center rounded-full bg-blue-100 px-2.5 py-0.5 text-xs font-medium text-blue-800 dark:bg-blue-900/30 dark:text-blue-400">
          {formatRoleName(row.original.role_name)}
        </span>
      ),
    },
    { accessorKey: "branch_name", header: "Branch" },
    {
      accessorKey: "department_name",
      header: "Department",
      cell: ({ row }) =>
        row.original.department_name ?? <span className="text-muted-foreground">—</span>,
    },
    {
      id: "today_status",
      header: "Today",
      // Only rank-and-file employees have a daily attendance status. Admin, HR and
      // manager accounts are staff/oversight roles that aren't tracked by the
      // attendance engine, so their Today cell stays blank.
      cell: ({ row }) =>
        row.original.role_name?.toLowerCase() === "employee" ? (
          <StatusBadge status={todayStatus.get(row.original.id) ?? "ABSENT"} className="text-xs" />
        ) : (
          <span className="text-xs text-muted-foreground">—</span>
        ),
    },
    {
      accessorKey: "date_of_joining",
      header: "Joined",
      cell: ({ row }) => (
        <span className="text-sm text-muted-foreground">{row.original.date_of_joining}</span>
      ),
    },
    {
      id: "actions",
      header: "Actions",
      cell: ({ row }) => {
        // In the HR portal, the system-admin account can't be deactivated or deleted.
        const canManage =
          portalLabel === "Admin" || row.original.role_name?.toLowerCase() !== "admin";
        return (
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => {
              setEditingEmployee(row.original);
              setSheetOpen(true);
            }}
          >
            <Pencil className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            title="Enroll face photos (select one or more)"
            onClick={() => {
              setEnrollTarget(row.original);
              fileRef.current?.click();
            }}
          >
            <Camera className="h-4 w-4" />
          </Button>
          {canManage && (
            <Button
              variant="ghost"
              size="icon"
              title={row.original.is_active ? "Deactivate" : "Activate"}
              className={
                row.original.is_active
                  ? "text-yellow-600 hover:text-yellow-600"
                  : "text-green-600 hover:text-green-600"
              }
              onClick={() => setDeactivateEmployee(row.original)}
            >
              {row.original.is_active ? <UserX className="h-4 w-4" /> : <UserCheck className="h-4 w-4" />}
            </Button>
          )}
          {canManage && (
            <Button
              variant="ghost"
              size="icon"
              className="text-destructive hover:text-destructive"
              onClick={() => setDeleteEmployee(row.original)}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          )}
        </div>
        );
      },
    },
  ];

  const isMutating = createMutation.isPending || updateMutation.isPending;

  return (
    <PortalLayout navItems={navItems} portalLabel={portalLabel} pageTitle="Employees">
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-bold">Employees</h2>
            <p className="text-muted-foreground">Manage all employees in the system</p>
          </div>
          <Button
            onClick={() => {
              setEditingEmployee(null);
              setSheetOpen(true);
            }}
          >
            <Plus className="mr-2 h-4 w-4" />
            Add Employee
          </Button>
        </div>

        {/* Filters */}
        <div className="flex flex-wrap gap-3">
          <Input
            placeholder="Search by name, email or code…"
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            className="max-w-xs"
          />
          <Select value={filterBranch} onValueChange={setFilterBranch}>
            <SelectTrigger className="w-48">
              <SelectValue placeholder="All branches" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Branches</SelectItem>
              {branches.map((b) => (
                <SelectItem key={b.id} value={b.id}>
                  {b.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={filterActive} onValueChange={setFilterActive}>
            <SelectTrigger className="w-36">
              <SelectValue placeholder="All status" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Status</SelectItem>
              <SelectItem value="active">Active</SelectItem>
              <SelectItem value="inactive">Inactive</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {empLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        ) : employees.length === 0 ? (
          <div className="flex h-48 items-center justify-center text-muted-foreground">
            No employees found.
          </div>
        ) : (
          <DataTable columns={columns} data={employees} pageSize={20} />
        )}
      </div>

      {/* Hidden file input for face enrollment — accepts multiple photos at once */}
      <input
        ref={fileRef}
        type="file"
        accept="image/jpeg,image/png,image/webp"
        multiple
        className="hidden"
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          if (files.length && enrollTarget) {
            toast.info(`Enrolling ${files.length} photo${files.length === 1 ? "" : "s"}…`);
            enrollMutation.mutate({ id: enrollTarget.id, files });
          }
          e.target.value = "";
        }}
      />

      {/* Create/Edit Sheet */}
      <Sheet
        open={sheetOpen}
        onOpenChange={(open) => {
          setSheetOpen(open);
          if (!open) setEditingEmployee(null);
        }}
      >
        <SheetContent className="overflow-y-auto sm:max-w-lg">
          <SheetHeader className="mb-4">
            <SheetTitle>{editingEmployee ? "Edit Employee" : "Add Employee"}</SheetTitle>
            <SheetDescription>
              {editingEmployee
                ? "Update employee details."
                : "Create a new employee account."}
            </SheetDescription>
          </SheetHeader>
          {editingEmployee ? (
            <EmployeeEditForm
              employee={editingEmployee}
              branches={branches}
              departments={departments}
              roles={roles}
              onSubmit={(values) =>
                updateMutation.mutate({ id: editingEmployee.id, body: values })
              }
              isLoading={isMutating}
            />
          ) : (
            <EmployeeCreateForm
              branches={branches}
              departments={departments}
              roles={roles}
              onSubmit={(values) => createMutation.mutate(values)}
              isLoading={isMutating}
            />
          )}
        </SheetContent>
      </Sheet>

      {/* Activate / Deactivate Confirm */}
      <ConfirmDialog
        open={!!deactivateEmployee}
        onOpenChange={(open) => !open && setDeactivateEmployee(null)}
        title={deactivateEmployee?.is_active ? "Deactivate Employee" : "Activate Employee"}
        description={
          deactivateEmployee?.is_active
            ? `Deactivate ${deactivateEmployee?.first_name} ${deactivateEmployee?.last_name}? They will no longer be able to log in.`
            : `Activate ${deactivateEmployee?.first_name} ${deactivateEmployee?.last_name}? They will regain access to the system.`
        }
        confirmLabel={deactivateEmployee?.is_active ? "Deactivate" : "Activate"}
        destructive={deactivateEmployee?.is_active}
        onConfirm={() =>
          deactivateEmployee &&
          deactivateMutation.mutate({ id: deactivateEmployee.id, active: !deactivateEmployee.is_active })
        }
        isLoading={deactivateMutation.isPending}
      />

      {/* Delete Confirm */}
      <ConfirmDialog
        open={!!deleteEmployee}
        onOpenChange={(open) => !open && setDeleteEmployee(null)}
        title="Delete Employee"
        description={`Permanently delete ${deleteEmployee?.first_name} ${deleteEmployee?.last_name}? This cannot be undone.`}
        confirmLabel="Delete"
        destructive
        onConfirm={() => deleteEmployee && deleteMutation.mutate(deleteEmployee.id)}
        isLoading={deleteMutation.isPending}
      />
    </PortalLayout>
  );
}
