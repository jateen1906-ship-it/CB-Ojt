"""CodeBridge API Gateway FastAPI application factory and entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.clients.http_client import GatewayHTTPClient
from app.clients.service_registry import build_service_registry
from app.config import Settings, load_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.redis_client import GatewayRedisManager
from app.middleware.auth_blacklist import TokenBlacklistMiddleware
from app.middleware.correlation import CorrelationIDMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.routes.health import router as health_router
from app.routes.proxy import build_proxy_router


def create_app(
    settings: Settings | None = None,
    http_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    """Create and configure the standalone CodeBridge API Gateway application."""
    resolved_settings = settings or load_settings()
    configure_logging(level=resolved_settings.LOG_LEVEL, service_name="api-gateway")
    logger = get_logger("main")

    service_registry = build_service_registry(resolved_settings)
    http_client = GatewayHTTPClient(settings=resolved_settings, transport=http_transport)
    redis_manager = GatewayRedisManager(settings=resolved_settings)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        logger.info("Starting CodeBridge API Gateway", extra={"event": "gateway_startup"})
        await http_client.startup()
        await redis_manager.startup()
        try:
            yield
        finally:
            await redis_manager.shutdown()
            await http_client.shutdown()
            logger.info("Stopped CodeBridge API Gateway", extra={"event": "gateway_shutdown"})

    application = FastAPI(
        title=resolved_settings.APP_NAME,
        version=resolved_settings.APP_VERSION,
        debug=resolved_settings.DEBUG,
        lifespan=lifespan,
    )

    application.state.settings = resolved_settings
    application.state.service_registry = service_registry
    application.state.http_client = http_client
    application.state.redis_manager = redis_manager

    register_exception_handlers(application)

    # Middlewares (ordered from inner to outer)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.CORS_ORIGINS if "*" not in resolved_settings.CORS_ORIGINS else ["*"],
        allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2[0-9]|3[0-1])\.\d+\.\d+)(:\d+)?|https://.*\.loca\.lt",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[
            "X-Request-ID",
            "X-Correlation-Id",
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "X-RateLimit-Reset",
            "Retry-After",
        ],
    )
    application.add_middleware(TokenBlacklistMiddleware, redis_manager=redis_manager)
    application.add_middleware(RateLimitMiddleware, redis_manager=redis_manager)
    application.add_middleware(SecurityHeadersMiddleware)
    application.add_middleware(GZipMiddleware, minimum_size=1000)
    application.add_middleware(CorrelationIDMiddleware)

    application.include_router(health_router)
    proxy_router = build_proxy_router(service_registry)
    application.include_router(proxy_router)
    application.include_router(
        proxy_router,
        prefix=resolved_settings.API_V1_PREFIX,
    )
    application.include_router(
        proxy_router,
        prefix=f"{resolved_settings.API_V1_PREFIX}{resolved_settings.API_V1_PREFIX}",
    )

    return application


app = create_app()
