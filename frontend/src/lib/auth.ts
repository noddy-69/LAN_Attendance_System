"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/stores/auth-store";
import { ROLE_REDIRECT, TOKEN_KEY } from "@/lib/constants";
import { apiPost, apiGet } from "@/lib/api";
import { EmployeeProfile } from "@/types/employee";
import { TokenResponse } from "@/types/api";

// ── Login ─────────────────────────────────────────────────────────────────────

export async function login(email: string, password: string): Promise<EmployeeProfile> {
  const loginRes = await apiPost<TokenResponse>("/auth/login", { email, password });
  if (!loginRes.success || !loginRes.data) {
    throw new Error(loginRes.error ?? "Login failed");
  }

  const { access_token } = loginRes.data;

  // Save the token to sessionStorage BEFORE calling /me so the Axios
  // request interceptor picks it up and adds the Authorization header.
  if (typeof window !== "undefined") {
    sessionStorage.setItem(TOKEN_KEY, access_token);
  }

  const meRes = await apiGet<EmployeeProfile>("/auth/me");
  if (!meRes.success || !meRes.data) {
    throw new Error("Could not fetch user profile");
  }

  useAuthStore.getState().setAuth(meRes.data, access_token);
  return meRes.data;
}

// ── Logout ────────────────────────────────────────────────────────────────────

export async function logout(): Promise<void> {
  try {
    await apiPost("/auth/logout");
  } catch {
    // best effort
  }
  useAuthStore.getState().clearAuth();
}

// ── useAuth hook ──────────────────────────────────────────────────────────────

export function useAuth() {
  const { user, token, isAuthenticated, setAuth, clearAuth, hydrateFromStorage } =
    useAuthStore();

  // Hydrate token from sessionStorage after client mount.
  useEffect(() => {
    hydrateFromStorage();
  }, [hydrateFromStorage]);

  const fetchMe = async (): Promise<EmployeeProfile | null> => {
    try {
      const res = await apiGet<EmployeeProfile>("/auth/me");
      if (res.success && res.data) {
        // Preserve existing token if already set
        const t = token ?? "";
        setAuth(res.data, t);
        return res.data;
      }
    } catch {
      clearAuth();
    }
    return null;
  };

  return { user, token, isAuthenticated, fetchMe };
}

// ── AuthGuard ─────────────────────────────────────────────────────────────────

/**
 * Wraps a page/layout to enforce authentication.
 * If the user is not authenticated, redirects to /login.
 * If `requiredRole` is provided, also checks the role.
 */
export function useAuthGuard(requiredRole?: string) {
  const router = useRouter();
  const { user, isAuthenticated } = useAuthStore();

  useEffect(() => {
    if (!isAuthenticated || !user) {
      router.replace("/login");
      return;
    }
    if (requiredRole && user.role_name.toLowerCase() !== requiredRole.toLowerCase()) {
      // Wrong portal — redirect to the correct one
      const correctPath =
        ROLE_REDIRECT[user.role_name.toLowerCase()] ?? "/employee/dashboard";
      router.replace(correctPath);
    }
  }, [isAuthenticated, user, router, requiredRole]);

  return { user, isAuthenticated };
}
