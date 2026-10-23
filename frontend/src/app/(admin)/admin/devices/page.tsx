"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { ColumnDef } from "@tanstack/react-table";
import { Plus, Pencil, Trash2, Wifi } from "lucide-react";

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

interface Device {
  id: string;
  name: string;
  device_type: "camera" | "biometric";
  branch_id: string;
  branch_name: string;
  is_entry_camera: boolean;
  rtsp_url_masked: string | null;
  ip_address: string | null;
  port: number | null;
  serial_number: string | null;
  device_uid: string | null;
  is_active: boolean;
  last_heartbeat: string | null;
}

interface TestConnectionResult {
  reachable: boolean;
  message: string;
  latency_ms: number | null;
}

// ── Zod Schema ────────────────────────────────────────────────────────────────

const schema = z
  .object({
    name: z.string().min(1, "Name is required").max(150),
    device_type: z.enum(["camera", "biometric"]),
    branch_id: z.string().uuid("Branch is required"),
    is_entry_camera: z.boolean().default(true),
    rtsp_url: z.string().optional(),
    ip_address: z.string().optional(),
    port: z.coerce.number().int().min(1).max(65535).optional(),
    serial_number: z.string().optional(),
    device_uid: z.string().optional(),
  })
  .refine((d) => d.device_type !== "camera" || !!d.rtsp_url, {
    message: "RTSP URL is required for camera",
    path: ["rtsp_url"],
  })
  .refine((d) => d.device_type !== "biometric" || !!d.ip_address, {
    message: "IP address is required for biometric",
    path: ["ip_address"],
  });

type FormValues = z.infer<typeof schema>;

// ── Helpers ───────────────────────────────────────────────────────────────────

function toIST(utcString: string | null): string {
  if (!utcString) return "Never";
  const d = new Date(utcString);
  const ist = new Date(d.getTime() + 5.5 * 60 * 60 * 1000);
  return ist.toLocaleString("en-IN", { timeZone: "UTC" });
}

// ── DeviceForm ────────────────────────────────────────────────────────────────

function DeviceForm({
  branches,
  defaultValues,
  onSubmit,
  isLoading,
}: {
  branches: Branch[];
  defaultValues: Partial<FormValues>;
  onSubmit: (values: FormValues) => void;
  isLoading: boolean;
}) {
  const {
    register,
    handleSubmit,
    watch,
    setValue,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      is_entry_camera: true,
      device_type: "camera",
      ...defaultValues,
    },
  });

  const deviceType = watch("device_type");

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4 overflow-y-auto">
      {/* Name */}
      <div className="space-y-1">
        <Label htmlFor="name">Device Name *</Label>
        <Input id="name" {...register("name")} placeholder="Entry Camera 1" />
        {errors.name && <p className="text-xs text-destructive">{errors.name.message}</p>}
      </div>

      {/* Type */}
      <div className="space-y-1">
        <Label>Device Type *</Label>
        <Select
          defaultValue={defaultValues.device_type ?? "camera"}
          onValueChange={(v) => setValue("device_type", v as "camera" | "biometric")}
        >
          <SelectTrigger>
            <SelectValue placeholder="Select type" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="camera">Camera</SelectItem>
            <SelectItem value="biometric">Biometric</SelectItem>
          </SelectContent>
        </Select>
        {errors.device_type && (
          <p className="text-xs text-destructive">{errors.device_type.message}</p>
        )}
      </div>

      {/* Branch */}
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

      {/* Entry/Exit (camera only) */}
      {deviceType === "camera" && (
        <div className="space-y-1">
          <Label>Camera Role</Label>
          <Select
            defaultValue={defaultValues.is_entry_camera === false ? "exit" : "entry"}
            onValueChange={(v) => setValue("is_entry_camera", v === "entry")}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="entry">Entry Camera</SelectItem>
              <SelectItem value="exit">Exit Camera</SelectItem>
            </SelectContent>
          </Select>
        </div>
      )}

      {/* Camera-specific fields */}
      {deviceType === "camera" && (
        <div className="space-y-1">
          <Label htmlFor="rtsp_url">RTSP URL *</Label>
          <Input
            id="rtsp_url"
            {...register("rtsp_url")}
            placeholder="rtsp://admin:pass@192.168.1.100:554/cam/realmonitor?channel=1&subtype=0"
          />
          {errors.rtsp_url && (
            <p className="text-xs text-destructive">{errors.rtsp_url.message}</p>
          )}
        </div>
      )}

      {/* Biometric-specific fields */}
      {deviceType === "biometric" && (
        <>
          <div className="space-y-1">
            <Label htmlFor="ip_address">IP Address *</Label>
            <Input id="ip_address" {...register("ip_address")} placeholder="192.168.1.50" />
            {errors.ip_address && (
              <p className="text-xs text-destructive">{errors.ip_address.message}</p>
            )}
          </div>
          <div className="space-y-1">
            <Label htmlFor="port">Port</Label>
            <Input
              id="port"
              type="number"
              {...register("port")}
              placeholder="4370"
            />
            {errors.port && <p className="text-xs text-destructive">{errors.port.message}</p>}
          </div>
          <div className="space-y-1">
            <Label htmlFor="serial_number">Serial Number</Label>
            <Input id="serial_number" {...register("serial_number")} placeholder="ABC123456" />
          </div>
          <div className="space-y-1">
            <Label htmlFor="device_uid">Device UID</Label>
            <Input id="device_uid" {...register("device_uid")} placeholder="ZKID001" />
          </div>
        </>
      )}

      <SheetFooter className="mt-4">
        <Button type="submit" disabled={isLoading} className="w-full">
          {isLoading ? "Saving…" : "Save Device"}
        </Button>
      </SheetFooter>
    </form>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function DevicesPage() {
  const qc = useQueryClient();
  const [sheetOpen, setSheetOpen] = useState(false);
  const [editingDevice, setEditingDevice] = useState<Device | null>(null);
  const [deleteDevice, setDeleteDevice] = useState<Device | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);

  const { data: devicesResp, isLoading: devicesLoading } = useQuery({
    queryKey: ["devices"],
    queryFn: () => apiGet<Device[]>("/devices"),
  });

  const { data: branchesResp } = useQuery({
    queryKey: ["branches"],
    queryFn: () => apiGet<Branch[]>("/branches"),
  });

  const devices = devicesResp?.data ?? [];
  const branches = branchesResp?.data ?? [];

  const createMutation = useMutation({
    mutationFn: (body: FormValues) => apiPost<Device>("/devices", body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["devices"] });
      toast.success("Device created successfully");
      setSheetOpen(false);
    },
    onError: (err: Error) => toast.error(err.message || "Failed to create device"),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<FormValues> }) =>
      apiPatch<Device>(`/devices/${id}`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["devices"] });
      toast.success("Device updated successfully");
      setSheetOpen(false);
      setEditingDevice(null);
    },
    onError: (err: Error) => toast.error(err.message || "Failed to update device"),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiDelete(`/devices/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["devices"] });
      toast.success("Device deleted");
      setDeleteDevice(null);
    },
    onError: (err: Error) => toast.error(err.message || "Failed to delete device"),
  });

  const testConnection = async (device: Device) => {
    setTestingId(device.id);
    try {
      const res = await apiPost<TestConnectionResult>(`/devices/${device.id}/test-connection`);
      const result = res.data;
      if (result?.reachable) {
        toast.success(`Reachable — ${result.message}${result.latency_ms != null ? ` (${result.latency_ms}ms)` : ""}`);
      } else {
        toast.error(`Not reachable — ${result?.message ?? "Unknown error"}`);
      }
    } catch {
      toast.error("Connection test failed");
    } finally {
      setTestingId(null);
    }
  };

  const columns: ColumnDef<Device>[] = [
    {
      accessorKey: "name",
      header: "Name",
      cell: ({ row }) => <span className="font-medium">{row.original.name}</span>,
    },
    {
      accessorKey: "device_type",
      header: "Type",
      cell: ({ row }) => (
        <span
          className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${
            row.original.device_type === "camera"
              ? "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400"
              : "bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-400"
          }`}
        >
          {row.original.device_type}
        </span>
      ),
    },
    {
      accessorKey: "branch_name",
      header: "Branch",
    },
    {
      id: "camera_role",
      header: "Role",
      cell: ({ row }) => {
        if (row.original.device_type !== "camera") return <span className="text-muted-foreground">—</span>;
        return (
          <span
            className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${
              row.original.is_entry_camera
                ? "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400"
                : "bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-400"
            }`}
          >
            {row.original.is_entry_camera ? "Entry" : "Exit"}
          </span>
        );
      },
    },
    {
      id: "status",
      header: "Status",
      cell: ({ row }) => (
        <span
          className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${
            row.original.is_active
              ? "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400"
              : "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400"
          }`}
        >
          {row.original.is_active ? "Active" : "Inactive"}
        </span>
      ),
    },
    {
      id: "last_heartbeat",
      header: "Last Heartbeat",
      cell: ({ row }) => (
        <span className="text-sm text-muted-foreground">{toIST(row.original.last_heartbeat)}</span>
      ),
    },
    {
      id: "actions",
      header: "Actions",
      cell: ({ row }) => (
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => testConnection(row.original)}
            disabled={testingId === row.original.id}
          >
            <Wifi className="h-3 w-3" />
            {testingId === row.original.id ? "Testing…" : "Test"}
          </Button>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => {
              setEditingDevice(row.original);
              setSheetOpen(true);
            }}
          >
            <Pencil className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="text-destructive hover:text-destructive"
            onClick={() => setDeleteDevice(row.original)}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      ),
    },
  ];

  const handleSubmit = (values: FormValues) => {
    if (editingDevice) {
      updateMutation.mutate({ id: editingDevice.id, body: values });
    } else {
      createMutation.mutate(values);
    }
  };

  const isMutating = createMutation.isPending || updateMutation.isPending;

  return (
    <PortalLayout navItems={ADMIN_NAV} portalLabel="Admin" pageTitle="Devices">
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-bold">Devices</h2>
            <p className="text-muted-foreground">Manage cameras and biometric devices</p>
          </div>
          <Button
            onClick={() => {
              setEditingDevice(null);
              setSheetOpen(true);
            }}
          >
            <Plus className="mr-2 h-4 w-4" />
            Add Device
          </Button>
        </div>

        {devicesLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        ) : (
          <DataTable columns={columns} data={devices} filterColumn="name" filterPlaceholder="Search devices…" />
        )}
      </div>

      {/* Add/Edit Sheet */}
      <Sheet
        open={sheetOpen}
        onOpenChange={(open) => {
          setSheetOpen(open);
          if (!open) setEditingDevice(null);
        }}
      >
        <SheetContent className="overflow-y-auto">
          <SheetHeader className="mb-4">
            <SheetTitle>{editingDevice ? "Edit Device" : "Add Device"}</SheetTitle>
            <SheetDescription>
              {editingDevice ? "Update device configuration." : "Configure a new camera or biometric device."}
            </SheetDescription>
          </SheetHeader>
          <DeviceForm
            branches={branches}
            defaultValues={
              editingDevice
                ? {
                    name: editingDevice.name,
                    device_type: editingDevice.device_type,
                    branch_id: editingDevice.branch_id,
                    is_entry_camera: editingDevice.is_entry_camera,
                    ip_address: editingDevice.ip_address ?? undefined,
                    port: editingDevice.port ?? undefined,
                    serial_number: editingDevice.serial_number ?? undefined,
                    device_uid: editingDevice.device_uid ?? undefined,
                  }
                : {}
            }
            onSubmit={handleSubmit}
            isLoading={isMutating}
          />
        </SheetContent>
      </Sheet>

      {/* Delete Confirm */}
      <ConfirmDialog
        open={!!deleteDevice}
        onOpenChange={(open) => !open && setDeleteDevice(null)}
        title="Delete Device"
        description={`Are you sure you want to delete "${deleteDevice?.name}"? This cannot be undone.`}
        confirmLabel="Delete"
        destructive
        onConfirm={() => deleteDevice && deleteMutation.mutate(deleteDevice.id)}
        isLoading={deleteMutation.isPending}
      />
    </PortalLayout>
  );
}
