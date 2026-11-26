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
    password: str = Field(..., min_length=4, max_length=128, examples=["StrongPassword123!"])
    role: UserRole = Field(default=UserRole.FREELANCER, examples=[UserRole.FREELANCER])

    @model_validator(mode="before")
    @classmethod
    def _preprocess_fields(cls, data: object) -> object:
        if isinstance(data, dict):
            # Security check: reject privilege-escalation flags (like is_verified, is_admin)
            forbidden_flags = {"is_verified", "is_admin", "is_superuser", "is_staff", "permissions"}
            for flag in forbidden_flags:
                if flag in data:
                    raise ValueError(f"Extra flag field '{flag}' is forbidden.")

            # Support alternative display name / full name fields
            if "full_name" not in data or not str(data["full_name"]).strip():
                for alt_key in ("displayName", "display_name", "fullName", "name", "username"):
                    if alt_key in data and str(data[alt_key]).strip():
                        data["full_name"] = str(data[alt_key]).strip()
                        break

            # Strip benign frontend UI fields so extra="forbid" doesn't reject standard form inputs
            for benign_key in (
                "displayName",
                "display_name",
                "fullName",
                "confirmPassword",
                "confirm_password",
                "confirm",
                "password_confirmation",
                "terms",
                "agreedToTerms",
                "termsAccepted",
                "acceptTerms",
                "step",
                "title",
                "bio",
            ):
                data.pop(benign_key, None)

            # Support and normalize case-insensitive and UI role aliases
            if "role" in data:
                raw_role = str(data["role"]).strip().upper().replace(" ", "_").replace("-", "_").replace("/", "_")
                if raw_role in {"OWNER", "PROJECT_OWNER", "PROJECTOWNER", "CLIENT", "1"}:
                    data["role"] = "OWNER"
                elif raw_role in {"FREELANCER", "DEVELOPER", "FREELANCER_DEVELOPER", "DEV", "TALENT", "2"}:
                    data["role"] = "FREELANCER"
                elif raw_role in {"ADMIN"}:
                    data["role"] = "ADMIN"
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
        # Length-based policy (NIST SP 800-63B), kept in sync with the frontend's
        # lib/password.ts: >= 12 characters and >= 5 distinct characters.
        if len(value) < 12:
            raise ValueError("Password must be at least 12 characters.")
        if len(set(value)) < 5:
            raise ValueError("Password must use at least 5 different characters.")
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
    """Google OAuth ID token verification or auth code exchange payload for Freelancers."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    credential: str | None = Field(
        default=None,
        min_length=10,
        description="Google ID Token issued by Google Identity Services",
    )
    code: str | None = Field(
        default=None,
        min_length=1,
        description="Google OAuth authorization code (for code exchange flow)",
    )
    role: UserRole = Field(
        default=UserRole.FREELANCER,
        description="Role for onboarding: only FREELANCER is permitted for Google authentication",
    )
    redirect_uri: str | None = Field(
        default=None,
        description="Optional redirect URI used in auth code flow",
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
            if "redirectUri" in data and "redirect_uri" not in data:
                data["redirect_uri"] = data["redirectUri"]
        return data

    @model_validator(mode="after")
    def _validate_credential_or_code(self) -> GoogleAuthRequest:
        if not self.credential and not self.code:
            raise ValueError("Either Google 'credential' (ID token) or 'code' (authorization code) must be provided.")
        return self


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


