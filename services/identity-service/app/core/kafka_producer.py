"""Production-grade asynchronous Kafka producer for Identity Service."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaError

logger = logging.getLogger("codebridge.identity.kafka")


class IdentityKafkaProducer:
    """Publishes authentication and user lifecycle events to Kafka."""

    def __init__(self, bootstrap_servers: str = "kafka:9092", enabled: bool = True) -> None:
        self.bootstrap_servers = bootstrap_servers
        self.enabled = enabled
        self.producer: AIOKafkaProducer | None = None
        self._is_available: bool = False

    @property
    def is_available(self) -> bool:
        return self._is_available and self.producer is not None

    async def startup(self) -> None:
        if not self.enabled:
            return
        try:
            self.producer = AIOKafkaProducer(
                bootstrap_servers=self.bootstrap_servers,
                retry_backoff_ms=500,
                request_timeout_ms=5000,
            )
            await self.producer.start()
            self._is_available = True
            logger.info("Identity Kafka producer connected to %s", self.bootstrap_servers)
        except Exception as exc:
            self._is_available = False
            logger.warning("Identity Kafka producer connection failed (failing open): %s", exc)

    async def shutdown(self) -> None:
        if self.producer:
            try:
                await self.producer.stop()
            except Exception:
                pass
            self.producer = None
            self._is_available = False

    async def publish_auth_event(
        self,
        event_type: str,
        user_id: str,
        payload: dict[str, Any],
    ) -> bool:
        """Publish an auth event to codebridge.auth.events."""
        if not self.is_available or not self.producer:
            return False

        event = {
            "event_id": str(uuid.uuid4()),
            "event_type": event_type,
            "aggregate_id": str(user_id),
            "source": "identity-service",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }

        try:
            raw = json.dumps(event, default=str).encode("utf-8")
            key = str(user_id).encode("utf-8")
            await self.producer.send_and_wait("codebridge.auth.events", value=raw, key=key)
            return True
        except KafkaError as exc:
            logger.warning("Failed to publish auth event %s: %s", event_type, exc)
            return False
