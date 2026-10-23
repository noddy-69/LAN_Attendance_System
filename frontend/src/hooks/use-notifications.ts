"use client";

import { useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuthStore } from "@/stores/auth-store";
import { useNotificationStore } from "@/stores/notification-store";
import { apiGet, apiPost } from "@/lib/api";

interface Notification {
  id: string;
  event_type: string;
  title: string;
  body: string;
  status: string;
  created_at: string;
}

export function useNotifications(unreadOnly = false) {
  const { isAuthenticated } = useAuthStore();
  const setUnreadCount = useNotificationStore((s) => s.setUnreadCount);

  const query = useQuery({
    queryKey: ["notifications", unreadOnly],
    queryFn: async () => {
      const res = await apiGet<Notification[]>("/notifications", {
        unread_only: unreadOnly,
      });
      return res.data ?? [];
    },
    enabled: isAuthenticated,
    refetchInterval: 60_000, // poll every 60 s for new notifications
  });

  const unreadQuery = useQuery({
    queryKey: ["notifications-unread-count"],
    queryFn: async () => {
      const res = await apiGet<{ count: number }>("/notifications/unread-count");
      return res.data?.count ?? 0;
    },
    enabled: isAuthenticated,
    refetchInterval: 60_000,
  });

  useEffect(() => {
    if (unreadQuery.data !== undefined) {
      setUnreadCount(unreadQuery.data);
    }
  }, [unreadQuery.data, setUnreadCount]);

  return query;
}

export function useMarkNotificationRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiPost(`/notifications/${id}/read`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["notifications"] });
      qc.invalidateQueries({ queryKey: ["notifications-unread-count"] });
    },
  });
}
