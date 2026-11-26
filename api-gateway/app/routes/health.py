"""API Gateway self-health and readiness endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

router = APIRouter(tags=["Health"])


@router.get("/health", summary="API Gateway health check")
@router.get("/health/live", summary="Kubernetes liveness probe")
@router.get("/live", summary="Kubernetes liveness probe alias")
async def health_check(request: Request) -> dict:
    """Check the health of the API Gateway process and connected services."""
    settings = request.app.state.settings
    redis_mgr = getattr(request.app.state, "redis_manager", None)
    redis_status = "disabled"
    if redis_mgr and redis_mgr.settings.REDIS_ENABLED:
        redis_status = "connected" if redis_mgr.is_available else "disconnected"

    http_client = getattr(request.app.state, "http_client", None)
    cb_stats = {}
    if http_client and hasattr(http_client, "circuit_breakers"):
        for svc, breaker in http_client.circuit_breakers._breakers.items():
            cb_stats[svc] = breaker.state.value

    return {
        "status": "healthy",
        "service": "api-gateway",
        "version": settings.APP_VERSION,
        "redis": redis_status,
        "circuit_breakers": cb_stats,
    }


@router.get("/ready", summary="API Gateway readiness check")
@router.get("/health/ready", summary="Kubernetes readiness probe")
async def readiness_check(request: Request) -> JSONResponse:
    """Check API Gateway HTTP client readiness."""
    client_open = bool(getattr(request.app.state.http_client, "is_open", False))
    payload = {
        "status": "ready" if client_open else "not_ready",
        "service": "api-gateway",
        "version": request.app.state.settings.APP_VERSION,
    }
    return JSONResponse(
        status_code=status.HTTP_200_OK if client_open else status.HTTP_503_SERVICE_UNAVAILABLE,
        content=payload,
    )
