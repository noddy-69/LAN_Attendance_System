export type LeaveStatus =
  | "PENDING"
  | "MANAGER_APPROVED"
  | "APPROVED"
  | "REJECTED"
  | "CANCELLED";

export interface LeaveType {
  id: string;
  name: string;
  code: string;
  max_days_per_year: number;
  requires_proof: boolean;
}

export interface LeaveRequest {
  id: string;
  employee_id: string;
  leave_type_id: string;
  leave_type?: LeaveType;
  start_date: string;
  end_date: string;
  days_requested: number;
  reason: string;
  status: LeaveStatus;
  manager_remarks: string | null;
  hr_remarks: string | null;
  created_at: string;
}

export interface LeaveBalance {
  id: string;
  employee_id: string;
  leave_type_id: string;
  leave_type?: LeaveType;
  year: number;
  total_days: number;
  used_days: number;
  pending_days: number;
  remaining_days: number;
}
