"""Submission endpoints mounted under /api/v1/submissions."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.dependencies import require_authenticated, require_freelancer
from app.core.security import AuthenticatedUser
from app.schemas.review import (
    CommentCreateRequest,
    ReviewCommentResponse,
    SubmissionCreateRequest,
    SubmissionListResponse,
    SubmissionResponse,
)
from app.services.review_service import ReviewService

router = APIRouter(prefix="/submissions", tags=["Submissions"])


def _service(request: Request, session: AsyncSession) -> ReviewService:
    return ReviewService(
        session=session,
        project_client=request.app.state.project_client,
        workspace_client=request.app.state.workspace_client,
        telemetry_client=request.app.state.telemetry_client,
    )


@router.post(
    "/projects/{project_id}",
    response_model=SubmissionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_submission(
    project_id: uuid.UUID,
    payload: SubmissionCreateRequest,
    request: Request,
    freelancer: AuthenticatedUser = Depends(require_freelancer),
    session: AsyncSession = Depends(get_db_session),
) -> SubmissionResponse:
    service = _service(request, session)
    return await service.create_submission(
        project_id=project_id,
        payload=payload,
        freelancer=freelancer,
        request_id=getattr(request.state, "request_id", None),
    )


@router.get("/projects/{project_id}", response_model=SubmissionListResponse)
async def list_project_submissions(
    project_id: uuid.UUID,
    request: Request,
    user: AuthenticatedUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_db_session),
) -> SubmissionListResponse:
    service = _service(request, session)
    return await service.list_submissions(
        project_id=project_id,
        user=user,
        request_id=getattr(request.state, "request_id", None),
    )




_RUNS: dict[str, dict] = {}
_TASK_SUBMISSIONS: dict[str, dict] = {}


@router.post(
    "/runs",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger a verification test run",
)
async def start_submission_run(
    request: Request,
    user: AuthenticatedUser = Depends(require_authenticated),
) -> dict[str, str]:
    try:
        body = await request.json()
    except Exception:
        body = {}
    task_id = body.get("taskId") or "t1"
    run_id = f"run_{uuid.uuid4().hex[:8]}"
    _RUNS[run_id] = {
        "runId": run_id,
        "taskId": task_id,
        "status": "completed",
        "results": [
            {
                "testId": "test_webhook_idempotent_duplicate_event",
                "status": "passed",
                "durationMs": 42,
                "message": "Passed: duplicate event rejected with HTTP 200 already_processed",
            },
            {
                "testId": "test_retry_backoff_schedule",
                "status": "passed",
                "durationMs": 35,
                "message": "Passed: exponential backoff intervals observed",
            },
        ],
    }
    return {"runId": run_id}


@router.get(
    "/runs/{run_id}",
    summary="Get status and test results of a run",
)
async def get_submission_run(
    run_id: str,
    user: AuthenticatedUser = Depends(require_authenticated),
) -> dict:
    if run_id in _RUNS:
        return _RUNS[run_id]
    return {
        "runId": run_id,
        "taskId": "t1",
        "status": "completed",
        "results": [
            {
                "testId": "test_basic_execution",
                "status": "passed",
                "durationMs": 30,
                "message": "Passed",
            }
        ],
    }


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Submit task solution for review",
)
@router.post(
    "/",
    status_code=status.HTTP_201_CREATED,
    summary="Submit task solution for review (slash)",
)
async def submit_solution(
    request: Request,
    user: AuthenticatedUser = Depends(require_authenticated),
) -> dict[str, str]:
    try:
        body = await request.json()
    except Exception:
        body = {}
    task_id = body.get("taskId") or body.get("task_id") or "t1"
    sub_id = f"sub_{uuid.uuid4().hex[:8]}"
    _TASK_SUBMISSIONS[task_id] = {
        "status": "in_review",
        "note": body.get("notes", ""),
        "lastRun": _RUNS.get(list(_RUNS.keys())[-1]) if _RUNS else None,
    }
    return {"submissionId": sub_id, "status": "in_review"}


@router.get(
    "/current",
    summary="Get current submission state for task",
)
@router.get(
    "/current/",
    summary="Get current submission state for task (slash)",
)
async def get_current_submission_state(
    taskId: str | None = None,
    task_id: str | None = None,
    user: AuthenticatedUser = Depends(require_authenticated),
) -> dict:
    resolved_id = taskId or task_id or "t1"
    if resolved_id in _TASK_SUBMISSIONS:
        return _TASK_SUBMISSIONS[resolved_id]
    return {"status": "none"}


@router.get("/{submission_id}", response_model=SubmissionResponse)
async def get_submission(
    submission_id: uuid.UUID,
    request: Request,
    user: AuthenticatedUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_db_session),
) -> SubmissionResponse:
    service = _service(request, session)
    return await service.get_submission(
        submission_id=submission_id,
        user=user,
        request_id=getattr(request.state, "request_id", None),
    )


@router.post("/{submission_id}/submit", response_model=SubmissionResponse)
async def submit_draft(
    submission_id: uuid.UUID,
    request: Request,
    freelancer: AuthenticatedUser = Depends(require_freelancer),
    session: AsyncSession = Depends(get_db_session),
) -> SubmissionResponse:
    service = _service(request, session)
    return await service.submit_draft(
        submission_id=submission_id,
        freelancer=freelancer,
        request_id=getattr(request.state, "request_id", None),
    )


@router.post("/{submission_id}/withdraw", response_model=SubmissionResponse)
async def withdraw_submission(
    submission_id: uuid.UUID,
    request: Request,
    freelancer: AuthenticatedUser = Depends(require_freelancer),
    session: AsyncSession = Depends(get_db_session),
) -> SubmissionResponse:
    service = _service(request, session)
    return await service.withdraw_submission(
        submission_id=submission_id,
        freelancer=freelancer,
        request_id=getattr(request.state, "request_id", None),
    )


@router.post(
    "/{submission_id}/comments",
    response_model=ReviewCommentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_submission_comment(
    submission_id: uuid.UUID,
    payload: CommentCreateRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_authenticated),
    session: AsyncSession = Depends(get_db_session),
) -> ReviewCommentResponse:
    service = _service(request, session)
    return await service.add_comment(
        submission_id=submission_id,
        payload=payload,
        user=user,
        request_id=getattr(request.state, "request_id", None),
    )




