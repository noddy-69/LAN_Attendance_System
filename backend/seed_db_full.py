"""
seed_db_full.py — Full database seed for the Attendance System
==============================================================
Idempotent: safe to run multiple times. Uses INSERT … ON CONFLICT DO NOTHING
or checks-before-insert so existing rows are never overwritten.

Seeds:
  1. All permissions
  2. Roles (admin, hr, manager, employee) with correct permission sets
  3. Head Office branch
  4. Default shift (Standard Day 09:00–18:00)
  5. Admin user (admin@attendance.local / Admin@1234)
  6. System policies
  7. Leave types (CL, SL, EL, ML, PL)
  8. Indian Gazetted Holidays 2026 (17 national public holidays)

Run:
  docker exec <backend_container> python seed_db_full.py
  OR via seed-db.sh from the project root
"""
import asyncio
import json
import os
from datetime import date, time

import bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from app.core.config import ASYNCPG_CONNECT_ARGS, settings

_engine = create_async_engine(
    settings.DATABASE_URL,
    connect_args=ASYNCPG_CONNECT_ARGS,
    echo=False,
)
_Session = async_sessionmaker(bind=_engine, expire_on_commit=False)

# Register all ORM models
import app.models  # noqa: F401

from app.models.branch import Branch
from app.models.employee import Employee
from app.models.leave import LeaveType
from app.models.role import Permission, Role
from app.models.shift import ShiftDefinition
from app.models.system import HolidayCalendar, HolidayType, SystemPolicy


# ── 1. Permissions & Roles ────────────────────────────────────────────────

_ROLE_PERMS: dict[str, list[str]] = {
    "admin": [
        "admin:*",
        "employees:read", "employees:write",
        "attendance:read", "attendance:write",
        "leave:read", "leave:write", "leave:approve",
        "reimbursement:read", "reimbursement:write", "reimbursement:approve",
        "payroll:read", "payroll:write",
        "reports:read",
        "notification:read",
        "devices:read", "devices:write",
        "branches:read", "branches:write",
        "roles:read", "roles:write",
        "system:read", "system:write",
        "face:read", "face:write",
        "holiday:read", "holiday:write",
    ],
    "hr": [
        "employees:read", "employees:write",
        "attendance:read", "attendance:write",
        "leave:read", "leave:write", "leave:approve",
        "reimbursement:read", "reimbursement:write", "reimbursement:approve",
        "payroll:read", "payroll:write",
        "reports:read",
        "notification:read",
        # HR portal includes face enrollment photo upload
        "face:read", "face:write",
        # HR manages the holiday calendar (scoped — not full system:write)
        "holiday:read", "holiday:write",
        # Read-only access to reference lists so the Add/Edit Employee form's
        # Branch and Role dropdowns populate (HR assigns them, can't edit them).
        "branches:read", "roles:read",
    ],
    "manager": [
        # NOTE: employees:read intentionally excluded — managers access their
        # team via /employees/{id}/direct-reports (attendance:read permission).
        # Granting employees:read would expose the full company employee list.
        "attendance:read", "attendance:write",
        "leave:read", "leave:approve",
        "reimbursement:read", "reimbursement:approve",
        "reports:read",
        "notification:read",
    ],
    "employee": [
        "attendance:read",
        "leave:read", "leave:write",
        "reimbursement:read", "reimbursement:write",
        "notification:read",
    ],
    # Machine account for the face-recognition microservice — it only posts
    # camera events, so it gets the narrowest possible permission set.
    "service": [
        "attendance:write",
    ],
}

_ALL_PERMS = sorted({p for perms in _ROLE_PERMS.values() for p in perms})


async def seed_permissions_and_roles(db: AsyncSession) -> dict[str, Role]:
    # Permissions
    res = await db.execute(select(Permission))
    existing_perms = {p.name: p for p in res.scalars().all()}
    for name in _ALL_PERMS:
        if name not in existing_perms:
            p = Permission(name=name, description=f"Permission: {name}")
            db.add(p)
            existing_perms[name] = p
    await db.flush()

    # Roles
    res = await db.execute(select(Role).options(selectinload(Role.permissions)))
    existing_roles = {r.name: r for r in res.scalars().all()}
    roles: dict[str, Role] = {}
    for role_name, perm_keys in _ROLE_PERMS.items():
        wanted = [existing_perms[k] for k in perm_keys]
        if role_name in existing_roles:
            role = existing_roles[role_name]
            role.permissions = wanted
        else:
            role = Role(name=role_name, description=f"{role_name.title()} role")
            role.permissions = wanted
            db.add(role)
        roles[role_name] = role
    await db.flush()
    print(f"  Roles: {', '.join(roles)}")
    return roles


# ── 2. Branch ─────────────────────────────────────────────────────────────

async def seed_branch(db: AsyncSession) -> Branch:
    res = await db.execute(select(Branch).where(Branch.name == "Head Office"))
    branch = res.scalar_one_or_none()
    if not branch:
        branch = Branch(
            name="Head Office",
            city="Mumbai",
            state="Maharashtra",
            address="Corporate Office, Nariman Point, Mumbai 400021",
            office_start_time=time(9, 0),
            office_end_time=time(18, 0),
            grace_period_minutes=15,
        )
        db.add(branch)
        await db.flush()
        print("  Branch: Head Office (Mumbai) created")
    else:
        print("  Branch: Head Office already exists")
    return branch


# ── 3. Default shift ──────────────────────────────────────────────────────

async def seed_shift(db: AsyncSession, branch: Branch) -> ShiftDefinition:
    res = await db.execute(
        select(ShiftDefinition).where(ShiftDefinition.name == "Standard Day")
    )
    shift = res.scalar_one_or_none()
    if not shift:
        shift = ShiftDefinition(
            name="Standard Day",
            start_time=time(9, 0),
            end_time=time(18, 0),
            required_minutes=540,   # 9 hours
            is_overnight=False,
            branch_id=None,         # NULL → applies to all branches
        )
        db.add(shift)
        await db.flush()
        print("  Shift: Standard Day (09:00–18:00, 540 min) created")
    else:
        print("  Shift: Standard Day already exists")
    return shift


# ── 4. Admin user ─────────────────────────────────────────────────────────

# Configurable so an installer can set the initial admin per deployment.
ADMIN_EMAIL    = os.environ.get("ADMIN_EMAIL", "admin@test.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Admin@1234")
ADMIN_CODE     = os.environ.get("ADMIN_CODE", "EMP001")


async def seed_admin(db: AsyncSession, admin_role: Role, branch: Branch) -> None:
    # Check by employee_code first (unique constraint), then by email
    res = await db.execute(
        select(Employee).where(Employee.employee_code == ADMIN_CODE)
    )
    emp = res.scalar_one_or_none()

    if emp is None:
        res2 = await db.execute(select(Employee).where(Employee.email == ADMIN_EMAIL))
        emp = res2.scalar_one_or_none()

    if emp is not None:
        # Admin already exists. Because the seed now runs on every backend start,
        # we must NOT reset the password — the operator may have changed it.
        # Only keep role/branch/active correct.
        emp.role_id = admin_role.id
        emp.branch_id = branch.id
        emp.is_active = True
        print(f"  Admin: {ADMIN_EMAIL} already exists — left as-is (password unchanged)")
        return

    hashed = bcrypt.hashpw(ADMIN_PASSWORD.encode(), bcrypt.gensalt(rounds=12)).decode()
    emp = Employee(
        employee_code=ADMIN_CODE,
        first_name="System",
        last_name="Admin",
        email=ADMIN_EMAIL,
        password_hash=hashed,
        role_id=admin_role.id,
        branch_id=branch.id,
        date_of_joining=date.today(),
        is_active=True,
    )
    db.add(emp)
    print(f"  Admin: {ADMIN_EMAIL} / {ADMIN_PASSWORD}  [CREATED]")


# ── 4b. Face-service machine account ──────────────────────────────────────
# The face-recognition microservice logs in with these credentials to POST
# camera events. Override via SERVICE_ACCOUNT_EMAIL / SERVICE_ACCOUNT_PASSWORD
# in .env (the same values must be passed to the face-recognition container).

SERVICE_EMAIL    = os.environ.get("SERVICE_ACCOUNT_EMAIL", "face-service@attendance.app")
SERVICE_PASSWORD = os.environ.get("SERVICE_ACCOUNT_PASSWORD", "FaceService@1234")
SERVICE_CODE     = "SVC001"


async def seed_service_account(db: AsyncSession, service_role: Role, branch: Branch) -> None:
    res = await db.execute(
        select(Employee).where(Employee.employee_code == SERVICE_CODE)
    )
    emp = res.scalar_one_or_none()
    if emp is None:
        res2 = await db.execute(select(Employee).where(Employee.email == SERVICE_EMAIL))
        emp = res2.scalar_one_or_none()

    hashed = bcrypt.hashpw(SERVICE_PASSWORD.encode(), bcrypt.gensalt(rounds=12)).decode()
    if emp is not None:
        emp.email = SERVICE_EMAIL
        emp.password_hash = hashed
        emp.role_id = service_role.id
        emp.branch_id = branch.id
        emp.is_active = True
        print(f"  Service account: {SERVICE_EMAIL} already exists — credentials refreshed")
        return

    emp = Employee(
        employee_code=SERVICE_CODE,
        first_name="Face",
        last_name="Service",
        email=SERVICE_EMAIL,
        password_hash=hashed,
        role_id=service_role.id,
        branch_id=branch.id,
        date_of_joining=date.today(),
        is_active=True,
    )
    db.add(emp)
    print(f"  Service account: {SERVICE_EMAIL}  [CREATED]")


# ── 4c. Demo accounts (one ready-to-use login per portal) ─────────────────
# Created on every fresh setup so the system can be tested/demoed immediately.
# Set SEED_DEMO_ACCOUNTS=false (env) to skip these — recommended for production.

_DEMO_PASSWORD = os.environ.get("DEMO_ACCOUNT_PASSWORD", "Demo@1234")
_DEMO_ACCOUNTS = [
    # employee_code, first,   last,       email,                role
    ("DEMO-HR",      "Henry",  "HR",       "hr@test.com",       "hr"),
    ("DEMO-MGR",     "Maya",   "Manager",  "manager@test.com",  "manager"),
    ("DEMO-EMP",     "Evan",   "Employee", "employee@test.com", "employee"),
]


async def seed_demo_accounts(db: AsyncSession, roles: dict[str, Role], branch: Branch) -> None:
    if os.environ.get("SEED_DEMO_ACCOUNTS", "true").strip().lower() not in ("1", "true", "yes"):
        print("  Demo accounts: skipped (SEED_DEMO_ACCOUNTS is off)")
        return

    created: dict[str, Employee] = {}
    for code, first, last, email, role_name in _DEMO_ACCOUNTS:
        res = await db.execute(select(Employee).where(Employee.employee_code == code))
        emp = res.scalar_one_or_none()
        if emp is None:
            res2 = await db.execute(select(Employee).where(Employee.email == email))
            emp = res2.scalar_one_or_none()

        hashed = bcrypt.hashpw(_DEMO_PASSWORD.encode(), bcrypt.gensalt(rounds=12)).decode()
        if emp is None:
            emp = Employee(
                employee_code=code, first_name=first, last_name=last, email=email,
                password_hash=hashed, role_id=roles[role_name].id, branch_id=branch.id,
                date_of_joining=date.today(), is_active=True,
            )
            db.add(emp)
        else:
            emp.email = email
            emp.password_hash = hashed
            emp.role_id = roles[role_name].id
            emp.branch_id = branch.id
            emp.is_active = True
        created[role_name] = emp
    await db.flush()

    # The demo employee reports to the demo manager, so the approval chain
    # (employee -> manager -> HR) has a real team to demonstrate with.
    if "employee" in created and "manager" in created:
        created["employee"].manager_id = created["manager"].id
        await db.flush()

    print(
        "  Demo accounts: hr@test.com / manager@test.com / employee@test.com "
        f"(password: {_DEMO_PASSWORD})"
    )


# ── 5. System policies ────────────────────────────────────────────────────

_POLICIES: list[dict] = [
    {
        "key": "payroll.late_days_per_unit",
        "value": "3",
        "description": "Late days that make up one penalty unit (every 3 lates = a half day)",
    },
    {
        "key": "payroll.penalty_percent_per_unit",
        "value": "50",
        "description": "Percent of a day's salary deducted per penalty unit (50 = half day)",
    },
    {
        "key": "payroll.grace_days",
        "value": "1.5",
        "description": "Penalty-days forgiven each month before any deduction applies",
    },
    {
        "key": "payroll.salary_days_per_month",
        "value": "30",
        "description": "Divisor to derive a day's salary from the monthly salary (monthly / 30)",
    },
    {
        "key": "attendance.grace_period_minutes",
        "value": "15",
        "description": "Minutes after shift start before a check-in is considered late",
    },
    {
        "key": "attendance.saturday_off",
        "value": "true",
        "description": "Whether Saturday counts as a weekly off (Sunday is always off)",
    },
    {
        "key": "attendance.min_work_hours_half_day",
        "value": "240",
        "description": "Minimum work minutes to count as a half day (240 = 4 hours)",
    },
    {
        "key": "attendance.min_work_hours_full_day",
        "value": "480",
        "description": "Minimum work minutes to count as a full day (480 = 8 hours)",
    },
    {
        "key": "face.confidence_threshold",
        "value": "0.40",
        "description": "Cosine similarity threshold for face recognition (0-1). "
                       "Genuine matches with buffalo_sc score ~0.4-0.6; raise toward "
                       "0.5 for stricter matching, lower toward 0.35 for easier matching.",
    },
    {
        "key": "face.cooldown_seconds",
        "value": "300",
        "description": "Seconds between two attendance events for the same employee on the same camera",
    },
    {
        "key": "notifications.whatsapp_enabled",
        "value": "false",
        "description": "Set true after configuring the WhatsApp Cloud API in Admin → Settings → Notifications",
    },
    {
        "key": "notifications.email_enabled",
        "value": "false",
        "description": "Set true after configuring SMTP settings in .env",
    },
]


async def seed_policies(db: AsyncSession) -> None:
    res = await db.execute(select(SystemPolicy))
    existing = {p.key for p in res.scalars().all()}
    inserted = 0
    for pol in _POLICIES:
        if pol["key"] not in existing:
            db.add(SystemPolicy(
                key=pol["key"],
                value=pol["value"],
                description=pol["description"],
            ))
            inserted += 1
    await db.flush()
    print(f"  System policies: {inserted} inserted, {len(_POLICIES) - inserted} already existed")


# ── 6. Leave types ────────────────────────────────────────────────────────

_LEAVE_TYPES: list[dict] = [
    {
        "name": "Casual Leave",
        "code": "CL",
        "days_per_year": 12,
        "is_paid": True,
        "requires_approval": True,
        "carry_forward": False,
        "max_carry_forward_days": 0,
        "description": "General purpose leave for personal matters",
    },
    {
        "name": "Sick Leave",
        "code": "SL",
        "days_per_year": 6,
        "is_paid": True,
        "requires_approval": False,
        "carry_forward": False,
        "max_carry_forward_days": 0,
        "description": "Medical / health related leave",
    },
    {
        "name": "Earned Leave",
        "code": "EL",
        "days_per_year": 15,
        "is_paid": True,
        "requires_approval": True,
        "carry_forward": True,
        "max_carry_forward_days": 30,
        "description": "Privilege leave accrued based on days worked; can carry forward",
    },
    {
        "name": "Maternity Leave",
        "code": "ML",
        "days_per_year": 182,
        "is_paid": True,
        "requires_approval": True,
        "carry_forward": False,
        "max_carry_forward_days": 0,
        "description": "26 weeks as per Maternity Benefit Act 1961",
    },
    {
        "name": "Paternity Leave",
        "code": "PL",
        "days_per_year": 15,
        "is_paid": True,
        "requires_approval": True,
        "carry_forward": False,
        "max_carry_forward_days": 0,
        "description": "15 days for fathers around the birth of a child",
    },
    {
        "name": "Leave Without Pay",
        "code": "LWP",
        "days_per_year": 30,
        "is_paid": False,
        "requires_approval": True,
        "carry_forward": False,
        "max_carry_forward_days": 0,
        "description": "Unpaid leave when other balances are exhausted",
    },
]


async def seed_leave_types(db: AsyncSession) -> None:
    res = await db.execute(select(LeaveType))
    existing = {lt.code for lt in res.scalars().all()}
    inserted = 0
    for lt in _LEAVE_TYPES:
        if lt["code"] not in existing:
            db.add(LeaveType(**lt))
            inserted += 1
    await db.flush()
    codes = [lt["code"] for lt in _LEAVE_TYPES]
    print(f"  Leave types ({', '.join(codes)}): {inserted} inserted, {len(_LEAVE_TYPES)-inserted} already existed")


# ── 7. Indian Gazetted Holidays 2026 ─────────────────────────────────────
# Source: Ministry of Personnel, Public Grievances & Pensions
# Central Government Gazetted Holidays for 2026

_HOLIDAYS_2026: list[tuple[date, str]] = [
    (date(2026, 1, 1),  "New Year's Day"),
    (date(2026, 1, 14), "Makar Sankranti / Pongal"),
    (date(2026, 1, 26), "Republic Day"),
    (date(2026, 3, 20), "Holi"),           # Dhulendi
    (date(2026, 3, 29), "Easter Sunday"),
    (date(2026, 4, 2),  "Rama Navami"),
    (date(2026, 4, 3),  "Good Friday"),
    (date(2026, 4, 14), "Dr. B.R. Ambedkar Jayanti"),
    (date(2026, 5, 1),  "Maharashtra Day / Labour Day"),
    (date(2026, 8, 15), "Independence Day"),
    (date(2026, 8, 21), "Janmashtami"),
    (date(2026, 9, 2),  "Ganesh Chaturthi"),
    (date(2026, 10, 2), "Gandhi Jayanti / Dussehra"),
    (date(2026, 10, 21),"Diwali (Laxmi Puja)"),
    (date(2026, 10, 22),"Diwali (Bali Pratipada)"),
    (date(2026, 11, 5), "Guru Nanak Jayanti"),
    (date(2026, 12, 25),"Christmas Day"),
]


async def seed_holidays(db: AsyncSession) -> None:
    # ── Clean up any test/placeholder entries before seeding ─────────────
    # The unique constraint on (date, branch_id) doesn't block NULL duplicates,
    # so we must delete stale rows explicitly before inserting the real data.
    from sqlalchemy import delete as sa_delete, and_
    await db.execute(
        sa_delete(HolidayCalendar).where(
            and_(
                HolidayCalendar.year == 2026,
                HolidayCalendar.branch_id.is_(None),   # national only
            )
        )
    )
    await db.flush()

    # ── Insert the canonical 2026 holiday list ────────────────────────────
    for hdate, hname in _HOLIDAYS_2026:
        db.add(HolidayCalendar(
            name=hname,
            date=hdate,
            branch_id=None,
            holiday_type=HolidayType.NATIONAL,
            year=2026,
        ))
    await db.flush()
    print(
        f"  Holidays 2026: {len(_HOLIDAYS_2026)} national holidays loaded "
        f"({_HOLIDAYS_2026[0][0]} … {_HOLIDAYS_2026[-1][0]})"
    )


# ── Main ──────────────────────────────────────────────────────────────────

async def main() -> None:
    print("\n════════════════════════════════════════════════")
    print("  Attendance System — Database Seed")
    print("════════════════════════════════════════════════")

    async with _Session() as db:
        print("\n[1] Seeding permissions and roles...")
        roles = await seed_permissions_and_roles(db)

        print("\n[2] Seeding branch...")
        branch = await seed_branch(db)

        print("\n[3] Seeding default shift...")
        await seed_shift(db, branch)

        print("\n[4] Seeding admin user...")
        await seed_admin(db, roles["admin"], branch)

        print("\n[4b] Seeding face-service account...")
        await seed_service_account(db, roles["service"], branch)

        print("\n[4c] Seeding demo accounts...")
        await seed_demo_accounts(db, roles, branch)

        print("\n[5] Seeding system policies...")
        await seed_policies(db)

        print("\n[6] Seeding leave types...")
        await seed_leave_types(db)

        print("\n[7] Seeding Indian holidays 2026...")
        await seed_holidays(db)

        await db.commit()

    await _engine.dispose()

    print("\n════════════════════════════════════════════════")
    print("  Seed complete!")
    print("  Logins:")
    print(f"    Admin    : {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
    print(f"    HR       : hr@test.com / {_DEMO_PASSWORD}")
    print(f"    Manager  : manager@test.com / {_DEMO_PASSWORD}")
    print(f"    Employee : employee@test.com / {_DEMO_PASSWORD}")
    print("════════════════════════════════════════════════\n")


if __name__ == "__main__":
    asyncio.run(main())
