"""Background Kafka Consumer for Audit Service to record immutable audit logs."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import TYPE_CHECKING

from aiokafka import AIOKafkaConsumer
from aiokafka.errors import KafkaError

from app.models.audit import AuditLog

if TYPE_CHECKING:
    from app.core.config import Settings

logger = logging.getLogger("codebridge.audit.consumer")


class AuditKafkaConsumer:
    """Consumes domain events from Kafka and writes them to the immutable audit log."""

    TOPICS = [
        "codebridge.auth.events",
        "codebridge.project.events",
        "codebridge.payment.events",
    ]

    def __init__(self, settings: Settings, session_factory) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.consumer: AIOKafkaConsumer | None = None
        self._running: bool = False
        self._task: asyncio.Task | None = None

    async def startup(self) -> None:
        if not getattr(self.settings, "KAFKA_ENABLED", True):
            return

        bootstrap_servers = getattr(self.settings, "KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
        try:
            self.consumer = AIOKafkaConsumer(
                *self.TOPICS,
                bootstrap_servers=bootstrap_servers,
                group_id="codebridge-audit-service-group",
                auto_offset_reset="earliest",
                enable_auto_commit=True,
            )
            await self.consumer.start()
            self._running = True
            self._task = asyncio.create_task(self._consume_loop())
            logger.info("Audit Kafka Consumer started on topics: %s", self.TOPICS)
        except Exception as exc:
            logger.warning("Audit Kafka Consumer startup failed (failing open): %s", exc)

    async def shutdown(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self.consumer:
            try:
                await self.consumer.stop()
            except Exception:
                pass
            self.consumer = None

    async def _consume_loop(self) -> None:
        while self._running and self.consumer:
            try:
                async for msg in self.consumer:
                    if not self._running:
                        break
                    await self._process_message(msg)
            except asyncio.CancelledError:
                break
            except KafkaError as exc:
                logger.warning("Audit consumer loop Kafka error: %s. Reconnecting in 3s...", exc)
                await asyncio.sleep(3)
            except Exception as exc:
                logger.error("Unexpected error in audit consumer: %s", exc)
                await asyncio.sleep(1)

    async def _process_message(self, msg) -> None:
        try:
            payload = json.loads(msg.value.decode("utf-8"))
            event_type = payload.get("event_type", "unknown")
            source = payload.get("source", "unknown")
            agg_id = payload.get("aggregate_id")
            event_data = payload.get("payload", {})

            actor_uuid = None
            if agg_id:
                try:
                    actor_uuid = uuid.UUID(agg_id)
                except (ValueError, TypeError):
                    pass

            async with self.session_factory() as session:
                log_entry = AuditLog(
                    service_name=source,
                    actor_id=actor_uuid,
                    action=event_type,
                    resource_type=msg.topic,
                    resource_id=str(agg_id) if agg_id else None,
                    outcome="SUCCESS",
                    metadata_json=json.dumps(event_data, default=str),
                )
                session.add(log_entry)
                await session.commit()
                logger.info("Recorded audit log for event %s from %s", event_type, source)
        except Exception as exc:
            logger.warning("Failed to record audit log from Kafka message: %s", exc)
