"""API Gateway routes package."""

from app.routes.health import router as health_router
from app.routes.proxy import build_proxy_router

__all__ = ["build_proxy_router", "health_router"]
