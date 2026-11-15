"""Authentication request and token pair response schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

from app.models.user import UserRole
from app.schemas.user import UserPublicResponse


class RegisterRequest(BaseModel):
    """Public account registration payload (OWNER or FREELANCER only)."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    full_name: str = Field(..., min_length=1, max_length=120, examples=["Demo User"])
    email: EmailStr = Field(..., examples=["demo@example.com"])
    password: str = Field(..., min_length=6, max_length=128, examples=["StrongPassword123!"])
    role: UserRole = Field(default=UserRole.FREELANCER, examples=[UserRole.FREELANCER])

    @model_validator(mode="before")
    @classmethod
    def _preprocess_fields(cls, data: object) -> object:
        if isinstance(data, dict):
            # Support 'name' or 'username' if 'full_name' is missing
            if "full_name" not in data or not str(data["full_name"]).strip():
                if "name" in data and str(data["name"]).strip():
                    data["full_name"] = data["name"]
                elif "username" in data and str(data["username"]).strip():
                    data["full_name"] = data["username"]
                else:
                    data["full_name"] = "User"
            # Support lowercase roles: 'owner' -> 'OWNER', 'freelancer' -> 'FREELANCER'
            if "role" in data and isinstance(data["role"], str):
                role_upper = data["role"].strip().upper()
                if role_upper in {"OWNER", "FREELANCER"}:
                    data["role"] = role_upper
                else:
                    data["role"] = "FREELANCER"
            elif "role" not in data:
                data["role"] = "FREELANCER"
        return data

    @field_validator("full_name")
    @classmethod
    def _clean_full_name(cls, value: str) -> str:
        cleaned = " ".join(value.strip().split())
        return cleaned if cleaned else "User"

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()


class LoginRequest(BaseModel):
    """User login credentials payload."""

    model_config = ConfigDict(extra="ignore")

    email: EmailStr = Field(..., examples=["demo@example.com"])
    password: str = Field(..., min_length=1, max_length=128, examples=["StrongPassword123!"])

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()


class RefreshTokenRequest(BaseModel):
    """Refresh token rotation request payload."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    refresh_token: str = Field(..., min_length=10, max_length=4096)

    @model_validator(mode="before")
    @classmethod
    def _preprocess_refresh_token(cls, data: object) -> object:
        if isinstance(data, dict):
            if "refresh_token" not in data and "refreshToken" in data:
                data["refresh_token"] = data["refreshToken"]
        return data


class LogoutRequest(BaseModel):
    """Logout payload identifying the refresh token to revoke."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    refresh_token: str = Field(..., min_length=10, max_length=4096)

    @model_validator(mode="before")
    @classmethod
    def _preprocess_logout_token(cls, data: object) -> object:
        if isinstance(data, dict):
            if "refresh_token" not in data and "refreshToken" in data:
                data["refresh_token"] = data["refreshToken"]
        return data


class TokenPairResponse(BaseModel):
    """Signed access and refresh token pair with expiration metadata."""

    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(..., description="Access token lifetime in seconds.")
    refresh_expires_in: int = Field(..., description="Refresh token lifetime in seconds.")
    user: UserPublicResponse

