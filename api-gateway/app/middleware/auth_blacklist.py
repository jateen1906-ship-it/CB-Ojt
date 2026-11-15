"""O(1) in-memory revoked JWT token blacklist validation using Redis."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

if TYPE_CHECKING:
    from app.core.redis_client import GatewayRedisManager


class TokenBlacklistMiddleware(BaseHTTPMiddleware):
    """Intercepts requests with revoked JWTs before they reach downstream services."""

    def __init__(self, app, redis_manager: GatewayRedisManager) -> None:
        super().__init__(app)
        self.redis_manager = redis_manager

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not self.redis_manager.is_available:
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
            if token:
                try:
                    # Unverified decode to extract jti without secret coupling
                    unverified = jwt.decode(
                        token,
                        options={"verify_signature": False},
                    )
                    jti = unverified.get("jti")
                    if jti and await self.redis_manager.is_token_blacklisted(jti):
                        return JSONResponse(
                            status_code=401,
                            content={
                                "error": {
                                    "code": "TOKEN_REVOKED",
                                    "message": "This authorization token has been revoked. Please log in again.",
                                }
                            },
                        )
                except Exception:
                    # If token decoding fails, let downstream authentication handle syntax/signature errors
                    pass

        return await call_next(request)
