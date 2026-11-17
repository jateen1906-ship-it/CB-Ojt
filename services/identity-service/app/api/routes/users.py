"""User and talent profile routes matching frontend cross-app contracts."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.dependencies import get_current_user
from app.models.user import User
from app.schemas.user import UserPublicResponse

users_router = APIRouter(prefix="/users", tags=["Users"])
talent_router = APIRouter(prefix="/talent", tags=["Talent"])


@users_router.get(
    "/me",
    response_model=UserPublicResponse,
    status_code=status.HTTP_200_OK,
    summary="Get current authenticated user identity",
)
async def get_current_user_me(
    current_user: User = Depends(get_current_user),
) -> UserPublicResponse:
    return UserPublicResponse.model_validate(current_user)


@users_router.get(
    "/me/owner-profile",
    status_code=status.HTTP_200_OK,
    summary="Get owner onboarding profile",
)
async def get_owner_profile(
    current_user: User = Depends(get_current_user),
) -> dict:
    return {
        "profile": {
            "organizationName": current_user.full_name or "",
            "roleTitle": "Owner",
            "timezone": "UTC",
        },
        "onboardingCompleted": True,
    }


@users_router.put(
    "/me/owner-profile",
    status_code=status.HTTP_200_OK,
    summary="Save owner onboarding profile",
)
@users_router.patch(
    "/me/owner-profile",
    status_code=status.HTTP_200_OK,
    summary="Save owner onboarding profile (patch)",
)
async def save_owner_profile(
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    body = await request.json()
    org_name = body.get("organizationName")
    if org_name and not current_user.full_name:
        current_user.full_name = org_name
        await session.commit()
    return {"profile": body, "onboardingCompleted": True}


@talent_router.put(
    "/profiles/me",
    status_code=status.HTTP_200_OK,
    summary="Save freelancer onboarding profile",
)
@talent_router.patch(
    "/profiles/me",
    status_code=status.HTTP_200_OK,
    summary="Save freelancer onboarding profile (patch)",
)
async def save_talent_profile(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict:
    body = await request.json()
    return {
        "profile": {
            **body,
            "githubVerified": bool(body.get("githubUsername")),
            "rating": None,
        },
        "onboardingCompleted": True,
    }
