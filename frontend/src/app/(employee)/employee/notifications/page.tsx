"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Bell, CheckCheck } from "lucide-react";
import { useAuthStore } from "@/stores/auth-store";
import { useMe } from "@/hooks/use-auth";
import { useNotifications } from "@/hooks/use-notifications";
import { apiPost } from "@/lib/api";
import { EmployeeLayout } from "@/components/employee/EmployeeLayout";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { toIST } from "@/lib/utils";

export default function NotificationsPage() {
  const router = useRouter();
  const { isAuthenticated } = useAuthStore();
  const { data: user, isLoading: userLoading } = useMe();
  const qc = useQueryClient();

  useEffect(() => {
    if (!isAuthenticated && !userLoading) router.replace("/login");
  }, [isAuthenticated, userLoading, router]);

  const { data: notifications = [], isLoading } = useNotifications(false);

  const { mutate: markRead } = useMutation({
    mutationFn: (id: string) => apiPost(`/notifications/${id}/read`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["notifications"] });
      qc.invalidateQueries({ queryKey: ["notifications-unread-count"] });
    },
  });

  const { mutate: markAll } = useMutation({
    mutationFn: () => apiPost("/notifications/read-all"),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["notifications"] });
      qc.invalidateQueries({ queryKey: ["notifications-unread-count"] });
    },
  });

  if (userLoading || !user) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
      </div>
    );
  }

  const unread = notifications.filter(n => n.status !== "SENT").length;

  return (
    <EmployeeLayout pageTitle="Notifications">
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
            {notifications.map(n => {
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
    </EmployeeLayout>
  );
}
