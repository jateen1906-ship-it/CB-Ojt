"""Authentication service handling registration, login, token refresh, and logout."""

from __future__ import annotations

import secrets
import uuid

import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import (
    EmailAlreadyExistsError,
    ForbiddenError,
    InvalidCredentialsError,
)
from app.core.logging import get_logger
from app.core.security import get_dummy_password_hash, hash_password, verify_password
from app.models.user import User, UserRole
from app.repositories.profile_repository import ProfileRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import (
    GitHubAuthRequest,
    GoogleAuthRequest,
    LoginRequest,
    RegisterRequest,
    TokenPairResponse,
)
from app.services.token_service import TokenService

logger = get_logger("services.auth")


class AuthService:
    """Orchestrates public registration, credential login, refresh rotation, and logout."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.user_repo = UserRepository(session)
        self.profile_repo = ProfileRepository(session)
        self.token_service = TokenService(session, settings)

    async def register(self, payload: RegisterRequest) -> User:
        """Register an OWNER or FREELANCER account (never ADMIN)."""
        if payload.role == UserRole.ADMIN:
            raise ForbiddenError("Public registration may only create OWNER or FREELANCER accounts.")

        existing = await self.user_repo.get_by_email(payload.email)
        if existing is not None:
            raise EmailAlreadyExistsError()

        password_digest = hash_password(payload.password)

        try:
            user = await self.user_repo.create_user(
                full_name=payload.full_name,
                email=payload.email,
                password_hash=password_digest,
                role=payload.role,
                is_active=True,
                is_verified=False,
            )
            if payload.role == UserRole.FREELANCER:
                await self.profile_repo.create_profile(user_id=user.id)
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise EmailAlreadyExistsError() from exc

        logger.info(
            "User registered",
            extra={
                "event": "user_registered",
                "user_id": str(user.id),
                "role": user.role.value,
            },
        )
        return user

    async def login(self, payload: LoginRequest) -> TokenPairResponse:
        """Authenticate email/password credentials and return signed access + refresh tokens."""
        user = await self.user_repo.get_by_email(payload.email)
        if user is None:
            verify_password(payload.password, get_dummy_password_hash())
            raise InvalidCredentialsError()

        if not verify_password(payload.password, user.password_hash):
            raise InvalidCredentialsError()

        if not user.is_active:
            raise ForbiddenError("User account is inactive.")

        token_pair, _ = await self.token_service.issue_token_pair(user=user, commit=True)
        logger.info(
            "User logged in",
            extra={
                "event": "user_login",
                "user_id": str(user.id),
                "role": user.role.value,
            },
        )
        return token_pair

    async def refresh(self, refresh_token: str) -> TokenPairResponse:
        """Rotate refresh token and return fresh access + refresh token pair."""
        return await self.token_service.rotate_refresh_token(refresh_token)

    async def logout(self, *, refresh_token: str, authenticated_user_id: uuid.UUID) -> None:
        """Revoke the user's refresh token session."""
        await self.token_service.revoke_refresh_token(
            refresh_token=refresh_token,
            authenticated_user_id=authenticated_user_id,
        )

    async def login_or_register_google(self, payload: GoogleAuthRequest) -> TokenPairResponse:
        """Authenticate or register a freelancer via verified Google OAuth ID Token."""
        if payload.role == UserRole.OWNER:
            raise ForbiddenError(
                "Project owners must authenticate using GitHub. Google authentication is not permitted for developer/owner accounts."
            )
        if payload.role == UserRole.ADMIN:
            raise ForbiddenError("Admin accounts cannot authenticate via public OAuth.")

        email: str
        full_name: str

        if self.settings.APP_ENV == "test" and (
            (payload.credential and payload.credential.startswith("mock-google-token:"))
            or (payload.code and payload.code.startswith("mock-google-code:"))
        ):
            raw = payload.credential if payload.credential else (payload.code or "")
            parts = raw.split(":")
            email = parts[1].strip().lower()
            full_name = parts[2].strip() if len(parts) > 2 else "Google Freelancer"
        elif payload.code and not payload.credential:
            client_id = self.settings.GOOGLE_CLIENT_ID or ""
            client_secret = (
                self.settings.GOOGLE_CLIENT_SECRET.get_secret_value()
                if self.settings.GOOGLE_CLIENT_SECRET
                else ""
            )
            token_params = {
                "code": payload.code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": payload.redirect_uri or "postmessage",
                "grant_type": "authorization_code",
            }
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(
                        "https://oauth2.googleapis.com/token",
                        data=token_params,
                    )
                    if resp.status_code != 200:
                        logger.warning("Google token endpoint rejected code with status %d: %s", resp.status_code, resp.text)
                        raise InvalidCredentialsError("Failed to exchange Google authorization code.")

                    token_res = resp.json()
                    access_token_val = token_res.get("access_token")
                    if not access_token_val:
                        raise InvalidCredentialsError("Google token exchange did not return an access token.")

                    userinfo_resp = await client.get(
                        "https://www.googleapis.com/oauth2/v3/userinfo",
                        headers={"Authorization": f"Bearer {access_token_val}"},
                    )
                    if userinfo_resp.status_code != 200:
                        raise InvalidCredentialsError("Failed to fetch Google user profile.")
                    google_info = userinfo_resp.json()
            except httpx.RequestError as exc:
                logger.error("Failed to reach Google token endpoint", exc_info=exc)
                raise InvalidCredentialsError(
                    "Unable to reach Google OAuth services. Please try again."
                ) from exc

            raw_email = google_info.get("email")
            if not raw_email or not isinstance(raw_email, str):
                raise InvalidCredentialsError("Google credential does not contain an email address.")
            email = raw_email.strip().lower()

            email_verified = google_info.get("email_verified")
            if email_verified not in (True, "true", "True", 1, "1"):
                raise ForbiddenError("Your Google account email address must be verified.")

            full_name = (
                google_info.get("name")
                or google_info.get("given_name")
                or email.split("@")[0]
            )
        else:
            credential_val = payload.credential or ""
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        "https://oauth2.googleapis.com/tokeninfo",
                        params={"id_token": credential_val},
                    )
            except httpx.RequestError as exc:
                logger.error("Failed to reach Google tokeninfo endpoint", exc_info=exc)
                raise InvalidCredentialsError(
                    "Unable to verify Google credentials with upstream provider. Please try again."
                ) from exc

            if resp.status_code != 200:
                logger.warning("Google tokeninfo rejected token with status %d", resp.status_code)
                raise InvalidCredentialsError("Invalid or expired Google credential.")

            google_info = resp.json()
            raw_email = google_info.get("email")
            if not raw_email or not isinstance(raw_email, str):
                raise InvalidCredentialsError("Google credential does not contain an email address.")
            email = raw_email.strip().lower()

            email_verified = google_info.get("email_verified")
            if email_verified not in (True, "true", "True", 1, "1"):
                raise ForbiddenError("Your Google account email address must be verified.")

            if self.settings.GOOGLE_CLIENT_ID:
                aud = google_info.get("aud")
                if aud != self.settings.GOOGLE_CLIENT_ID:
                    raise InvalidCredentialsError(
                        "Google credential was issued for a different client ID."
                    )

            full_name = (
                google_info.get("name")
                or google_info.get("given_name")
                or email.split("@")[0]
            )

        # Lookup or register user
        user = await self.user_repo.get_by_email(email)
        if user is not None:
            if user.role == UserRole.OWNER:
                raise ForbiddenError(
                    "This account is registered as a Project Owner. Project owners must authenticate using GitHub."
                )
            if not user.is_active:
                raise ForbiddenError("User account is inactive.")
        else:
            random_pw = secrets.token_urlsafe(32)
            password_digest = hash_password(random_pw)
            try:
                user = await self.user_repo.create_user(
                    full_name=full_name,
                    email=email,
                    password_hash=password_digest,
                    role=UserRole.FREELANCER,
                    is_active=True,
                    is_verified=True,
                )
                await self.profile_repo.create_profile(user_id=user.id)
                await self.session.commit()
            except IntegrityError as exc:
                await self.session.rollback()
                user = await self.user_repo.get_by_email(email)
                if user is None:
                    raise EmailAlreadyExistsError() from exc

        token_pair, _ = await self.token_service.issue_token_pair(user=user, commit=True)
        logger.info(
            "User authenticated via Google",
            extra={
                "event": "user_google_auth",
                "user_id": str(user.id),
                "role": user.role.value,
            },
        )
        return token_pair

    async def login_or_register_github(self, payload: GitHubAuthRequest) -> TokenPairResponse:
        """Authenticate or register an OWNER or FREELANCER via GitHub OAuth authorization code."""
        if payload.role == UserRole.ADMIN:
            raise ForbiddenError("Admin accounts cannot authenticate via public OAuth.")

        email: str
        full_name: str

        if self.settings.APP_ENV == "test" and payload.code.startswith("mock-github-code:"):
            parts = payload.code.split(":")
            email = parts[1].strip().lower()
            full_name = parts[2].strip() if len(parts) > 2 else "GitHub User"
        else:
            client_id = self.settings.GITHUB_CLIENT_ID or ""
            client_secret = (
                self.settings.GITHUB_CLIENT_SECRET.get_secret_value()
                if self.settings.GITHUB_CLIENT_SECRET
                else ""
            )

            token_data: dict[str, str] = {
                "client_id": client_id,
                "client_secret": client_secret,
                "code": payload.code,
            }
            if payload.redirect_uri:
                token_data["redirect_uri"] = payload.redirect_uri

            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    token_resp = await client.post(
                        "https://github.com/login/oauth/access_token",
                        json=token_data,
                        headers={"Accept": "application/json"},
                    )
                    if token_resp.status_code != 200:
                        raise InvalidCredentialsError(
                            "GitHub OAuth code exchange failed with upstream provider."
                        )

                    exchange_result = token_resp.json()
                    if "error" in exchange_result:
                        err_desc = exchange_result.get(
                            "error_description", exchange_result["error"]
                        )
                        raise InvalidCredentialsError(f"GitHub OAuth error: {err_desc}")

                    github_access_token = exchange_result.get("access_token")
                    if not github_access_token:
                        raise InvalidCredentialsError(
                            "GitHub response did not contain an access token."
                        )

                    gh_headers = {
                        "Authorization": f"Bearer {github_access_token}",
                        "User-Agent": "CodeBridge-Identity/1.0",
                        "Accept": "application/vnd.github+json",
                    }

                    user_resp = await client.get(
                        "https://api.github.com/user",
                        headers=gh_headers,
                    )
                    if user_resp.status_code != 200:
                        raise InvalidCredentialsError("Failed to fetch GitHub user profile.")
                    gh_user = user_resp.json()

                    # Fetch emails to get primary verified email
                    email_resp = await client.get(
                        "https://api.github.com/user/emails",
                        headers=gh_headers,
                    )
                    found_email: str | None = None
                    if email_resp.status_code == 200:
                        emails_list = email_resp.json()
                        if isinstance(emails_list, list):
                            for em in emails_list:
                                if isinstance(em, dict) and em.get("primary") and em.get("verified"):
                                    found_email = em.get("email")
                                    break
                            if not found_email:
                                for em in emails_list:
                                    if isinstance(em, dict) and em.get("verified"):
                                        found_email = em.get("email")
                                        break

                    if not found_email:
                        found_email = gh_user.get("email")

                    if not found_email:
                        raise ForbiddenError(
                            "Your GitHub account must have a verified email address to authenticate."
                        )

                    email = found_email.strip().lower()
                    full_name = gh_user.get("name") or gh_user.get("login") or email.split("@")[0]
            except httpx.RequestError as exc:
                logger.error("Failed to connect to GitHub APIs", exc_info=exc)
                raise InvalidCredentialsError(
                    "Unable to communicate with GitHub. Please try again."
                ) from exc

        # Lookup or register user
        user = await self.user_repo.get_by_email(email)
        if user is not None:
            if not user.is_active:
                raise ForbiddenError("User account is inactive.")
        else:
            target_role = (
                payload.role
                if payload.role in {UserRole.OWNER, UserRole.FREELANCER}
                else UserRole.OWNER
            )
            random_pw = secrets.token_urlsafe(32)
            password_digest = hash_password(random_pw)
            try:
                user = await self.user_repo.create_user(
                    full_name=full_name,
                    email=email,
                    password_hash=password_digest,
                    role=target_role,
                    is_active=True,
                    is_verified=True,
                )
                if target_role == UserRole.FREELANCER:
                    await self.profile_repo.create_profile(user_id=user.id)
                await self.session.commit()
            except IntegrityError as exc:
                await self.session.rollback()
                user = await self.user_repo.get_by_email(email)
                if user is None:
                    raise EmailAlreadyExistsError() from exc

        token_pair, _ = await self.token_service.issue_token_pair(user=user, commit=True)
        logger.info(
            "User authenticated via GitHub",
            extra={
                "event": "user_github_auth",
                "user_id": str(user.id),
                "role": user.role.value,
            },
        )
        return token_pair


