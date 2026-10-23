import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class PermissionOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None

    model_config = {"from_attributes": True}


class RoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    permission_ids: list[uuid.UUID] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    # None = "don't touch permissions"; [] = "remove all permissions"
    permission_ids: list[uuid.UUID] | None = None


class RoleOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    permissions: list[PermissionOut]
    employee_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
