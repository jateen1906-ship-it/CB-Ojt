"""Asynchronous Redis Cache-Aside Manager for Project Service."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

import redis.asyncio as aioredis
from redis.exceptions import RedisError

if TYPE_CHECKING:
    from app.core.config import Settings

logger = logging.getLogger("codebridge.project.redis")


class ProjectRedisManager:
    """Manages Redis connection for project caching and query acceleration."""

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
            logger.info("Project service connected to Redis cache.")
        except Exception as exc:
            self._is_available = False
            logger.warning("Project service Redis connection failed (fail-open): %s", exc)

    async def shutdown(self) -> None:
        if self.client:
            try:
                await self.client.aclose()
            except Exception:
                pass
            self.client = None
            self._is_available = False

    async def get_json(self, key: str) -> Any | None:
        """Fetch and deserialize JSON value from cache."""
        if not self.is_available or not self.client:
            return None
        try:
            val = await self.client.get(key)
            if val:
                return json.loads(val)
        except (RedisError, json.JSONDecodeError) as exc:
            logger.warning("Cache get_json error for %s: %s", key, exc)
        return None

    async def set_json(self, key: str, value: Any, ttl_seconds: int = 300) -> bool:
        """Serialize and store JSON value with TTL."""
        if not self.is_available or not self.client:
            return False
        try:
            raw = json.dumps(value, default=str)
            await self.client.set(key, raw, ex=ttl_seconds)
            return True
        except (RedisError, TypeError) as exc:
            logger.warning("Cache set_json error for %s: %s", key, exc)
            return False

    async def delete(self, key: str) -> None:
        """Delete a single cache key."""
        if not self.is_available or not self.client:
            return
        try:
            await self.client.delete(key)
        except RedisError:
            pass

    async def delete_pattern(self, pattern: str) -> None:
        """Scan and delete keys matching pattern (e.g. 'cb:proj:*')."""
        if not self.is_available or not self.client:
            return
        try:
            cursor = 0
            while True:
                cursor, keys = await self.client.scan(cursor, match=pattern, count=100)
                if keys:
                    await self.client.delete(*keys)
                if cursor == 0:
                    break
        except RedisError as exc:
            logger.warning("Cache delete_pattern error for %s: %s", pattern, exc)
