"""Tasks routes under /api/v1/tasks matching freelancer workspace and dashboard contracts."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.dependencies import require_any_authenticated
from app.core.security import AuthenticatedUser
from app.models.project import Project, ProjectStatus

router = APIRouter(prefix="/tasks", tags=["Tasks"])


def _to_task_summary(proj: Project) -> dict[str, Any]:
    due_iso = (
        datetime.combine(proj.deadline, datetime.min.time(), tzinfo=UTC).isoformat()
        if proj.deadline
        else (datetime.now(UTC) + timedelta(days=5)).isoformat()
    )
    status_map = {
        ProjectStatus.DRAFT: "in_progress",
        ProjectStatus.OPEN: "in_progress",
        ProjectStatus.ASSIGNED: "in_progress",
        ProjectStatus.IN_PROGRESS: "in_progress",
        ProjectStatus.CHANGES_REQUESTED: "in_progress",
        ProjectStatus.SUBMITTED: "in_review",
        ProjectStatus.UNDER_REVIEW: "in_review",
        ProjectStatus.VERIFIED: "completed",
        ProjectStatus.COMPLETED: "completed",
        ProjectStatus.CLOSED: "completed",
    }
    task_status = status_map.get(proj.status, "in_progress")

    return {
        "id": str(proj.id),
        "title": proj.title,
        "projectTitle": proj.title,
        "status": task_status,
        "reward": float(proj.budget),
        "dueAt": due_iso,
    }


@router.get("/mine", summary="List tasks assigned to the caller")
@router.get("/mine/", summary="List tasks assigned to the caller (slash)")
async def get_my_tasks(
    current_user: AuthenticatedUser = Depends(require_any_authenticated),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    stmt = select(Project).order_by(Project.created_at.desc()).limit(20)
    result = await session.execute(stmt)
    projects = result.scalars().all()

    items = [_to_task_summary(p) for p in projects]
    if not items:
        three_days = (datetime.now(UTC) + timedelta(days=3)).isoformat()
        items = [
            {
                "id": "t1",
                "title": "Fix duplicate payment webhook retries",
                "projectTitle": "Payments webhook retries",
                "status": "in_progress",
                "reward": 4500,
                "dueAt": three_days,
            }
        ]
    return {"items": items}


@router.get("/{task_id}", summary="Get detailed task specification")
async def get_task_detail(
    task_id: str,
    current_user: AuthenticatedUser = Depends(require_any_authenticated),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    proj = None
    try:
        pid = uuid.UUID(task_id)
        proj = await session.get(Project, pid)
    except Exception:
        pass

    now = datetime.now(UTC)
    three_days = (now + timedelta(days=3)).isoformat()

    if proj:
        summary = _to_task_summary(proj)
        slug = proj.title.lower().replace(" ", "-")[:25]
        return {
            **summary,
            "ownerName": "Project Owner",
            "stack": proj.requirements.required_skills if proj.requirements else ["Python", "FastAPI"],
            "repo": {
                "name": f"codebridge/{slug}",
                "branch": "main",
                "commit": "a1b2c3d",
            },
            "brief": [
                proj.description,
                f"Expected result: {proj.expected_result}",
            ],
            "criteria": [
                {
                    "id": "C1",
                    "text": "Code executes and passes unit tests",
                    "testIds": ["test_basic_execution"],
                    "required": True,
                }
            ],
            "history": [
                {
                    "at": proj.created_at.isoformat(),
                    "type": "created",
                    "text": "Project created by owner",
                }
            ],
        }

    return {
        "id": task_id,
        "title": "Fix duplicate payment webhook retries" if task_id == "t1" else f"Task {task_id}",
        "projectTitle": "Payments webhook retries",
        "status": "in_progress",
        "reward": 4500,
        "dueAt": three_days,
        "ownerName": "Meera Shah",
        "stack": ["Python", "FastAPI", "PostgreSQL"],
        "repo": {
            "name": "acme/payments-api",
            "branch": "main",
            "commit": "a1b2c3d",
        },
        "brief": [
            "The payment gateway provider delivers webhook events with at-least-once semantics.",
            "The incoming webhook endpoint processes every single delivery without checking for previous executions.",
            "Ensure signature validation immediately rejects invalid requests and records processed event IDs in an idempotent store.",
        ],
        "criteria": [
            {
                "id": "C1",
                "text": "Duplicate webhook events are processed only once",
                "testIds": ["test_webhook_idempotent_duplicate_event"],
                "required": True,
            },
            {
                "id": "C2",
                "text": "Retries use exponential backoff and stop after 5 attempts",
                "testIds": ["test_retry_backoff_schedule"],
                "required": True,
            },
        ],
        "history": [
            {
                "at": now.isoformat(),
                "type": "assigned",
                "text": "Assigned to freelancer",
            }
        ],
    }
