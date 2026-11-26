"""Production-grade asynchronous Kafka producer for Payment Service."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

try:
    from aiokafka import AIOKafkaProducer
    from aiokafka.errors import KafkaError
except ImportError:
    AIOKafkaProducer = None  # type: ignore[assignment, misc]
    KafkaError = Exception  # type: ignore[assignment, misc]

logger = logging.getLogger("codebridge.payment.kafka")


class PaymentKafkaProducer:
    """Publishes payment and escrow lifecycle events to Kafka."""

    def __init__(self, bootstrap_servers: str = "kafka:9092", enabled: bool = True) -> None:
        self.bootstrap_servers = bootstrap_servers
        self.enabled = enabled
        self.producer: AIOKafkaProducer | None = None
        self._is_available: bool = False

    @property
    def is_available(self) -> bool:
        return self._is_available and self.producer is not None

    async def startup(self) -> None:
        if not self.enabled or AIOKafkaProducer is None:
            self._is_available = False
            return
        try:
            self.producer = AIOKafkaProducer(
                bootstrap_servers=self.bootstrap_servers,
                retry_backoff_ms=500,
                request_timeout_ms=5000,
            )
            await self.producer.start()
            self._is_available = True
            logger.info("Payment Kafka producer connected to %s", self.bootstrap_servers)
        except Exception as exc:
            self._is_available = False
            logger.warning("Payment Kafka producer connection failed (failing open): %s", exc)

    async def shutdown(self) -> None:
        if self.producer:
            try:
                await self.producer.stop()
            except Exception:
                pass
            self.producer = None
            self._is_available = False

    async def publish_payment_event(
        self,
        event_type: str,
        escrow_id: str,
        payload: dict[str, Any],
    ) -> bool:
        """Publish a payment event to codebridge.payment.events."""
        if not self.is_available or not self.producer:
            return False

        event = {
            "event_id": str(uuid.uuid4()),
            "event_type": event_type,
            "aggregate_id": str(escrow_id),
            "source": "payment-service",
            "timestamp": datetime.now(UTC).isoformat(),
            "payload": payload,
        }

        try:
            raw = json.dumps(event, default=str).encode("utf-8")
            key = str(escrow_id).encode("utf-8")
            await self.producer.send_and_wait("codebridge.payment.events", value=raw, key=key)
            return True
        except KafkaError as exc:
            logger.warning("Failed to publish payment event %s: %s", event_type, exc)
            return False
