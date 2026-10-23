import uuid

from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds until access token expiry


class EmployeeProfile(BaseModel):
    id: uuid.UUID
    employee_code: str
    first_name: str
    last_name: str
    email: str
    phone: str | None
    role_name: str
    branch_id: uuid.UUID
    branch_name: str | None = None
    department_id: uuid.UUID | None
    department_name: str | None = None
    is_active: bool
    avatar_url: str | None
    permissions: list[str]

    model_config = {"from_attributes": True}
