"""Background Kafka Consumer for Notification Service."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import TYPE_CHECKING

from aiokafka import AIOKafkaConsumer
from aiokafka.errors import KafkaError

from app.models.notification import Notification

if TYPE_CHECKING:
    from app.core.config import Settings

logger = logging.getLogger("codebridge.notification.consumer")


class NotificationKafkaConsumer:
    """Consumes domain events from Kafka and generates notifications for users."""

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
                group_id="codebridge-notification-service-group",
                auto_offset_reset="earliest",
                enable_auto_commit=True,
            )
            await self.consumer.start()
            self._running = True
            self._task = asyncio.create_task(self._consume_loop())
            logger.info("Notification Kafka Consumer started on topics: %s", self.TOPICS)
        except Exception as exc:
            logger.warning("Notification Kafka Consumer startup failed (failing open): %s", exc)

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
                logger.warning("Notification consumer Kafka error: %s. Reconnecting in 3s...", exc)
                await asyncio.sleep(3)
            except Exception as exc:
                logger.error("Unexpected error in notification consumer: %s", exc)
                await asyncio.sleep(1)

    async def _process_message(self, msg) -> None:
        try:
            payload = json.loads(msg.value.decode("utf-8"))
            event_type = payload.get("event_type", "unknown")
            agg_id = payload.get("aggregate_id")
            event_data = payload.get("payload", {})

            user_uuid = None
            if agg_id:
                try:
                    user_uuid = uuid.UUID(agg_id)
                except (ValueError, TypeError):
                    pass

            if not user_uuid:
                # If aggregate_id was not user_id, check owner_id in payload
                owner_id = event_data.get("owner_id")
                if owner_id:
                    try:
                        user_uuid = uuid.UUID(owner_id)
                    except (ValueError, TypeError):
                        pass

            if not user_uuid:
                return

            title = f"Update: {event_type}"
            message = f"Event {event_type} occurred."
            if event_type == "user.registered":
                title = "Welcome to CodeBridge!"
                message = f"Welcome {event_data.get('full_name', '')}! Your account is active."
            elif event_type == "project.created":
                title = "Project Created"
                message = f"Your project '{event_data.get('title', '')}' has been created."

            async with self.session_factory() as session:
                notification = Notification(
                    user_id=user_uuid,
                    event_type=event_type,
                    title=title,
                    message=message,
                    resource_type=msg.topic,
                    resource_id=str(agg_id) if agg_id else None,
                    idempotency_key=str(payload.get("event_id")),
                )
                session.add(notification)
                await session.commit()
                logger.info("Generated notification for user %s on event %s", user_uuid, event_type)
        except Exception as exc:
            logger.warning("Failed to process notification from Kafka: %s", exc)
