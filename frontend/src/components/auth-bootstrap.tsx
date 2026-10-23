"use client";

import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useAuthStore } from "@/stores/auth-store";
import { apiGet } from "@/lib/api";
import { TOKEN_KEY } from "@/lib/constants";
import { EmployeeProfile } from "@/types/employee";

/**
 * Restores the auth session on app load / refresh.
 *
 * The access token lives in sessionStorage (survives a page reload). On mount we call
 * /auth/me — the axios interceptor auto-refreshes the token (via the HttpOnly refresh
 * cookie) if it has expired. On success the store is repopulated; on failure it is cleared.
 * Children are gated behind an `initialized` flag so protected pages don't wrongly bounce
 * to /login before the session has been restored.
 */
export function AuthBootstrap({ children }: { children: React.ReactNode }) {
  const initialized = useAuthStore((s) => s.initialized);
  const setAuth = useAuthStore((s) => s.setAuth);
  const clearAuth = useAuthStore((s) => s.clearAuth);
  const setInitialized = useAuthStore((s) => s.setInitialized);
  const qc = useQueryClient();

  useEffect(() => {
    let cancelled = false;
    const token = typeof window !== "undefined" ? sessionStorage.getItem(TOKEN_KEY) : null;

    // No stored token → definitely logged out; render immediately (e.g. the login page).
    if (!token) {
      setInitialized(true);
      return;
    }

    (async () => {
      try {
        const res = await apiGet<EmployeeProfile>("/auth/me");
        if (cancelled) return;
        if (res.success && res.data) {
          // The interceptor may have refreshed the token — read the latest value.
          setAuth(res.data, sessionStorage.getItem(TOKEN_KEY) ?? token);
          qc.setQueryData(["me"], res.data);
        } else {
          clearAuth();
        }
      } catch {
        if (!cancelled) clearAuth();
      } finally {
        if (!cancelled) setInitialized(true);
      }
    })();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!initialized) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
      </div>
    );
  }

  return <>{children}</>;
}
