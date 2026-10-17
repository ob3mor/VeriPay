"""Auth request/response schemas (docs/API.md §4)."""

import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    # bcrypt operates on at most 72 bytes (core.security enforces byte length).
    password: str = Field(min_length=8, max_length=72)
    full_name: str = Field(min_length=1, max_length=200)
    organization_name: str = Field(min_length=1, max_length=200)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    role: str
    organization_id: uuid.UUID


class OrganizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str


class RegisterResponse(BaseModel):
    user: UserOut
    organization: OrganizationOut
    access_token: str
    token_type: str = "bearer"


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RefreshResponse(TokenResponse):
    """200 of POST /auth/refresh — a fresh short-lived Bearer token minted
    from the httpOnly session cookie."""


class LogoutResponse(BaseModel):
    """200 of POST /auth/logout — the presented credential (Bearer jti or
    session row) is revoked server-side and the cookies are cleared."""

    status: str = "ok"


class MeResponse(BaseModel):
    user: UserOut
    organization: OrganizationOut
