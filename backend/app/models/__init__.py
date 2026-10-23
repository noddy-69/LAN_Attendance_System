from app.models.base import Base

# Import every model so their tables register on Base.metadata.
# Order matters only for readability — SQLAlchemy resolves FK references lazily.
from app.models.role import Permission, Role, role_permissions          # noqa: F401
from app.models.branch import Branch, Department                        # noqa: F401
from app.models.shift import ShiftDefinition                            # noqa: F401
from app.models.employee import Employee                                 # noqa: F401
from app.models.employee_hierarchy import EmployeeHierarchy             # noqa: F401
from app.models.face_embedding import FaceEmbedding                     # noqa: F401
from app.models.device import Device, DeviceType                        # noqa: F401
from app.models.attendance_event import AttendanceEvent, AttendanceSource, EventType  # noqa: F401
from app.models.daily_attendance import DailyAttendance, AttendanceStatus  # noqa: F401
from app.models.attendance_proof import AttendanceProof, ProofType      # noqa: F401
from app.models.leave import LeaveBalance, LeaveRequest, LeaveType, LeaveStatus  # noqa: F401
from app.models.reimbursement import Reimbursement, ReimbursementDocument  # noqa: F401
from app.models.payroll import SalaryDeduction                          # noqa: F401
from app.models.notification import Notification, NotificationEvent, NotificationChannel, NotificationStatus  # noqa: F401
from app.models.system import AuditLog, HolidayCalendar, SystemPolicy   # noqa: F401

__all__ = [
    "Base",
    "Permission", "Role",
    "Branch", "Department",
    "ShiftDefinition",
    "Employee",
    "EmployeeHierarchy",
    "FaceEmbedding",
    "Device",
    "AttendanceEvent",
    "DailyAttendance",
    "AttendanceProof",
    "LeaveType", "LeaveRequest", "LeaveBalance",
    "Reimbursement", "ReimbursementDocument",
    "SalaryDeduction",
    "Notification",
    "AuditLog", "HolidayCalendar", "SystemPolicy",
]
