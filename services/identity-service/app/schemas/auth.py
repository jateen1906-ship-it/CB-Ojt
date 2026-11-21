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

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    full_name: str = Field(..., min_length=2, max_length=120, examples=["Demo User"])
    email: EmailStr = Field(..., examples=["demo@example.com"])
    password: str = Field(..., min_length=8, max_length=128, examples=["StrongPassword123!"])
    role: UserRole = Field(default=UserRole.FREELANCER, examples=[UserRole.FREELANCER])

    @model_validator(mode="before")
    @classmethod
    def _preprocess_fields(cls, data: object) -> object:
        if isinstance(data, dict):
            # Support 'displayName', 'name' or 'username' if 'full_name' is missing
            if "full_name" not in data or not str(data["full_name"]).strip():
                if "displayName" in data and str(data["displayName"]).strip():
                    data["full_name"] = data["displayName"]
                elif "name" in data and str(data["name"]).strip():
                    data["full_name"] = data["name"]
                elif "username" in data and str(data["username"]).strip():
                    data["full_name"] = data["username"]
            # Support case-insensitive role string
            if "role" in data and isinstance(data["role"], str):
                role_upper = data["role"].strip().upper()
                if role_upper in {"OWNER", "FREELANCER", "ADMIN"}:
                    data["role"] = role_upper
        return data

    @field_validator("full_name")
    @classmethod
    def _clean_full_name(cls, value: str) -> str:
        cleaned = " ".join(value.strip().split())
        if len(cleaned) < 2:
            raise ValueError("full_name must contain at least 2 non-space characters.")
        return cleaned

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()

    @field_validator("password")
    @classmethod
    def _validate_password_strength(cls, value: str) -> str:
        has_upper = any(ch.isupper() for ch in value)
        has_lower = any(ch.islower() for ch in value)
        has_digit = any(ch.isdigit() for ch in value)
        has_special = any(not ch.isalnum() for ch in value)
        if not (has_upper and has_lower and has_digit and has_special):
            raise ValueError(
                "Password must contain uppercase, lowercase, numeric, and special characters."
            )
        return value


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

    refresh_token: str | None = Field(default=None, min_length=10, max_length=4096)

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

    refresh_token: str | None = Field(default=None, min_length=10, max_length=4096)

    @model_validator(mode="before")
    @classmethod
    def _preprocess_logout_token(cls, data: object) -> object:
        if isinstance(data, dict):
            if "refresh_token" not in data and "refreshToken" in data:
                data["refresh_token"] = data["refreshToken"]
        return data


class TokenPairResponse(BaseModel):
    """Signed access and refresh token pair with expiration metadata."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(..., description="Access token lifetime in seconds.")
    refresh_expires_in: int = Field(..., description="Refresh token lifetime in seconds.")
    user: UserPublicResponse
    accessToken: str | None = None
    refreshToken: str | None = None
    expiresIn: int | None = None

    @model_validator(mode="after")
    def _fill_frontend_aliases(self) -> TokenPairResponse:
        self.accessToken = self.access_token
        self.refreshToken = self.refresh_token
        self.expiresIn = self.expires_in
        return self


class GoogleAuthRequest(BaseModel):
    """Google OAuth ID token verification payload for Freelancers."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    credential: str = Field(..., min_length=10, description="Google ID Token issued by Google Identity Services")
    role: UserRole = Field(
        default=UserRole.FREELANCER,
        description="Role for onboarding: only FREELANCER is permitted for Google authentication",
    )

    @model_validator(mode="before")
    @classmethod
    def _preprocess(cls, data: object) -> object:
        if isinstance(data, dict):
            if "id_token" in data and "credential" not in data:
                data["credential"] = data["id_token"]
            if "role" in data and isinstance(data["role"], str):
                role_upper = data["role"].strip().upper()
                if role_upper in {"OWNER", "FREELANCER", "ADMIN"}:
                    data["role"] = role_upper
        return data


class GitHubAuthRequest(BaseModel):
    """GitHub OAuth authorization code payload for Owners and Freelancers."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    code: str = Field(..., min_length=1, description="GitHub OAuth authorization code")
    role: UserRole = Field(
        default=UserRole.OWNER,
        description="Role for onboarding: OWNER or FREELANCER",
    )
    redirect_uri: str | None = Field(
        default=None,
        description="Optional redirect URI matching client OAuth initiation",
    )

    @model_validator(mode="before")
    @classmethod
    def _preprocess(cls, data: object) -> object:
        if isinstance(data, dict):
            if "redirectUri" in data and "redirect_uri" not in data:
                data["redirect_uri"] = data["redirectUri"]
            if "role" in data and isinstance(data["role"], str):
                role_upper = data["role"].strip().upper()
                if role_upper in {"OWNER", "FREELANCER", "ADMIN"}:
                    data["role"] = role_upper
        return data


