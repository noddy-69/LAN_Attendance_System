import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_permission
from app.models.device import Device, DeviceType
from app.models.employee import Employee
from app.schemas.common import ApiResponse
from app.schemas.devices import ConnectionTestOut, DeviceCreate, DeviceOut, DeviceUpdate
from app.services import device_service

router = APIRouter(prefix="/devices", tags=["devices"])


def _to_out(device: Device) -> DeviceOut:
    return DeviceOut(
        id=device.id,
        name=device.name,
        device_type=device.device_type,
        branch_id=device.branch_id,
        branch_name=device.branch.name if device.branch else "",
        is_entry_camera=device.is_entry_camera,
        rtsp_url_masked=device_service.masked_rtsp(device),
        ip_address=device.ip_address,
        port=device.port,
        serial_number=device.serial_number,
        device_uid=device.device_uid,
        is_active=device.is_active,
        last_heartbeat=device.last_heartbeat,
        created_at=device.created_at,
        updated_at=device.updated_at,
    )


@router.get("", response_model=ApiResponse[list[DeviceOut]])
async def list_devices(
    device_type: DeviceType | None = Query(default=None),
    branch_id: uuid.UUID | None = Query(default=None),
    per_page: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("devices:read")),
):
    devices, pagination = await device_service.list_devices(
        db,
        device_type=device_type,
        branch_id=branch_id,
        per_page=per_page,
        cursor=cursor,
    )
    return ApiResponse.ok([_to_out(d) for d in devices], pagination)


@router.post("", response_model=ApiResponse[DeviceOut], status_code=201)
async def create_device(
    body: DeviceCreate,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("devices:write")),
):
    device = await device_service.create_device(db, body)
    return ApiResponse.ok(_to_out(device))


@router.get("/{device_id}", response_model=ApiResponse[DeviceOut])
async def get_device(
    device_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("devices:read")),
):
    device = await device_service.get_device(db, device_id)
    return ApiResponse.ok(_to_out(device))


@router.patch("/{device_id}", response_model=ApiResponse[DeviceOut])
async def update_device(
    device_id: uuid.UUID,
    body: DeviceUpdate,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("devices:write")),
):
    device = await device_service.update_device(db, device_id, body)
    return ApiResponse.ok(_to_out(device))


@router.delete("/{device_id}", response_model=ApiResponse[None])
async def delete_device(
    device_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission("devices:write")),
):
    await device_service.delete_device(db, device_id, actor_id=current_user.id)
    return ApiResponse.ok(None)


@router.post("/{device_id}/heartbeat", response_model=ApiResponse[DeviceOut])
async def device_heartbeat(
    device_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    # attendance:write so the face-service machine account can ping without
    # needing the broader devices:write (admin) permission.
    _: Employee = Depends(require_permission("attendance:write")),
):
    """Liveness ping from a capture device (camera/face-service). Updates last_heartbeat."""
    device = await device_service.record_heartbeat(db, device_id)
    return ApiResponse.ok(_to_out(device))


@router.post("/{device_id}/test-connection", response_model=ApiResponse[ConnectionTestOut])
async def test_connection(
    device_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_permission("devices:write")),
):
    result = await device_service.test_connection(db, device_id)
    return ApiResponse.ok(ConnectionTestOut(**result))
