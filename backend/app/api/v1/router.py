from fastapi import APIRouter

from app.api.v1.routers import (
    attendance,
    auth,
    branches,
    departments,
    devices,
    employees,
    face,
    health,
    leave,
    notifications,
    payroll,
    reports,
    reimbursements,
    roles,
    shifts,
    system,
)

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(employees.router)
api_router.include_router(attendance.router)
api_router.include_router(leave.router)
api_router.include_router(reimbursements.router)
api_router.include_router(payroll.router)
api_router.include_router(notifications.router)
api_router.include_router(devices.router)
api_router.include_router(branches.router)
api_router.include_router(departments.router)
api_router.include_router(roles.router)
api_router.include_router(reports.router)
api_router.include_router(face.router)
api_router.include_router(shifts.router)
api_router.include_router(system.router)
