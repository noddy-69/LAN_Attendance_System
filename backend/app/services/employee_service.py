"""Employee CRUD + hierarchy service."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import license as license_mod
from app.core.exceptions import ConflictError, NotFoundError, UnprocessableError
from app.core.security import hash_password
from app.models.employee import Employee
from app.models.role import Role
from app.models.system import AuditAction, AuditLog
from app.schemas.common import PaginationMeta
from app.schemas.employees import EmployeeCreate, EmployeeUpdate, HierarchyNodeOut
from app.utils.pagination import paginate

_EAGER = [
    selectinload(Employee.role),
    selectinload(Employee.branch),
    selectinload(Employee.department),
    selectinload(Employee.manager),
]


async def _get_or_404(db: AsyncSession, employee_id: uuid.UUID) -> Employee:
    result = await db.execute(
        select(Employee)
        .where(Employee.id == employee_id, Employee.deleted_at.is_(None))
        .options(*_EAGER)
    )
    emp = result.scalar_one_or_none()
    if not emp:
        raise NotFoundError(f"Employee {employee_id} not found")
    return emp


async def list_employees(
    db: AsyncSession,
    *,
    branch_id: uuid.UUID | None = None,
    department_id: uuid.UUID | None = None,
    role_id: uuid.UUID | None = None,
    is_active: bool | None = None,
    search: str | None = None,
    per_page: int = 20,
    cursor: str | None = None,
) -> tuple[list[Employee], PaginationMeta]:
    stmt = (
        select(Employee)
        # Exclude the face-service machine account (role 'service') — it lives in the
        # employees table only so the face-recognition microservice can authenticate; it
        # is not a real person and must not appear in employee lists or counts.
        .where(Employee.deleted_at.is_(None), ~Employee.role.has(Role.name == "service"))
        .options(*_EAGER)
    )
    if branch_id:
        stmt = stmt.where(Employee.branch_id == branch_id)
    if department_id:
        stmt = stmt.where(Employee.department_id == department_id)
    if role_id:
        stmt = stmt.where(Employee.role_id == role_id)
    if is_active is not None:
        stmt = stmt.where(Employee.is_active.is_(is_active))
    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(
            or_(
                Employee.first_name.ilike(pattern),
                Employee.last_name.ilike(pattern),
                Employee.email.ilike(pattern),
                Employee.employee_code.ilike(pattern),
            )
        )
    return await paginate(db, stmt, Employee, per_page, cursor)


async def get_employee(db: AsyncSession, employee_id: uuid.UUID) -> Employee:
    return await _get_or_404(db, employee_id)


async def create_employee(
    db: AsyncSession,
    data: EmployeeCreate,
    actor_id: uuid.UUID | None = None,
) -> Employee:
    # License cap: when enforcing, refuse to add employees beyond the licensed max.
    cap = license_mod.max_employees()
    if license_mod.enforced() and cap is not None:
        current = (await db.execute(
            select(func.count()).select_from(Employee).where(Employee.deleted_at.is_(None))
        )).scalar_one()
        if current >= cap:
            raise UnprocessableError(
                f"Your license allows a maximum of {cap} employees. "
                "Contact your provider to increase the limit."
            )

    dup = await db.execute(
        select(Employee.id).where(
            or_(
                Employee.email == data.email,
                Employee.employee_code == data.employee_code,
            ),
            Employee.deleted_at.is_(None),
        )
    )
    if dup.scalar_one_or_none():
        raise ConflictError("Employee with this email or code already exists")

    emp = Employee(
        employee_code=data.employee_code,
        first_name=data.first_name,
        last_name=data.last_name,
        email=data.email,
        phone=data.phone,
        password_hash=hash_password(data.password),
        role_id=data.role_id,
        branch_id=data.branch_id,
        department_id=data.department_id,
        shift_id=data.shift_id,
        manager_id=data.manager_id,
        biometric_uid=data.biometric_uid,
        date_of_joining=data.date_of_joining,
        monthly_salary_paise=data.monthly_salary_paise,
        is_active=True,
    )
    db.add(emp)
    try:
        await db.flush()
    except IntegrityError as exc:
        # A unique conflict (email / employee_code / biometric_uid) — surface a clear
        # 409 instead of a 500. With the partial unique indexes this only fires on a
        # genuine clash with an ACTIVE employee.
        await db.rollback()
        raise ConflictError(
            "An employee with this email, code, or biometric UID already exists."
        ) from exc

    # Audit trail — record the creation (never store the password).
    _AUDIT_FIELDS = ("employee_code", "first_name", "last_name", "email", "phone",
                     "role_id", "branch_id", "department_id", "shift_id", "manager_id",
                     "biometric_uid", "date_of_joining", "monthly_salary_paise", "is_active")
    audit = AuditLog(
        table_name="employees",
        record_id=emp.id,
        action=AuditAction.CREATE,
        before_value=None,
        after_value={f: str(getattr(emp, f)) if getattr(emp, f) is not None else None
                     for f in _AUDIT_FIELDS},
        performed_by_id=actor_id,
    )
    db.add(audit)
    await db.flush()

    return await _get_or_404(db, emp.id)


async def update_employee(
    db: AsyncSession,
    employee_id: uuid.UUID,
    data: EmployeeUpdate,
    actor_id: uuid.UUID | None = None,
) -> Employee:
    emp = await _get_or_404(db, employee_id)
    updates = data.model_dump(exclude_unset=True)

    # Pop password before any audit capture or generic setattr — plain text
    # must never appear in audit_logs or be set on the wrong ORM column.
    raw_password = updates.pop("password", None)

    if "email" in updates and updates["email"] != emp.email:
        dup = await db.execute(
            select(Employee.id).where(
                Employee.email == updates["email"],
                Employee.id != employee_id,
                Employee.deleted_at.is_(None),
            )
        )
        if dup.scalar_one_or_none():
            raise ConflictError("Email already used by another employee")

    # Capture before-state for audit log (exclude sensitive fields)
    _AUDIT_FIELDS = ("first_name", "last_name", "email", "phone", "role_id",
                     "branch_id", "department_id", "shift_id", "manager_id",
                     "biometric_uid", "is_active", "date_of_leaving",
                     "monthly_salary_paise")
    before_val = {f: str(getattr(emp, f)) if getattr(emp, f) is not None else None
                  for f in _AUDIT_FIELDS if f in updates}

    for field, value in updates.items():
        setattr(emp, field, value)

    if raw_password:
        emp.password_hash = hash_password(raw_password)

    await db.flush()

    after_val = {f: str(updates[f]) if updates[f] is not None else None
                 for f in _AUDIT_FIELDS if f in updates}
    audit = AuditLog(
        table_name="employees",
        record_id=employee_id,
        action=AuditAction.UPDATE,
        before_value=before_val,
        after_value=after_val,
        performed_by_id=actor_id,
    )
    db.add(audit)
    await db.flush()

    return await _get_or_404(db, employee_id)


async def delete_employee(
    db: AsyncSession,
    employee_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
) -> None:
    emp = await _get_or_404(db, employee_id)
    before_val = {"is_active": str(emp.is_active), "deleted_at": None}
    emp.deleted_at = datetime.now(timezone.utc)
    emp.is_active = False
    await db.flush()

    audit = AuditLog(
        table_name="employees",
        record_id=employee_id,
        action=AuditAction.DELETE,
        before_value=before_val,
        after_value={"is_active": "False", "deleted_at": str(emp.deleted_at)},
        performed_by_id=actor_id,
    )
    db.add(audit)
    await db.flush()


async def update_avatar(
    db: AsyncSession, employee_id: uuid.UUID, avatar_url: str
) -> Employee:
    emp = await _get_or_404(db, employee_id)
    emp.avatar_url = avatar_url
    await db.flush()
    return await _get_or_404(db, employee_id)


async def get_direct_reports(
    db: AsyncSession, employee_id: uuid.UUID
) -> list[Employee]:
    """
    A manager's team = the 'employee'-role staff in the manager's OWN department
    (department-based tracking), excluding the manager themselves. Returns an empty
    list if the manager has no department assigned.
    """
    manager = await _get_or_404(db, employee_id)
    if manager.department_id is None:
        return []
    result = await db.execute(
        select(Employee)
        .where(
            Employee.department_id == manager.department_id,
            Employee.id != manager.id,
            Employee.deleted_at.is_(None),
            Employee.role.has(Role.name == "employee"),
        )
        .options(*_EAGER)
        .order_by(Employee.first_name, Employee.last_name)
    )
    return list(result.scalars().all())


async def get_hierarchy(
    db: AsyncSession, employee_id: uuid.UUID
) -> list[HierarchyNodeOut]:
    """Chain of command upward from employee → root. depth=0 is the employee."""
    await _get_or_404(db, employee_id)

    rows = (
        await db.execute(
            text(
                """
                WITH RECURSIVE chain AS (
                    SELECT e.id, e.first_name, e.last_name, e.manager_id,
                           r.name AS role_name, e.employee_code, 0 AS depth
                    FROM employees e
                    JOIN roles r ON r.id = e.role_id
                    WHERE e.id = :emp_id AND e.deleted_at IS NULL
                    UNION ALL
                    SELECT e.id, e.first_name, e.last_name, e.manager_id,
                           r.name AS role_name, e.employee_code, c.depth + 1
                    FROM employees e
                    JOIN roles r ON r.id = e.role_id
                    JOIN chain c ON e.id = c.manager_id
                    WHERE e.deleted_at IS NULL
                )
                SELECT * FROM chain ORDER BY depth
                """
            ),
            {"emp_id": str(employee_id)},
        )
    ).mappings().all()

    return [
        HierarchyNodeOut(
            id=row["id"],
            employee_code=row["employee_code"],
            first_name=row["first_name"],
            last_name=row["last_name"],
            role_name=row["role_name"],
            depth=row["depth"],
        )
        for row in rows
    ]
