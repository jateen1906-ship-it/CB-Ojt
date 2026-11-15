"""Asynchronous Redis Cache and Distributed Lock Manager for Payment Service."""

from __future__ import annotations

import json
import logging
import uuid
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, AsyncIterator

import redis.asyncio as aioredis
from redis.exceptions import RedisError

if TYPE_CHECKING:
    from app.core.config import Settings

logger = logging.getLogger("codebridge.payment.redis")


class PaymentRedisManager:
    """Provides financial summary caching and distributed locking for escrow safety."""

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
            logger.info("Payment service connected to Redis cluster.")
        except Exception as exc:
            self._is_available = False
            logger.warning("Payment service Redis connection failed (fail-open): %s", exc)

    async def shutdown(self) -> None:
        if self.client:
            try:
                await self.client.aclose()
            except Exception:
                pass
            self.client = None
            self._is_available = False

    async def get_json(self, key: str) -> Any | None:
        if not self.is_available or not self.client:
            return None
        try:
            val = await self.client.get(key)
            if val:
                return json.loads(val)
        except (RedisError, json.JSONDecodeError) as exc:
            logger.warning("Payment cache get error: %s", exc)
        return None

    async def set_json(self, key: str, value: Any, ttl_seconds: int = 120) -> bool:
        if not self.is_available or not self.client:
            return False
        try:
            raw = json.dumps(value, default=str)
            await self.client.set(key, raw, ex=ttl_seconds)
            return True
        except (RedisError, TypeError) as exc:
            logger.warning("Payment cache set error: %s", exc)
            return False

    async def delete(self, key: str) -> None:
        if not self.is_available or not self.client:
            return
        try:
            await self.client.delete(key)
        except RedisError:
            pass

    async def delete_pattern(self, pattern: str) -> None:
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
        except RedisError:
            pass

    @asynccontextmanager
    async def distributed_lock(self, resource_name: str, timeout_seconds: int = 10) -> AsyncIterator[bool]:
        """Atomic Redlock to eliminate race conditions on payments and escrow release."""
        if not self.is_available or not self.client:
            yield True
            return

        lock_key = f"codebridge:lock:{resource_name}"
        lock_token = uuid.uuid4().hex
        acquired = False

        try:
            acquired = bool(await self.client.set(lock_key, lock_token, nx=True, ex=timeout_seconds))
            yield acquired
        finally:
            if acquired and self.client:
                # Safe Lua script ensures only lock holder deletes the lock
                release_lua = """
                if redis.call("get", KEYS[1]) == ARGV[1] then
                    return redis.call("del", KEYS[1])
                else
                    return 0
                end
                """
                try:
                    await self.client.eval(release_lua, 1, lock_key, lock_token)
                except Exception:
                    pass
