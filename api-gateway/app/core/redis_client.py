"""Production-grade asynchronous Redis client for CodeBridge API Gateway."""

from __future__ import annotations

import logging
import time
import uuid
from typing import TYPE_CHECKING

import redis.asyncio as aioredis
from redis.exceptions import RedisError

if TYPE_CHECKING:
    from app.config import Settings

logger = logging.getLogger("codebridge.gateway.redis")


class GatewayRedisManager:
    """Manages resilient Redis connection pool and caching/rate-limiting utilities."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client: aioredis.Redis | None = None
        self._is_available: bool = False

    @property
    def is_available(self) -> bool:
        return self._is_available and self.client is not None

    async def startup(self) -> None:
        """Initialize the Redis connection pool."""
        if not self.settings.REDIS_ENABLED or not self.settings.REDIS_URL:
            logger.info("Redis is disabled or REDIS_URL not configured. Operating in fallback mode.")
            self._is_available = False
            return

        try:
            # decode_responses=True ensures strings instead of bytes
            self.client = aioredis.from_url(
                self.settings.REDIS_URL,
                decode_responses=True,
                socket_timeout=3.0,
                socket_connect_timeout=3.0,
                retry_on_timeout=True,
                max_connections=50,
            )
            # Verify connectivity
            await self.client.ping()
            self._is_available = True
            logger.info("Successfully connected to Redis cluster.", extra={"event": "redis_connected"})
        except Exception as exc:
            self._is_available = False
            logger.warning(
                "Redis connection failed during gateway startup: %s. Continuing with fail-open fallback.",
                exc,
                extra={"event": "redis_connection_warning"},
            )

    async def shutdown(self) -> None:
        """Close connection pool gracefully."""
        if self.client:
            try:
                await self.client.aclose()
            except Exception:
                pass
            self.client = None
            self._is_available = False
            logger.info("Redis connection closed.", extra={"event": "redis_shutdown"})

    async def ping(self) -> bool:
        """Health-check ping."""
        if not self.is_available or not self.client:
            return False
        try:
            return bool(await self.client.ping())
        except Exception:
            return False

    async def check_rate_limit(
        self,
        identifier: str,
        limit: int,
        window_seconds: int = 60,
    ) -> tuple[bool, int, int]:
        """Sliding-window distributed rate limiter using atomic Redis pipeline.

        Returns (is_limited, current_count, reset_seconds).
        Fails open if Redis encounters any network error.
        """
        if not self.is_available or not self.client:
            return False, 0, 0

        key = f"codebridge:ratelimit:{identifier}"
        now = time.time()
        clear_before = now - window_seconds
        member = f"{now}:{uuid.uuid4().hex[:8]}"

        try:
            async with self.client.pipeline(transaction=True) as pipe:
                pipe.zremrangebyscore(key, 0, clear_before)
                pipe.zcard(key)
                pipe.zadd(key, {member: now})
                pipe.expire(key, window_seconds)
                results = await pipe.execute()

            existing_count = results[1]
            current_count = existing_count + 1

            if current_count > limit:
                return True, current_count, window_seconds

            return False, current_count, window_seconds
        except RedisError as exc:
            logger.warning("Redis rate limit check error (failing open): %s", exc)
            return False, 0, 0

    async def is_token_blacklisted(self, jti: str) -> bool:
        """Check if JWT token jti is in the revoked blacklist (O(1))."""
        if not self.is_available or not self.client or not jti:
            return False

        key = f"codebridge:blacklist:{jti}"
        try:
            return bool(await self.client.exists(key))
        except RedisError as exc:
            logger.warning("Redis blacklist lookup error (failing open): %s", exc)
            return False

    async def blacklist_token(self, jti: str, ttl_seconds: int) -> bool:
        """Add a revoked token jti to blacklist with TTL."""
        if not self.is_available or not self.client or not jti:
            return False

        key = f"codebridge:blacklist:{jti}"
        try:
            await self.client.set(key, "revoked", ex=max(ttl_seconds, 60))
            return True
        except RedisError as exc:
            logger.warning("Redis blacklist_token error: %s", exc)
            return False
