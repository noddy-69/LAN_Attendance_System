import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.models.device import DeviceType


class DeviceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    device_type: DeviceType
    branch_id: uuid.UUID
    is_entry_camera: bool = True

    # Camera-only
    rtsp_url: str | None = Field(default=None, max_length=1000)

    # Biometric-only
    ip_address: str | None = Field(default=None, max_length=45)
    port: int | None = Field(default=None, ge=1, le=65535)
    serial_number: str | None = Field(default=None, max_length=100)
    device_uid: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def _check_type_fields(self) -> "DeviceCreate":
        if self.device_type == DeviceType.CAMERA and not self.rtsp_url:
            raise ValueError("rtsp_url is required for camera devices")
        if self.device_type == DeviceType.BIOMETRIC and not self.ip_address:
            raise ValueError("ip_address is required for biometric devices")
        return self


class DeviceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    is_active: bool | None = None
    is_entry_camera: bool | None = None
    rtsp_url: str | None = Field(default=None, max_length=1000)
    ip_address: str | None = Field(default=None, max_length=45)
    port: int | None = Field(default=None, ge=1, le=65535)
    serial_number: str | None = Field(default=None, max_length=100)
    device_uid: str | None = Field(default=None, max_length=100)


class DeviceOut(BaseModel):
    id: uuid.UUID
    name: str
    device_type: DeviceType
    branch_id: uuid.UUID
    branch_name: str
    is_entry_camera: bool
    # RTSP URL is masked — password replaced with *** for security
    rtsp_url_masked: str | None
    ip_address: str | None
    port: int | None
    serial_number: str | None
    device_uid: str | None
    is_active: bool
    last_heartbeat: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConnectionTestOut(BaseModel):
    reachable: bool
    message: str
    latency_ms: int | None
