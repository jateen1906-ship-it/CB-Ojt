"""Unit and integration tests for Google and GitHub OAuth authentication flows."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.models.freelancer_profile import FreelancerProfile
from app.models.user import User, UserRole


@pytest.mark.asyncio
async def test_google_auth_freelancer_success(
    client: httpx.AsyncClient,
    identity_app: FastAPI,
) -> None:
    """Test successful freelancer onboarding/login via Google OAuth."""
    response = await client.post(
        "/api/v1/auth/google",
        json={
            "credential": "mock-google-token:googlefreelancer@example.com:Google Freelancer",
            "role": "FREELANCER",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["user"]["email"] == "googlefreelancer@example.com"
    assert data["user"]["role"] == "FREELANCER"
    assert data["user"]["is_verified"] is True

    # Verify user and FreelancerProfile exist in database
    async with identity_app.state.session_factory() as session:
        user = (
            await session.execute(
                select(User).where(User.email == "googlefreelancer@example.com")
            )
        ).scalar_one_or_none()
        assert user is not None
        assert user.role == UserRole.FREELANCER
        assert user.is_verified is True

        profile = (
            await session.execute(
                select(FreelancerProfile).where(FreelancerProfile.user_id == user.id)
            )
        ).scalar_one_or_none()
        assert profile is not None


@pytest.mark.asyncio
async def test_google_auth_rejects_owner_role(
    client: httpx.AsyncClient,
) -> None:
    """Project owners must use GitHub; Google auth is strictly rejected for OWNER role."""
    response = await client.post(
        "/api/v1/auth/google",
        json={
            "credential": "mock-google-token:owner@example.com:Project Owner",
            "role": "OWNER",
        },
    )
    assert response.status_code == 403
    err = response.json()
    assert err["success"] is False
    assert err["error"]["code"] == "FORBIDDEN"
    assert "Project owners must authenticate using GitHub" in err["error"]["message"]


@pytest.mark.asyncio
async def test_google_auth_rejects_existing_owner_account(
    client: httpx.AsyncClient,
) -> None:
    """If an account was already registered as OWNER, it cannot authenticate via Google."""
    # First, register an owner via GitHub
    gh_res = await client.post(
        "/api/v1/auth/github",
        json={
            "code": "mock-github-code:existingowner@example.com:Existing Owner",
            "role": "OWNER",
        },
    )
    assert gh_res.status_code == 200

    # Attempt to sign into the owner account using Google
    google_res = await client.post(
        "/api/v1/auth/google",
        json={
            "credential": "mock-google-token:existingowner@example.com:Existing Owner",
            "role": "FREELANCER",
        },
    )
    assert google_res.status_code == 403
    err = google_res.json()
    assert "Project owners must authenticate using GitHub" in err["error"]["message"]


@pytest.mark.asyncio
async def test_google_auth_rejects_admin_role(
    client: httpx.AsyncClient,
) -> None:
    """Admin accounts cannot onboard via public OAuth."""
    response = await client.post(
        "/api/v1/auth/google",
        json={
            "credential": "mock-google-token:admin@example.com:Admin",
            "role": "ADMIN",
        },
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_github_auth_owner_success(
    client: httpx.AsyncClient,
    identity_app: FastAPI,
) -> None:
    """Test successful developer/owner onboarding via GitHub OAuth."""
    response = await client.post(
        "/api/v1/auth/github",
        json={
            "code": "mock-github-code:devowner@example.com:Dev Owner",
            "role": "OWNER",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["user"]["email"] == "devowner@example.com"
    assert data["user"]["role"] == "OWNER"
    assert data["user"]["is_verified"] is True

    async with identity_app.state.session_factory() as session:
        user = (
            await session.execute(
                select(User).where(User.email == "devowner@example.com")
            )
        ).scalar_one_or_none()
        assert user is not None
        assert user.role == UserRole.OWNER


@pytest.mark.asyncio
async def test_github_auth_freelancer_success(
    client: httpx.AsyncClient,
    identity_app: FastAPI,
) -> None:
    """Freelancers can also connect and sign in with GitHub."""
    response = await client.post(
        "/api/v1/auth/github",
        json={
            "code": "mock-github-code:ghfreelancer@example.com:GH Freelancer",
            "role": "FREELANCER",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["user"]["email"] == "ghfreelancer@example.com"
    assert data["user"]["role"] == "FREELANCER"

    async with identity_app.state.session_factory() as session:
        profile = (
            await session.execute(
                select(FreelancerProfile).join(User).where(User.email == "ghfreelancer@example.com")
            )
        ).scalar_one_or_none()
        assert profile is not None


@pytest.mark.asyncio
async def test_github_auth_existing_user_login(
    client: httpx.AsyncClient,
) -> None:
    """Logging in multiple times with GitHub returns fresh tokens without duplication."""
    res1 = await client.post(
        "/api/v1/auth/github",
        json={
            "code": "mock-github-code:repeat@example.com:Repeat Dev",
            "role": "OWNER",
        },
    )
    assert res1.status_code == 200
    u1_id = res1.json()["user"]["id"]

    res2 = await client.post(
        "/api/v1/auth/github",
        json={
            "code": "mock-github-code:repeat@example.com:Repeat Dev",
            "role": "OWNER",
        },
    )
    assert res2.status_code == 200
    assert res2.json()["user"]["id"] == u1_id


@pytest.mark.asyncio
async def test_github_auth_rejects_admin_role(
    client: httpx.AsyncClient,
) -> None:
    """Public GitHub OAuth cannot provision ADMIN accounts."""
    response = await client.post(
        "/api/v1/auth/github",
        json={
            "code": "mock-github-code:attacker@example.com:Attacker",
            "role": "ADMIN",
        },
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
