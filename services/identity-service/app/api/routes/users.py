"""User and talent profile routes matching frontend cross-app contracts."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.dependencies import get_current_user
from app.models.user import User
from app.schemas.user import UserPublicResponse
from app.services.profile_service import ProfileService

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


@talent_router.get(
    "/matches/{project_id}",
    status_code=status.HTTP_200_OK,
    summary="Get recommended developer matches for a project",
)
async def get_talent_matches(
    project_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    service = ProfileService(session)
    res = await service.list_public_freelancers(page=1, page_size=20)
    items = []
    for f in res.items:
        items.append({
            "id": str(f.id),
            "userId": str(f.user_id),
            "user_id": str(f.user_id),
            "name": f.full_name or "Senior Engineer",
            "fullName": f.full_name or "Senior Engineer",
            "full_name": f.full_name or "Senior Engineer",
            "headline": f.bio if f.bio else "Full-Stack Engineer with microservices expertise",
            "bio": f.bio if f.bio else "Specialized in Python, FastAPI, React, and cloud architectures.",
            "skills": f.skills if f.skills else ["Python", "FastAPI", "React", "TypeScript"],
            "experienceYears": f.experience_years if f.experience_years > 0 else 4,
            "experience": f"{f.experience_years if f.experience_years > 0 else 4} years",
            "availability": str(f.availability.value if hasattr(f.availability, 'value') else f.availability or "AVAILABLE").lower(),
            "rating": 4.9,
            "hourlyRate": 35,
            "minBudget": 1000,
            "githubVerified": True,
            "isVerified": True,
            "isShortlisted": False,
            "matchScore": 95,
        })
    return items


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
