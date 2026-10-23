import { create } from "zustand";
import { EmployeeProfile } from "@/types/employee";
import { TOKEN_KEY, ROLE_COOKIE } from "@/lib/constants";

interface AuthState {
  user: EmployeeProfile | null;
  token: string | null;
  isAuthenticated: boolean;
  // False until the app has attempted to restore a session from storage on load.
  // Pages must not redirect to /login while this is false (avoids a bogus logout on refresh).
  initialized: boolean;
  setAuth: (user: EmployeeProfile, token: string) => void;
  clearAuth: () => void;
  setInitialized: (v: boolean) => void;
  hydrateFromStorage: () => void;
}

function setRoleCookie(role: string) {
  if (typeof document === "undefined") return;
  const maxAge = 7 * 24 * 3600; // 7 days (matches refresh token TTL)
  document.cookie = `${ROLE_COOKIE}=${role}; path=/; max-age=${maxAge}; SameSite=Lax`;
}

function clearRoleCookie() {
  if (typeof document === "undefined") return;
  document.cookie = `${ROLE_COOKIE}=; path=/; max-age=0`;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  token: null,
  isAuthenticated: false,
  initialized: false,

  setInitialized(v) {
    set({ initialized: v });
  },

  setAuth(user, token) {
    if (typeof window !== "undefined") {
      sessionStorage.setItem(TOKEN_KEY, token);
    }
    setRoleCookie(user.role_name.toLowerCase());
    set({ user, token, isAuthenticated: true });
  },

  clearAuth() {
    if (typeof window !== "undefined") {
      sessionStorage.removeItem(TOKEN_KEY);
    }
    clearRoleCookie();
    set({ user: null, token: null, isAuthenticated: false });
  },

  hydrateFromStorage() {
    if (typeof window === "undefined") return;
    const token = sessionStorage.getItem(TOKEN_KEY);
    if (token) {
      set({ token, isAuthenticated: true });
    }
  },
}));
