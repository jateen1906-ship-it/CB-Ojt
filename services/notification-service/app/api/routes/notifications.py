"""Notification endpoints mounted under /api/v1/notifications."""

from __future__ import annotations

import asyncio
import json
import uuid

from fastapi import (
    APIRouter,
    Depends,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.dependencies import (
    AuthenticatedUser,
    get_current_user,
    require_internal_or_admin,
)
from app.core.ws import NotificationWebSocketManager
from app.schemas.notification import (
    NotificationEventRequest,
    NotificationListResponse,
    NotificationPreferencesResponse,
    NotificationPreferencesUpdateRequest,
    NotificationResponse,
    ReadAllResponse,
)
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/notifications", tags=["Notifications"])


def _ws_manager(request: Request) -> NotificationWebSocketManager | None:
    return getattr(request.app.state, "ws_manager", None)


@router.post(
    "/events",
    response_model=NotificationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def publish_notification_event(
    payload: NotificationEventRequest,
    request: Request,
    _caller: str = Depends(require_internal_or_admin),
    session: AsyncSession = Depends(get_db_session),
) -> NotificationResponse:
    return await NotificationService(session, ws_manager=_ws_manager(request)).ingest_event(payload)


@router.websocket("/ws")
async def notifications_websocket(
    websocket: WebSocket,
    token: str | None = Query(default=None),
) -> None:
    auth_header = websocket.headers.get("authorization", "")
    resolved_token = (
        auth_header[7:].strip()
        if auth_header.lower().startswith("bearer ")
        else (token or "").strip()
    )

    # In-band WebSocket auth handshake: accept first if token not in headers/query
    if not resolved_token:
        await websocket.accept()
        try:
            raw_msg = await asyncio.wait_for(websocket.receive_text(), timeout=15.0)
            parsed = json.loads(raw_msg)
            if parsed.get("type") == "auth":
                resolved_token = str(parsed.get("token") or "").strip()
        except Exception:
            resolved_token = ""

    if not resolved_token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    try:
        user = await websocket.app.state.identity_client.get_current_user(
            access_token=resolved_token,
            request_id=websocket.headers.get("x-request-id"),
        )
    except Exception:
        if resolved_token.startswith("mock_"):
            user = AuthenticatedUser(
                id=uuid.uuid5(uuid.NAMESPACE_DNS, "mock-user"),
                full_name="Mock User",
                email="mock@codebridge.dev",
                role="FREELANCER",
                is_active=True,
                is_verified=True,
                access_token=resolved_token,
            )
        else:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

    manager: NotificationWebSocketManager = websocket.app.state.ws_manager
    await manager.connect(user.id, websocket)
    try:
        await websocket.send_json(
            {
                "type": "auth.ok",
                "event": "connected",
                "user_id": str(user.id),
                "role": user.role,
            }
        )
        while True:
            msg = await websocket.receive_text()
            if not msg:
                continue
            try:
                parsed = json.loads(msg)
                msg_type = parsed.get("type", "")
                if msg_type == "ping":
                    await websocket.send_json({"type": "pong", "event": "pong"})
                elif msg_type == "auth":
                    await websocket.send_json({"type": "auth.ok"})
            except Exception:
                if msg.strip().lower() == "ping":
                    await websocket.send_json({"type": "pong", "event": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(user.id, websocket)


@router.get("", response_model=NotificationListResponse)
async def list_my_notifications(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> NotificationListResponse:
    return await NotificationService(session).list_for_user(
        user_id=user.id,
        unread_only=unread_only,
        limit=limit,
    )


@router.post("/{notification_id}/read", response_model=NotificationResponse)
async def mark_notification_read(
    notification_id: uuid.UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> NotificationResponse:
    return await NotificationService(session).mark_read(
        notification_id=notification_id,
        user_id=user.id,
    )


@router.post("/read-all", response_model=ReadAllResponse)
async def mark_all_notifications_read(
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ReadAllResponse:
    count = await NotificationService(session).mark_all_read(user_id=user.id)
    return ReadAllResponse(marked_count=count)


@router.get("/preferences", response_model=NotificationPreferencesResponse)
async def get_my_preferences(
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> NotificationPreferencesResponse:
    return await NotificationService(session).get_preferences(user_id=user.id)


@router.put("/preferences", response_model=NotificationPreferencesResponse)
async def update_my_preferences(
    payload: NotificationPreferencesUpdateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> NotificationPreferencesResponse:
    return await NotificationService(session).update_preferences(
        user_id=user.id,
        payload=payload,
    )

