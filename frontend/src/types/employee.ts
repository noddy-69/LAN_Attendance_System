export interface EmployeeProfile {
  id: string;
  employee_code: string;
  first_name: string;
  last_name: string;
  email: string;
  phone: string | null;
  role_name: string;
  branch_id: string;
  branch_name: string | null;
  department_id: string | null;
  department_name: string | null;
  is_active: boolean;
  avatar_url: string | null;
  permissions: string[];
}

export const ROLE_REDIRECT: Record<string, string> = {
  admin: "/admin/dashboard",
  hr: "/hr/dashboard",
  manager: "/manager/dashboard",
  employee: "/employee/dashboard",
};
