export type AttendanceStatus =
  | "PRESENT"
  | "ABSENT"
  | "HALF_DAY"
  | "LATE"
  | "ON_LEAVE"
  | "HOLIDAY"
  | "WEEKEND"
  | "PENDING_CORRECTION";

export type AttendanceSource = "face_recognition" | "biometric" | "manual";

export interface DailyAttendance {
  id: string;
  employee_id: string;
  date: string;
  check_in: string | null;
  check_out: string | null;
  work_minutes: number | null;
  overtime_minutes: number;
  late_minutes: number;
  is_late: boolean;
  status: AttendanceStatus;
  source: AttendanceSource;
  notes: string | null;
}

export interface AttendanceProof {
  id: string;
  attendance_event_id: string;
  proof_type: "entry" | "exit";
  file_path: string;
  presigned_url?: string;
}
