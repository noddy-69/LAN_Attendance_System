"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm, Controller } from "react-hook-form";
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
import { Switch } from "@/components/ui/switch";
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

interface Permission {
  id: string;
  name: string;
  description: string | null;
}

interface Role {
  id: string;
  name: string;
  description: string | null;
  permissions: Permission[];
  employee_count?: number;
}

// ── Schema ────────────────────────────────────────────────────────────────────

const schema = z.object({
  name: z.string().min(1, "Name is required").max(100),
  description: z.string().optional(),
  permission_ids: z.array(z.string().uuid()),
});

type FormValues = z.infer<typeof schema>;

// ── Permission Matrix ─────────────────────────────────────────────────────────

type PermissionGroups = Record<string, Record<string, Permission>>;

function buildGroups(permissions: Permission[]): PermissionGroups {
  return permissions.reduce((acc, p) => {
    const parts = p.name.split(":");
    const resource = parts[0];
    const action = parts[1] ?? "other";
    if (!acc[resource]) acc[resource] = {};
    acc[resource][action] = p;
    return acc;
  }, {} as PermissionGroups);
}

function PermissionMatrix({
  allPermissions,
  selectedIds,
  onChange,
}: {
  allPermissions: Permission[];
  selectedIds: string[];
  onChange: (ids: string[]) => void;
}) {
  const groups = buildGroups(allPermissions);

  const toggle = (permId: string, checked: boolean) => {
    if (checked) {
      onChange([...selectedIds, permId]);
    } else {
      onChange(selectedIds.filter((id) => id !== permId));
    }
  };

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-3 gap-2 text-xs font-semibold text-muted-foreground px-1">
        <span>Resource</span>
        <span className="text-center">Read</span>
        <span className="text-center">Write</span>
      </div>
      {Object.entries(groups).map(([resource, actions]) => (
        <div
          key={resource}
          className="grid grid-cols-3 items-center gap-2 rounded-md border px-3 py-2"
        >
          <span className="text-sm font-medium capitalize">{resource}</span>
          <div className="flex justify-center">
            {actions["read"] ? (
              <Switch
                checked={selectedIds.includes(actions["read"].id)}
                onCheckedChange={(checked) => toggle(actions["read"].id, checked)}
              />
            ) : (
              <span className="text-xs text-muted-foreground">—</span>
            )}
          </div>
          <div className="flex justify-center">
            {actions["write"] ? (
              <Switch
                checked={selectedIds.includes(actions["write"].id)}
                onCheckedChange={(checked) => toggle(actions["write"].id, checked)}
              />
            ) : (
              <span className="text-xs text-muted-foreground">—</span>
            )}
          </div>
        </div>
      ))}
      {/* Show any non-read/write permissions */}
      {Object.entries(groups).map(([resource, actions]) =>
        Object.entries(actions)
          .filter(([action]) => action !== "read" && action !== "write")
          .map(([action, perm]) => (
            <div
              key={perm.id}
              className="flex items-center justify-between rounded-md border px-3 py-2"
            >
              <span className="text-sm font-medium capitalize">
                {resource}:{action}
              </span>
              <Switch
                checked={selectedIds.includes(perm.id)}
                onCheckedChange={(checked) => toggle(perm.id, checked)}
              />
            </div>
          ))
      )}
    </div>
  );
}

// ── RoleForm ──────────────────────────────────────────────────────────────────

function RoleForm({
  allPermissions,
  defaultValues,
  onSubmit,
  isLoading,
}: {
  allPermissions: Permission[];
  defaultValues: Partial<FormValues>;
  onSubmit: (values: FormValues) => void;
  isLoading: boolean;
}) {
  const {
    register,
    handleSubmit,
    control,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: "",
      description: "",
      permission_ids: [],
      ...defaultValues,
    },
  });

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4">
      <div className="space-y-1">
        <Label htmlFor="name">Role Name *</Label>
        <Input id="name" {...register("name")} placeholder="Manager" />
        {errors.name && <p className="text-xs text-destructive">{errors.name.message}</p>}
      </div>

      <div className="space-y-1">
        <Label htmlFor="description">Description</Label>
        <Textarea id="description" {...register("description")} placeholder="Role description…" />
      </div>

      <div className="space-y-2">
        <Label>Permissions</Label>
        <Controller
          control={control}
          name="permission_ids"
          render={({ field }) => (
            <PermissionMatrix
              allPermissions={allPermissions}
              selectedIds={field.value}
              onChange={field.onChange}
            />
          )}
        />
      </div>

      <SheetFooter className="mt-4">
        <Button type="submit" disabled={isLoading} className="w-full">
          {isLoading ? "Saving…" : "Save Role"}
        </Button>
      </SheetFooter>
    </form>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function RolesPage() {
  const qc = useQueryClient();
  const [sheetOpen, setSheetOpen] = useState(false);
  const [editingRole, setEditingRole] = useState<Role | null>(null);
  const [deleteRole, setDeleteRole] = useState<Role | null>(null);

  const { data: rolesResp, isLoading: rolesLoading } = useQuery({
    queryKey: ["roles"],
    queryFn: () => apiGet<Role[]>("/roles"),
  });

  const { data: permsResp } = useQuery({
    queryKey: ["permissions"],
    queryFn: () => apiGet<Permission[]>("/roles/permissions"),
  });

  const roles = rolesResp?.data ?? [];
  const allPermissions = permsResp?.data ?? [];

  const createMutation = useMutation({
    mutationFn: (body: FormValues) => apiPost<Role>("/roles", body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["roles"] });
      toast.success("Role created");
      setSheetOpen(false);
    },
    onError: (err: Error) => toast.error(err.message || "Failed to create role"),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<FormValues> }) =>
      apiPatch<Role>(`/roles/${id}`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["roles"] });
      toast.success("Role updated");
      setSheetOpen(false);
      setEditingRole(null);
    },
    onError: (err: Error) => toast.error(err.message || "Failed to update role"),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiDelete(`/roles/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["roles"] });
      toast.success("Role deleted");
      setDeleteRole(null);
    },
    onError: (err: Error) => toast.error(err.message || "Failed to delete role"),
  });

  const columns: ColumnDef<Role>[] = [
    {
      accessorKey: "name",
      header: "Name",
      cell: ({ row }) => <span className="font-medium">{row.original.name}</span>,
    },
    {
      accessorKey: "description",
      header: "Description",
      cell: ({ row }) =>
        row.original.description ?? <span className="text-muted-foreground">—</span>,
    },
    {
      id: "permission_count",
      header: "Permissions",
      cell: ({ row }) => (
        <span className="inline-flex items-center rounded-full bg-blue-100 px-2.5 py-0.5 text-xs font-medium text-blue-800 dark:bg-blue-900/30 dark:text-blue-400">
          {row.original.permissions?.length ?? 0}
        </span>
      ),
    },
    {
      id: "employee_count",
      header: "Employees",
      cell: ({ row }) => row.original.employee_count ?? "—",
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
              setEditingRole(row.original);
              setSheetOpen(true);
            }}
          >
            <Pencil className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="text-destructive hover:text-destructive"
            onClick={() => setDeleteRole(row.original)}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      ),
    },
  ];

  const handleSubmit = (values: FormValues) => {
    if (editingRole) {
      updateMutation.mutate({ id: editingRole.id, body: values });
    } else {
      createMutation.mutate(values);
    }
  };

  const isMutating = createMutation.isPending || updateMutation.isPending;

  return (
    <PortalLayout navItems={ADMIN_NAV} portalLabel="Admin" pageTitle="Roles">
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-bold">Roles</h2>
            <p className="text-muted-foreground">Manage roles and their permissions</p>
          </div>
          <Button
            onClick={() => {
              setEditingRole(null);
              setSheetOpen(true);
            }}
          >
            <Plus className="mr-2 h-4 w-4" />
            Add Role
          </Button>
        </div>

        {rolesLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        ) : (
          <DataTable
            columns={columns}
            data={roles}
            filterColumn="name"
            filterPlaceholder="Search roles…"
          />
        )}
      </div>

      <Sheet
        open={sheetOpen}
        onOpenChange={(open) => {
          setSheetOpen(open);
          if (!open) setEditingRole(null);
        }}
      >
        <SheetContent className="overflow-y-auto">
          <SheetHeader className="mb-4">
            <SheetTitle>{editingRole ? "Edit Role" : "Add Role"}</SheetTitle>
            <SheetDescription>
              {editingRole
                ? "Update role name, description and permissions."
                : "Create a new role and assign permissions."}
            </SheetDescription>
          </SheetHeader>
          <RoleForm
            allPermissions={allPermissions}
            defaultValues={
              editingRole
                ? {
                    name: editingRole.name,
                    description: editingRole.description ?? "",
                    permission_ids: editingRole.permissions?.map((p) => p.id) ?? [],
                  }
                : {}
            }
            onSubmit={handleSubmit}
            isLoading={isMutating}
          />
        </SheetContent>
      </Sheet>

      <ConfirmDialog
        open={!!deleteRole}
        onOpenChange={(open) => !open && setDeleteRole(null)}
        title="Delete Role"
        description={
          deleteRole
            ? `Delete role "${deleteRole.name}"?${
                (deleteRole.employee_count ?? 0) > 0
                  ? ` Warning: ${deleteRole.employee_count} employee(s) currently have this role.`
                  : ""
              } This cannot be undone.`
            : ""
        }
        confirmLabel="Delete"
        destructive
        onConfirm={() => deleteRole && deleteMutation.mutate(deleteRole.id)}
        isLoading={deleteMutation.isPending}
      />
    </PortalLayout>
  );
}
