from datetime import datetime

from pydantic import BaseModel, Field


class AuthSessionResponse(BaseModel):
    user_id: int
    auth0_sub: str
    email: str | None
    name: str | None
    strava_linked: bool


class UserBase(BaseModel):
    email: str | None = None
    name: str | None = None
    timezone: str | None = None


class UserResponse(UserBase):
    id: int
    auth0_sub: str
    role: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class UserUpdateSelf(BaseModel):
    name: str | None = Field(default=None)
    timezone: str | None = Field(default=None)


class UserUpdateAdmin(UserUpdateSelf):
    email: str | None = Field(default=None)
    role: str | None = Field(default=None)
    is_active: bool | None = Field(default=None)


class UserCreateAdmin(UserBase):
    auth0_sub: str
    role: str = "user"
