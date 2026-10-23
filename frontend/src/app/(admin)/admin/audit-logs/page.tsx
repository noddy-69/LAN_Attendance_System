"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ColumnDef } from "@tanstack/react-table";
import { Search } from "lucide-react";

import { PortalLayout } from "@/components/shared/Layout";
import { ADMIN_NAV } from "@/components/admin/nav";
import { DataTable } from "@/components/shared/DataTable";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { apiGet } from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────────────────────

interface AuditLog {
  id: string;
  table_name: string;
  record_id: string;
  action: "create" | "update" | "delete" | "restore";
  before_value: Record<string, unknown> | null;
  after_value: Record<string, unknown> | null;
  performed_by_id: string | null;
  performed_by_name: string | null;
  ip_address: string | null;
  user_agent: string | null;
  created_at: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function toIST(utc: string): string {
  const d = new Date(new Date(utc).getTime() + 5.5 * 60 * 60 * 1000);
  return d.toLocaleString("en-IN", { timeZone: "UTC" });
}

const ACTION_STYLES: Record<string, string> = {
  create:  "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400",
  update:  "bg-blue-100  text-blue-800  dark:bg-blue-900/30  dark:text-blue-400",
  delete:  "bg-red-100   text-red-800   dark:bg-red-900/30   dark:text-red-400",
  restore: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400",
};

function ActionBadge({ action }: { action: string }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${ACTION_STYLES[action] ?? "bg-gray-100 text-gray-800"}`}>
      {action}
    </span>
  );
}

function JsonBlock({ label, value }: { label: string; value: Record<string, unknown> | null }) {
  if (!value) return (
    <div>
      <p className="mb-1 text-xs font-semibold text-muted-foreground uppercase tracking-wide">{label}</p>
      <p className="text-sm text-muted-foreground italic">— none —</p>
    </div>
  );
  return (
    <div>
      <p className="mb-1 text-xs font-semibold text-muted-foreground uppercase tracking-wide">{label}</p>
      <pre className="overflow-auto rounded-md bg-muted p-3 text-xs leading-relaxed max-h-64">
        {JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function AuditLogsPage() {
  const [tableFilter, setTableFilter] = useState("");
  const [actionFilter, setActionFilter] = useState<string>("all");
  const [cursor, setCursor] = useState<string | undefined>(undefined);
  const [allLogs, setAllLogs] = useState<AuditLog[]>([]);
  const [selectedLog, setSelectedLog] = useState<AuditLog | null>(null);
  const [diffOpen, setDiffOpen] = useState(false);

  const params: Record<string, unknown> = { per_page: 50 };
  if (tableFilter) params.table_name = tableFilter;
  if (actionFilter !== "all") params.action = actionFilter;
  if (cursor) params.cursor = cursor;

  const { data, isLoading, isFetching } = useQuery({
    queryKey: ["audit-logs", tableFilter, actionFilter],
    queryFn: async () => {
      // Reset pagination when filters change
      setCursor(undefined);
      setAllLogs([]);
      const res = await apiGet<AuditLog[]>("/system/audit-logs", { ...params, cursor: undefined });
      const logs = res.data ?? [];
      setAllLogs(logs);
      return { logs, pagination: res.pagination };
    },
  });

  const loadMore = async () => {
    if (!data?.pagination?.next_cursor) return;
    const res = await apiGet<AuditLog[]>("/system/audit-logs", {
      ...params,
      cursor: data.pagination.next_cursor,
    });
    setAllLogs((prev) => [...prev, ...(res.data ?? [])]);
  };

  const openDiff = (log: AuditLog) => {
    setSelectedLog(log);
    setDiffOpen(true);
  };

  const columns: ColumnDef<AuditLog>[] = [
    {
      accessorKey: "created_at",
      header: "Timestamp (IST)",
      cell: ({ row }) => (
        <span className="whitespace-nowrap text-xs text-muted-foreground">
          {toIST(row.original.created_at)}
        </span>
      ),
    },
    {
      accessorKey: "performed_by_name",
      header: "Actor",
      cell: ({ row }) => (
        <span className="text-sm">{row.original.performed_by_name ?? "System"}</span>
      ),
    },
    {
      accessorKey: "action",
      header: "Action",
      cell: ({ row }) => <ActionBadge action={row.original.action} />,
    },
    {
      accessorKey: "table_name",
      header: "Table",
      cell: ({ row }) => (
        <code className="rounded bg-muted px-1.5 py-0.5 text-xs">
          {row.original.table_name}
        </code>
      ),
    },
    {
      accessorKey: "record_id",
      header: "Record ID",
      cell: ({ row }) => (
        <span className="font-mono text-xs text-muted-foreground">
          {row.original.record_id.slice(0, 8)}…
        </span>
      ),
    },
    {
      accessorKey: "ip_address",
      header: "IP",
      cell: ({ row }) => (
        <span className="text-xs text-muted-foreground">
          {row.original.ip_address ?? "—"}
        </span>
      ),
    },
    {
      id: "actions",
      header: "",
      cell: ({ row }) => (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => openDiff(row.original)}
          className="text-xs"
        >
          View Diff
        </Button>
      ),
    },
  ];

  const displayLogs = allLogs.length > 0 ? allLogs : (data?.logs ?? []);

  return (
    <PortalLayout navItems={ADMIN_NAV} portalLabel="Admin" pageTitle="Audit Logs">
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-bold">Audit Logs</h2>
            <p className="text-sm text-muted-foreground">
              Immutable record of every system mutation
            </p>
          </div>
        </div>

        {/* Filters */}
        <div className="flex flex-wrap gap-3">
          <div className="flex items-center gap-2">
            <Search className="h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Filter by table name…"
              value={tableFilter}
              onChange={(e) => setTableFilter(e.target.value)}
              className="w-48"
            />
          </div>

          <div className="w-40">
            <Select value={actionFilter} onValueChange={setActionFilter}>
              <SelectTrigger>
                <SelectValue placeholder="All actions" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All actions</SelectItem>
                <SelectItem value="create">Create</SelectItem>
                <SelectItem value="update">Update</SelectItem>
                <SelectItem value="delete">Delete</SelectItem>
                <SelectItem value="restore">Restore</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>

        {/* Table */}
        {isLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : (
          <>
            <DataTable
              columns={columns}
              data={displayLogs}
              pageSize={25}
            />

            {data?.pagination?.has_next && (
              <div className="flex justify-center pt-2">
                <Button
                  variant="outline"
                  onClick={loadMore}
                  disabled={isFetching}
                >
                  {isFetching ? "Loading…" : "Load more"}
                </Button>
              </div>
            )}

            {displayLogs.length === 0 && (
              <div className="flex h-40 items-center justify-center text-muted-foreground">
                No audit logs found.
              </div>
            )}
          </>
        )}
      </div>

      {/* Diff Dialog */}
      <Dialog open={diffOpen} onOpenChange={setDiffOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <ActionBadge action={selectedLog?.action ?? ""} />
              <span>{selectedLog?.table_name}</span>
            </DialogTitle>
            <DialogDescription className="font-mono text-xs">
              Record: {selectedLog?.record_id}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 overflow-auto">
            <div className="grid grid-cols-2 gap-3 text-sm text-muted-foreground">
              <div>
                <span className="font-medium text-foreground">Actor:</span>{" "}
                {selectedLog?.performed_by_name ?? "System"}
              </div>
              <div>
                <span className="font-medium text-foreground">IP:</span>{" "}
                {selectedLog?.ip_address ?? "—"}
              </div>
              <div>
                <span className="font-medium text-foreground">Time (IST):</span>{" "}
                {selectedLog ? toIST(selectedLog.created_at) : "—"}
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <JsonBlock label="Before" value={selectedLog?.before_value ?? null} />
              <JsonBlock label="After" value={selectedLog?.after_value ?? null} />
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </PortalLayout>
  );
}
