"use client";

import { useQuery } from "@tanstack/react-query";
import { useAuthStore } from "@/stores/auth-store";
import { apiGet } from "@/lib/api";
import { istDateStr } from "@/lib/utils";
import { DailyAttendance } from "@/types/attendance";

export function useTodayAttendance(employeeId?: string) {
  const { isAuthenticated } = useAuthStore();
  const today = istDateStr();

  return useQuery({
    queryKey: ["attendance", "today", employeeId],
    queryFn: async () => {
      const url = employeeId
        ? `/attendance/daily/${employeeId}?date=${today}`
        : `/attendance/me/today`;
      const res = await apiGet<DailyAttendance>(url);
      return res.data;
    },
    enabled: isAuthenticated,
    staleTime: 60_000,
  });
}

export function useAttendanceCalendar(
  employeeId: string | undefined,
  year: number,
  month: number
) {
  const { isAuthenticated } = useAuthStore();

  return useQuery({
    queryKey: ["attendance", "calendar", employeeId, year, month],
    queryFn: async () => {
      const res = await apiGet<DailyAttendance[]>("/attendance/me/calendar", {
        year,
        month,
      });
      return res.data ?? [];
    },
    enabled: isAuthenticated && !!employeeId,
  });
}
