"""AI Context endpoint matching the Developer Workspace frontend contract."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, status

from app.core.dependencies import AuthContext, require_any_authenticated
from app.schemas.ai_audit import AuditPRRequest, AuditReportCard

router = APIRouter(prefix="/ai", tags=["AI Context"])


@router.get("/context/{task_id}", summary="Get AI context and findings for task")
async def get_ai_context(
    task_id: str,
    auth_ctx: AuthContext = Depends(require_any_authenticated),
) -> dict[str, Any]:
    return {
        "summary": (
            "The webhook ingestion service fails to de-duplicate incoming requests, "
            "leading to multiple ledger debits during partner network retries. "
            "Furthermore, signature verification errors trigger HTTP 500 internal server responses "
            "rather than HTTP 400 client rejections, perpetuating upstream retry storms. "
            "The backoff calculation in app/retry.py is also hardcoded to a static delay."
        ),
        "findings": [
            "Missing idempotent event cache: app/webhooks.py executes record_payment_charge without verifying prior event IDs.",
            "Unhandled exception on invalid HMAC signature raises an HTTP 500 instead of HTTP 400 Bad Request.",
            "Retry scheduler lacks exponential backoff and does not terminate after the mandated 5 attempts.",
        ],
        "relevantFiles": [
            {
                "path": "app/webhooks.py",
                "score": 0.94,
                "reason": "Handler has no de-duplication and answers a bad signature with 500",
            },
            {
                "path": "app/retry.py",
                "score": 0.88,
                "reason": "Constant delay and no attempt limit",
            },
            {
                "path": "app/main.py",
                "score": 0.65,
                "reason": "Webhook ingress route definition",
            },
            {
                "path": "README.md",
                "score": 0.45,
                "reason": "Architecture documentation",
            },
        ],
        "approach": [
            "1. Add an in-memory set or Redis-compatible store in app/webhooks.py to discard already processed event IDs.",
            "2. Change the HTTPException in app/webhooks.py for signature mismatch from 500 to 400.",
            "3. In app/retry.py, implement exponential delay 2 ** attempt and enforce MAX_ATTEMPTS = 5.",
            "4. Verify health and test suites pass completely.",
        ],
    }


@router.post(
    "/audit-pr",
    response_model=AuditReportCard,
    status_code=status.HTTP_200_OK,
    summary="Forensic AI audit of Git PR diff against PRD requirements",
)
async def audit_pr(
    payload: AuditPRRequest,
    request: Request,
    auth_ctx: AuthContext = Depends(require_any_authenticated),
) -> AuditReportCard:
    """Evaluate a PR solution using dual-channel AST sanitization and forensic verification."""
    audit_service = getattr(request.app.state, "pr_audit_service", None)
    if audit_service is None:
        from app.services.pr_audit_service import PRAuditService
        audit_service = PRAuditService(request.app.state.settings)
    return await audit_service.audit_pr(payload)

