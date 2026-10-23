// Default to a RELATIVE path so the browser always calls the same origin that
// served the page (nginx proxies /api/ → backend). This works on localhost, any
// LAN IP (phones / other office devices), and HTTPS without rebuilding. Only set
// NEXT_PUBLIC_API_URL (build arg) when the API lives on a different origin.
export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "/api/v1";

export const TOKEN_KEY = "att_access_token";
export const ROLE_COOKIE = "att_role";

export const ROLE_REDIRECT: Record<string, string> = {
  admin: "/admin/dashboard",
  hr: "/hr/dashboard",
  manager: "/manager/dashboard",
  employee: "/employee/dashboard",
};

// Protected path prefixes — middleware redirects unauthenticated users to login
export const PROTECTED_PREFIXES = ["/admin", "/hr", "/manager", "/employee"];

export const STATUS_COLORS: Record<string, string> = {
  PRESENT: "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400",
  LATE: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400",
  ABSENT: "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400",
  HALF_DAY: "bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-400",
  ON_LEAVE: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400",
  HOLIDAY: "bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-400",
  WEEKEND: "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400",
  PENDING_CORRECTION: "bg-pink-100 text-pink-800 dark:bg-pink-900/30 dark:text-pink-400",
  PENDING: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400",
  PENDING_MANAGER: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400",
  PENDING_HR: "bg-teal-100 text-teal-800 dark:bg-teal-900/30 dark:text-teal-400",
  APPROVED: "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400",
  MANAGER_APPROVED: "bg-teal-100 text-teal-800 dark:bg-teal-900/30 dark:text-teal-400",
  REJECTED: "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400",
  CANCELLED: "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400",
  SENT: "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400",
  FAILED: "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400",
};
