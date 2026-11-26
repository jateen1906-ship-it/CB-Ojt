"""Verification Service API routes mounted under /api/v1/verification."""

from __future__ import annotations

import hashlib
import hmac
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.dependencies import require_authenticated, require_owner_or_admin
from app.core.security import AuthenticatedUser
from app.schemas.verification import (
    CIWorkflowRunResponse,
    CreateVerificationRequest,
    FreelancerVerificationListResponse,
    GitHubWorkflowRunWebhookPayload,
    MyVerifiedWorkListResponse,
    PayRailAutoReleaseCheckRequest,
    PayRailAutoReleaseCheckResponse,
    ProjectVerificationListResponse,
    PublicVerificationResponse,
    RevokeVerificationRequest,
    VerificationCheckResponse,
    VerifiedWorkRecordResponse,
)
from app.services.verification_service import VerificationService

router = APIRouter(prefix="/verification", tags=["Verification"])


def _service(request: Request, session: AsyncSession) -> VerificationService:
    return VerificationService(
        session=session,
        settings=request.app.state.settings,
        project_client=request.app.state.project_client,
        review_client=request.app.state.review_client,
        github_client=request.app.state.github_client,
        telemetry_client=request.app.state.telemetry_client,
    )


@router.post(
    "/records",
    response_model=VerifiedWorkRecordResponse,
    status_code=status.HTTP_201_CREATED,
)
async def issue_verification_record(
    payload: CreateVerificationRequest,
    request: Request,
    actor: AuthenticatedUser = Depends(require_owner_or_admin),
    session: AsyncSession = Depends(get_db_session),
) -> VerifiedWorkRecordResponse:
    service = _service(request, session)
    return await service.issue_record(
        payload=payload,
        actor=actor,
        request_id=getattr(request.state, "request_id", None),
    )


@router.get("/public/{public_verification_id}", response_model=PublicVerificationResponse)
async def public_lookup_verification(
    public_verification_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> PublicVerificationResponse:
    service = _service(request, session)
    return await service.get_public_record(public_verification_id)


@router.get("/me", response_model=MyVerifiedWorkListResponse)
async def list_my_verified_work(
    request: Request,
    user: AuthenticatedUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_db_session),
) -> MyVerifiedWorkListResponse:
    return await _service(request, session).list_my_records(user=user)


@router.get("/freelancers/{freelancer_id}", response_model=FreelancerVerificationListResponse)
async def list_freelancer_verified_work(
    freelancer_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> FreelancerVerificationListResponse:
    return await _service(request, session).list_freelancer_public_records(
        freelancer_id=freelancer_id
    )


@router.get("/projects/{project_id}", response_model=ProjectVerificationListResponse)
async def list_project_verifications(
    project_id: uuid.UUID,
    request: Request,
    user: AuthenticatedUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_db_session),
) -> ProjectVerificationListResponse:
    service = _service(request, session)
    return await service.list_project_records(
        project_id=project_id,
        user=user,
        request_id=getattr(request.state, "request_id", None),
    )


@router.get("/records/{record_id}", response_model=VerifiedWorkRecordResponse)
async def get_verification_record(
    record_id: uuid.UUID,
    request: Request,
    user: AuthenticatedUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_db_session),
) -> VerifiedWorkRecordResponse:
    service = _service(request, session)
    return await service.get_record(record_id=record_id, user=user)


@router.post("/records/{record_id}/verify", response_model=VerificationCheckResponse)
async def verify_record_signature(
    record_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> VerificationCheckResponse:
    service = _service(request, session)
    return await service.verify_record(record_id=record_id)


@router.post("/records/{record_id}/revoke", response_model=VerifiedWorkRecordResponse)
async def revoke_verification_record(
    record_id: uuid.UUID,
    payload: RevokeVerificationRequest,
    request: Request,
    actor: AuthenticatedUser = Depends(require_owner_or_admin),
    session: AsyncSession = Depends(get_db_session),
) -> VerifiedWorkRecordResponse:
    service = _service(request, session)
    return await service.revoke_record(
        record_id=record_id,
        payload=payload,
        actor=actor,
        request_id=getattr(request.state, "request_id", None),
    )


@router.post(
    "/webhooks/github/workflow-run",
    response_model=CIWorkflowRunResponse,
    status_code=status.HTTP_200_OK,
    summary="Receive GitHub Actions workflow_run webhook event with HMAC verification",
)
async def github_workflow_run_webhook(
    request: Request,
    payload: GitHubWorkflowRunWebhookPayload,
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
    session: AsyncSession = Depends(get_db_session),
) -> CIWorkflowRunResponse:
    secret = request.app.state.settings.GITHUB_WEBHOOK_SECRET
    # Validate HMAC signature if header provided or in strict mode
    body_bytes = await request.body()
    if x_hub_signature_256:
        expected_sig = "sha256=" + hmac.new(
            secret.encode("utf-8"),
            body_bytes,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(x_hub_signature_256, expected_sig):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid GitHub webhook signature.",
            )

    service = _service(request, session)
    ci_run = await service.record_github_workflow_run(payload=payload.model_dump())
    return CIWorkflowRunResponse.model_validate(ci_run)


@router.post(
    "/payrail/auto-release-check",
    response_model=PayRailAutoReleaseCheckResponse,
    summary="Evaluate if a milestone qualifies for 5-Day Auto-Release Guard",
)
async def check_payrail_auto_release(
    payload: PayRailAutoReleaseCheckRequest,
    request: Request,
    ai_audit_score: int | None = None,
    ai_recommendation: str | None = None,
    hollow_mock_code_detected: bool = False,
    security_vulnerabilities_count: int = 0,
    session: AsyncSession = Depends(get_db_session),
) -> PayRailAutoReleaseCheckResponse:
    service = _service(request, session)
    return await service.evaluate_payrail_auto_release(
        request_data=payload,
        ai_audit_score=ai_audit_score,
        ai_recommendation=ai_recommendation,
        hollow_mock_code_detected=hollow_mock_code_detected,
        security_vulnerabilities_count=security_vulnerabilities_count,
    )


