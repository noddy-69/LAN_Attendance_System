"use client";

import { Bell } from "lucide-react";
import Link from "next/link";
import { useNotificationStore } from "@/stores/notification-store";
import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/stores/auth-store";
import { ROLE_REDIRECT } from "@/lib/constants";

export function NotificationBell() {
  const unreadCount = useNotificationStore((s) => s.unreadCount);
  const user = useAuthStore((s) => s.user);
  const role = user?.role_name.toLowerCase() ?? "employee";
  const base = ROLE_REDIRECT[role]?.replace("/dashboard", "") ?? "/employee";

  return (
    <Button variant="ghost" size="icon" asChild className="relative h-11 w-11" aria-label="Notifications">
      <Link href={`${base}/notifications`}>
        <Bell className="h-5 w-5" />
        {unreadCount > 0 && (
          <span className="absolute -right-1 -top-1 flex h-4 w-4 items-center justify-center rounded-full bg-destructive text-[10px] font-bold text-destructive-foreground">
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        )}
      </Link>
    </Button>
  );
}
