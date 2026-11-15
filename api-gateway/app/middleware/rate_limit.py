"""Distributed sliding-window rate limiting middleware using Redis."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

if TYPE_CHECKING:
    from app.core.redis_client import GatewayRedisManager


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Protects CodeBridge services against DoS and credential stuffing."""

    def __init__(self, app, redis_manager: GatewayRedisManager) -> None:
        super().__init__(app)
        self.redis_manager = redis_manager

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        settings = self.redis_manager.settings
        path = request.url.path

        # Skip rate limiting on internal health checks and documentation
        if path.startswith("/health") or path in {"/", "/docs", "/openapi.json"}:
            return await call_next(request)

        if not settings.RATE_LIMIT_ENABLED or not self.redis_manager.is_available:
            return await call_next(request)

        # Determine identifier: prefer user auth header token prefix, otherwise IP
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token_snippet = auth_header[7:27]
            identifier = f"user:{token_snippet}"
        else:
            client_ip = request.headers.get("X-Forwarded-For")
            if client_ip:
                client_ip = client_ip.split(",")[0].strip()
            else:
                client_ip = request.client.host if request.client else "unknown"
            identifier = f"ip:{client_ip}"

        # Stricter limit on sensitive authentication routes
        if "/auth/login" in path or "/auth/register" in path:
            limit = settings.AUTH_RATE_LIMIT_PER_MINUTE
            route_id = f"{identifier}:auth"
        else:
            limit = settings.RATE_LIMIT_PER_MINUTE
            route_id = f"{identifier}:general"

        is_limited, current_count, reset_seconds = await self.redis_manager.check_rate_limit(
            identifier=route_id,
            limit=limit,
            window_seconds=60,
        )

        remaining = max(0, limit - current_count)

        if is_limited:
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "RATE_LIMIT_EXCEEDED",
                        "message": "Too many requests. Please wait before retrying.",
                        "retry_after_seconds": reset_seconds,
                    }
                },
                headers={
                    "Retry-After": str(reset_seconds),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset_seconds),
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
