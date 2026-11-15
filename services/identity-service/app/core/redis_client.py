"""Asynchronous Redis client for Identity Service session blacklisting and caching."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import redis.asyncio as aioredis
from redis.exceptions import RedisError

if TYPE_CHECKING:
    from app.core.config import Settings

logger = logging.getLogger("codebridge.identity.redis")


class IdentityRedisManager:
    """Manages Redis connection for token revocation and user caching."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client: aioredis.Redis | None = None
        self._is_available: bool = False

    @property
    def is_available(self) -> bool:
        return self._is_available and self.client is not None

    async def startup(self) -> None:
        if not self.settings.REDIS_ENABLED or not self.settings.REDIS_URL:
            self._is_available = False
            return

        try:
            self.client = aioredis.from_url(
                self.settings.REDIS_URL,
                decode_responses=True,
                socket_timeout=3.0,
                socket_connect_timeout=3.0,
                retry_on_timeout=True,
                max_connections=20,
            )
            await self.client.ping()
            self._is_available = True
            logger.info("Identity service connected to Redis cluster.")
        except Exception as exc:
            self._is_available = False
            logger.warning("Identity service Redis connection failed (fail-open): %s", exc)

    async def shutdown(self) -> None:
        if self.client:
            try:
                await self.client.aclose()
            except Exception:
                pass
            self.client = None
            self._is_available = False

    async def blacklist_token(self, jti: str, ttl_seconds: int = 900) -> bool:
        """Add a revoked token JTI to Redis blacklist."""
        if not self.is_available or not self.client or not jti:
            return False

        key = f"codebridge:blacklist:{jti}"
        try:
            await self.client.set(key, "revoked", ex=max(ttl_seconds, 60))
            return True
        except RedisError as exc:
            logger.warning("Failed to write to Redis blacklist: %s", exc)
            return False

    async def is_blacklisted(self, jti: str) -> bool:
        if not self.is_available or not self.client or not jti:
            return False

        key = f"codebridge:blacklist:{jti}"
        try:
            return bool(await self.client.exists(key))
        except RedisError:
            return False
