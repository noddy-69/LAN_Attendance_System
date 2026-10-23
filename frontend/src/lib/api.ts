/**
 * Typed Axios instance with JWT interceptor and auto-refresh on 401.
 *
 * Token lifecycle
 * ---------------
 * - access_token (15 min): stored in sessionStorage + Zustand.
 * - refresh_token (7 days): HttpOnly cookie — never touched by JS.
 *
 * On 401: calls POST /auth/refresh with credentials:include so the
 * browser sends the HttpOnly refresh cookie. If refresh succeeds, the
 * original request is retried with the new access token. If refresh
 * fails, the user is cleared and redirected to /login.
 */

import axios, { AxiosError, AxiosInstance, InternalAxiosRequestConfig } from "axios";
import { API_BASE, TOKEN_KEY } from "@/lib/constants";
import type { PaginationMeta } from "@/types/api";

interface ApiEnvelope<T> {
  success: boolean;
  data: T | null;
  error: string | null;
  pagination: PaginationMeta | null;
}

let isRefreshing = false;
let pendingQueue: Array<{
  resolve: (token: string) => void;
  reject: (err: unknown) => void;
}> = [];

function flushQueue(token: string) {
  pendingQueue.forEach((p) => p.resolve(token));
  pendingQueue = [];
}

function rejectQueue(err: unknown) {
  pendingQueue.forEach((p) => p.reject(err));
  pendingQueue = [];
}

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return sessionStorage.getItem(TOKEN_KEY);
}

function saveToken(token: string) {
  if (typeof window !== "undefined") {
    sessionStorage.setItem(TOKEN_KEY, token);
  }
}

function clearSession() {
  if (typeof window !== "undefined") {
    sessionStorage.removeItem(TOKEN_KEY);
    document.cookie = "att_role=; path=/; max-age=0";
  }
}

export const api: AxiosInstance = axios.create({
  baseURL: API_BASE,
  withCredentials: true, // sends HttpOnly refresh cookie on every request
  headers: { "Content-Type": "application/json" },
  timeout: 15_000,
});

// ── Request interceptor: attach access token ───────────────────────────────────
api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = getToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// ── Response interceptor: auto-refresh on 401 ────────────────────────────────
api.interceptors.response.use(
  (res) => res,
  async (error: AxiosError) => {
    // Surface the backend's human-readable reason as the Error message, so UI alerts
    // show WHY a request failed (e.g. "Employee with this email or code already exists")
    // instead of the generic "Request failed with status code NNN".
    const backendMsg = (error.response?.data as { error?: string } | undefined)?.error;
    if (backendMsg) error.message = backendMsg;

    const original = error.config as InternalAxiosRequestConfig & {
      _retry?: boolean;
    };

    // Only intercept 401 errors that haven't been retried yet.
    // Skip the refresh endpoint itself to avoid infinite loops.
    if (
      error.response?.status !== 401 ||
      original._retry ||
      original.url?.endsWith("/auth/refresh") ||
      original.url?.endsWith("/auth/login")
    ) {
      return Promise.reject(error);
    }

    original._retry = true;

    if (isRefreshing) {
      // Another request is already refreshing — queue this one.
      return new Promise((resolve, reject) => {
        pendingQueue.push({
          resolve: (token) => {
            original.headers.Authorization = `Bearer ${token}`;
            resolve(api(original));
          },
          reject,
        });
      });
    }

    isRefreshing = true;

    try {
      const { data } = await axios.post(
        `${API_BASE}/auth/refresh`,
        {},
        { withCredentials: true }
      );
      const newToken: string = data?.data?.access_token;
      if (!newToken) throw new Error("No access_token in refresh response");

      saveToken(newToken);
      // Sync with Zustand store without importing it (avoids circular dep).
      // The store hydrates on next render; the cookie update is enough for middleware.
      original.headers.Authorization = `Bearer ${newToken}`;
      flushQueue(newToken);
      return api(original);
    } catch (refreshErr) {
      rejectQueue(refreshErr);
      clearSession();
      if (typeof window !== "undefined") {
        window.location.href = "/login";
      }
      return Promise.reject(refreshErr);
    } finally {
      isRefreshing = false;
    }
  }
);

// ── Typed helpers ─────────────────────────────────────────────────────────────

export async function apiGet<T>(url: string, params?: Record<string, unknown>) {
  const res = await api.get<ApiEnvelope<T>>(url, { params });
  return res.data;
}

export async function apiPost<T>(url: string, body?: unknown) {
  const res = await api.post<ApiEnvelope<T>>(url, body);
  return res.data;
}

export async function apiPatch<T>(url: string, body?: unknown) {
  const res = await api.patch<ApiEnvelope<T>>(url, body);
  return res.data;
}

export async function apiPut<T>(url: string, body?: unknown) {
  const res = await api.put<ApiEnvelope<T>>(url, body);
  return res.data;
}

export async function apiDelete<T>(url: string) {
  const res = await api.delete<ApiEnvelope<T>>(url);
  return res.data;
}
