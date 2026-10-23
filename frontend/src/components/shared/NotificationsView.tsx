"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Bell, CheckCheck } from "lucide-react";
import { useNotifications } from "@/hooks/use-notifications";
import { apiPost } from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { toIST } from "@/lib/utils";

/**
 * Shared notifications feed — the per-user list with mark-read / mark-all-read.
 * Rendered inside each portal's own layout (Employee, Manager, HR, Admin) so the
 * notification bell in the shared navbar works for every role.
 */
export function NotificationsView() {
  const qc = useQueryClient();
  const { data: notifications = [], isLoading } = useNotifications(false);

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["notifications"] });
    qc.invalidateQueries({ queryKey: ["notifications-unread-count"] });
  };

  const { mutate: markRead } = useMutation({
    mutationFn: (id: string) => apiPost(`/notifications/${id}/read`),
    onSuccess: invalidate,
  });

  const { mutate: markAll } = useMutation({
    mutationFn: () => apiPost("/notifications/read-all"),
    onSuccess: invalidate,
  });

  const unread = notifications.filter((n) => n.status !== "SENT").length;

  return (
    <div className="mx-auto max-w-xl space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold">Notifications</h2>
        {unread > 0 && (
          <Button variant="ghost" size="sm" onClick={() => markAll()} className="text-xs">
            Mark all read
          </Button>
        )}
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-16 rounded-xl" />
          ))}
        </div>
      ) : notifications.length === 0 ? (
        <div className="flex flex-col items-center rounded-xl border border-dashed py-12 text-muted-foreground">
          <Bell className="mb-2 h-8 w-8 opacity-40" />
          <p className="text-sm">No notifications yet.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {notifications.map((n) => {
            const unreadItem = n.status !== "SENT";
            return (
              <button
                key={n.id}
                onClick={() => unreadItem && markRead(n.id)}
                className={`flex w-full items-start gap-3 rounded-xl border p-3 text-left transition-colors active:bg-muted ${
                  unreadItem ? "border-primary/20 bg-primary/5" : "bg-card"
                }`}
              >
                <div className={`mt-1 h-2 w-2 shrink-0 rounded-full ${unreadItem ? "bg-primary" : "bg-transparent"}`} />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium">{n.title}</p>
                  <p className="mt-0.5 text-xs text-muted-foreground">{n.body}</p>
                  <p className="mt-1 text-[10px] text-muted-foreground">{toIST(n.created_at)}</p>
                </div>
                {!unreadItem && <CheckCheck className="mt-1 h-3.5 w-3.5 shrink-0 text-muted-foreground" />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
