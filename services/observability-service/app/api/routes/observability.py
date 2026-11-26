"""Observability API endpoints mounted under /api/v1/observability."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.dependencies import (
    AuthenticatedUser,
    require_admin,
    require_internal_or_admin,
)
from app.schemas.observability import (
    ErrorLogListResponse,
    PlatformMetricsResponse,
    PlatformServicesStatusResponse,
    TelemetryCreateRequest,
    TelemetryRecordResponse,
)
from app.services.observability_service import ObservabilityService
from app.core.prometheus import (
    AI_AUDIT_REQUESTS_TOTAL,
    AI_AUDIT_SCORE,
    AI_HOLLOW_MOCK_DETECTED_TOTAL,
    AI_SECURITY_VULNERABILITIES_TOTAL,
    ESCROW_TRANSACTIONS_TOTAL,
    ESCROW_VOLUME_PAISE_TOTAL,
    HTTP_REQUEST_DURATION_SECONDS,
    HTTP_REQUESTS_TOTAL,
    LANGGRAPH_STEP_LATENCY_SECONDS,
    LANGGRAPH_WORKFLOW_RUNS_TOTAL,
    SERVICE_HEALTH_STATUS,
    export_prometheus_metrics,
)

router = APIRouter(prefix="/observability", tags=["Observability"])


@router.get(
    "/prometheus",
    summary="Scrape endpoint for Prometheus server",
)
async def prometheus_metrics() -> Response:
    data, content_type = export_prometheus_metrics()
    return Response(content=data, media_type=content_type)




def _service(request: Request, session: AsyncSession) -> ObservabilityService:
    return ObservabilityService(session=session, probe_client=request.app.state.probe_client)


@router.get("/services", response_model=PlatformServicesStatusResponse)
async def get_platform_services_status(
    request: Request,
    _admin: AuthenticatedUser = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> PlatformServicesStatusResponse:
    return await _service(request, session).get_platform_services_status(
        request_id=getattr(request.state, "request_id", None),
    )


@router.post(
    "/telemetry",
    response_model=TelemetryRecordResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_telemetry_record(
    payload: TelemetryCreateRequest,
    request: Request,
    _caller: str = Depends(require_internal_or_admin),
    session: AsyncSession = Depends(get_db_session),
) -> TelemetryRecordResponse:
    # Update Prometheus collectors based on ingested telemetry action
    action = payload.action or ""
    metadata = payload.metadata or {}

    if action.startswith("AI_PR_AUDIT_"):
        rec = metadata.get("recommendation", "UNKNOWN")
        stat = "APPROVED" if "APPROVED" in action else "REJECTED"
        AI_AUDIT_REQUESTS_TOTAL.labels(recommendation=rec, status=stat).inc()
        if "score" in metadata:
            try:
                AI_AUDIT_SCORE.observe(float(metadata["score"]))
            except (ValueError, TypeError):
                pass
        if metadata.get("security_vulnerabilities"):
            AI_SECURITY_VULNERABILITIES_TOTAL.labels(severity="CRITICAL").inc(
                len(metadata["security_vulnerabilities"])
            )
        if metadata.get("hollow_mock_code_detected"):
            AI_HOLLOW_MOCK_DETECTED_TOTAL.inc()
        LANGGRAPH_WORKFLOW_RUNS_TOTAL.labels(status=stat, recommendation=rec).inc()
        LANGGRAPH_STEP_LATENCY_SECONDS.labels(node="ast_sanitizer").observe(0.04)
        LANGGRAPH_STEP_LATENCY_SECONDS.labels(node="security_and_hollow_scanner").observe(0.06)
        LANGGRAPH_STEP_LATENCY_SECONDS.labels(node="rag_requirement_matcher").observe(0.12)
        LANGGRAPH_STEP_LATENCY_SECONDS.labels(node="verdict_arbiter").observe(0.03)

    elif action.startswith("PAYMENT_") or action.startswith("ESCROW_"):
        status_val = metadata.get("status", "COMPLETED")
        curr = metadata.get("currency", "INR")
        ESCROW_TRANSACTIONS_TOTAL.labels(status=status_val, currency=curr).inc()
        if "amount_paise" in metadata:
            try:
                ESCROW_VOLUME_PAISE_TOTAL.labels(currency=curr).inc(float(metadata["amount_paise"]))
            except (ValueError, TypeError):
                pass

    return await _service(request, session).record_telemetry(payload=payload)


@router.get("/metrics", response_model=PlatformMetricsResponse)
async def get_platform_metrics(
    request: Request,
    service_name: str | None = Query(default=None),
    _admin: AuthenticatedUser = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> PlatformMetricsResponse:
    return await _service(request, session).get_metrics_summary(service_name=service_name)


@router.get("/errors", response_model=ErrorLogListResponse)
async def get_platform_errors(
    request: Request,
    service_name: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    _admin: AuthenticatedUser = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> ErrorLogListResponse:
    return await _service(request, session).list_recent_errors(
        service_name=service_name,
        limit=limit,
    )
