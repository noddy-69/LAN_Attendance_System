import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

export function formatDateTime(dateStr: string): string {
  return new Date(dateStr).toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Asia/Kolkata",
  });
}

export function formatMinutes(minutes: number | null): string {
  if (minutes === null) return "—";
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

export function formatPaise(paise: number): string {
  return `₹${(paise / 100).toFixed(2)}`;
}

/**
 * Display form of a role name. Roles are stored lowercase ("hr", "admin", …); this
 * title-cases each word but keeps "HR" fully uppercase (it's an acronym, not a word).
 * e.g. "hr" → "HR", "admin" → "Admin", "manager" → "Manager".
 */
export function formatRoleName(name: string): string {
  if (!name) return name;
  return name
    .split(/[\s_]+/)
    .map((w) =>
      w.toLowerCase() === "hr"
        ? "HR"
        : w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()
    )
    .join(" ");
}

/**
 * Calendar date (YYYY-MM-DD) of a given instant **in IST**. Use this instead of
 * `someDate.toISOString().split("T")[0]`, which returns the UTC date — a day behind
 * between 00:00 and 05:30 IST. The backend files attendance under the IST date, so a
 * UTC "today" misses today's records during that window (shows Absent, hides proofs).
 */
export function istDateStr(d: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(d);
}

/** Today's date (YYYY-MM-DD) in IST. */
export function istToday(): string {
  return istDateStr();
}

export function toIST(utcString: string | null | undefined): string {
  if (!utcString) return "—";
  return new Date(utcString).toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export async function downloadFile(
  url: string,
  filename: string,
  token: string | null
): Promise<void> {
  const res = await fetch(url, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new Error(`Download failed: ${res.status}`);
  const blob = await res.blob();
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(href);
}
