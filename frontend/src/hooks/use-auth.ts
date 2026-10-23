"use client";

import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuthStore } from "@/stores/auth-store";
import { apiGet } from "@/lib/api";
import { login as authLogin, logout as authLogout } from "@/lib/auth";
import { EmployeeProfile } from "@/types/employee";

export function useMe() {
  const { token } = useAuthStore();
  return useQuery({
    queryKey: ["me"],
    queryFn: async () => {
      const res = await apiGet<EmployeeProfile>("/auth/me");
      if (!res.success || !res.data) throw new Error(res.error ?? "Unauthorized");
      return res.data;
    },
    enabled: !!token,
    staleTime: 5 * 60_000,
    retry: false,
  });
}

export function useLoginMutation() {
  const router = useRouter();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: ({ email, password }: { email: string; password: string }) =>
      authLogin(email, password),
    onSuccess: (user) => {
      qc.setQueryData(["me"], user);
      const role = user.role_name.toLowerCase();
      const dest =
        role === "admin"
          ? "/admin/dashboard"
          : role === "hr"
          ? "/hr/dashboard"
          : role === "manager"
          ? "/manager/dashboard"
          : "/employee/dashboard";
      router.push(dest);
    },
  });
}

export function useLogoutMutation() {
  const router = useRouter();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: authLogout,
    onSettled: () => {
      qc.clear();
      router.push("/login");
    },
  });
}
