"""Escrow financial workflow domain service enforcing server-side pricing, idempotency, and Review approval gates."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.razorpay_client import RazorpayClientAdapter
from app.clients.service_clients import (
    ProjectClient,
    ReviewClient,
    TelemetryRelayClient,
)
from app.core.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.core.security import AuthenticatedUser, hash_request_payload
from app.models import (
    DeveloperTdsLedger,
    EscrowMilestone,
    EscrowPayment,
    EscrowStatus,
    EscrowTransaction,
    MilestoneEscrowStatus,
    PaymentEvent,
    PaymentIdempotencyRecord,
    TransactionType,
)
from app.repositories.payment_repository import PaymentRepository
from app.schemas.payment import (
    AutoReleaseExecutionRequest,
    AutoReleaseExecutionResponse,
    CreateEscrowRequest,
    DeveloperTdsSummaryResponse,
    EscrowActionRequest,
    EscrowListResponse,
    EscrowPaymentResponse,
    EscrowTransactionResponse,
    FundEscrowRequest,
    MilestoneOrderCreateRequest,
    MilestoneOrderResponse,
    MilestoneRefundRequest,
    MilestoneRefundResponse,
    MilestoneReleaseResponse,
    MilestoneVerifyRequest,
    MilestoneVerifyResponse,
    RefundEscrowRequest,
    WebhookResponse,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _current_financial_year() -> str:
    now = datetime.now(UTC)
    if now.month >= 4:
        return f"{now.year}-{now.year + 1}"
    return f"{now.year - 1}-{now.year}"


class PaymentService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        project_client: ProjectClient,
        review_client: ReviewClient,
        telemetry_client: TelemetryRelayClient,
        razorpay_client: RazorpayClientAdapter | None = None,
    ) -> None:
        self.session = session
        self.repo = PaymentRepository(session)
        self.project_client = project_client
        self.review_client = review_client
        self.telemetry_client = telemetry_client
        self.razorpay_client = razorpay_client

    async def _check_idempotency(
        self,
        *,
        actor_id: uuid.UUID,
        operation_key: str,
        idempotency_key: str | None,
        request_hash: str,
    ) -> EscrowPaymentResponse | None:
        if not idempotency_key:
            return None
        cleaned = idempotency_key.strip()
        if not cleaned:
            return None
        existing = await self.repo.get_idempotency_record(
            actor_id=actor_id,
            operation_key=operation_key,
            idempotency_key=cleaned,
        )
        if existing is None:
            return None
        if existing.request_hash != request_hash:
            raise ConflictError(
                "Idempotency-Key was previously used with different request parameters.",
                error_code="IDEMPOTENCY_KEY_REUSE_CONFLICT",
            )
        return EscrowPaymentResponse.model_validate_json(existing.response_json)

    def _save_idempotency(
        self,
        *,
        actor_id: uuid.UUID,
        operation_key: str,
        idempotency_key: str | None,
        request_hash: str,
        status_code: int,
        response: EscrowPaymentResponse,
    ) -> None:
        if not idempotency_key or not idempotency_key.strip():
            return
        self.repo.add_idempotency_record(
            PaymentIdempotencyRecord(
                actor_id=actor_id,
                operation_key=operation_key,
                idempotency_key=idempotency_key.strip(),
                request_hash=request_hash,
                status_code=status_code,
                response_json=response.model_dump_json(),
            )
        )

    def _require_owner_or_admin_for_escrow(self, escrow: EscrowPayment, actor: AuthenticatedUser) -> None:
        if actor.role == "ADMIN":
            return
        if actor.role == "OWNER" and escrow.owner_id == actor.id:
            return
        raise ForbiddenError("Only the project owner or admin may manage this escrow.")

    async def create_escrow(
        self,
        *,
        project_id: uuid.UUID,
        payload: CreateEscrowRequest,
        actor: AuthenticatedUser,
        idempotency_key: str | None,
        request_id: str | None,
    ) -> EscrowPaymentResponse:
        op_key = f"create:{project_id}"
        req_hash = hash_request_payload({"project_id": str(project_id), **payload.model_dump()})
        replay = await self._check_idempotency(
            actor_id=actor.id,
            operation_key=op_key,
            idempotency_key=idempotency_key,
            request_hash=req_hash,
        )
        if replay is not None:
            return replay

        project = await self.project_client.get_project(
            project_id=project_id,
            access_token=actor.access_token,
            request_id=request_id,
        )
        if actor.role != "ADMIN" and (actor.role != "OWNER" or project.owner_id != actor.id):
            raise ForbiddenError("Only the project owner or admin can create project escrow.")
        if project.status == "CANCELLED":
            raise ConflictError("Cannot create escrow for a cancelled project.", error_code="PROJECT_CANCELLED")

        if payload.amount is not None:
            client_amount = payload.amount.quantize(Decimal("0.01"))
            if client_amount != project.budget:
                raise ValidationError(
                    f"Escrow amount ({client_amount}) must match server project budget ({project.budget}).",
                    error_code="ESCROW_AMOUNT_MISMATCH",
                )
        if payload.currency is not None and payload.currency.upper() != project.currency:
            raise ValidationError(
                f"Escrow currency ({payload.currency.upper()}) must match project currency ({project.currency}).",
                error_code="ESCROW_CURRENCY_MISMATCH",
            )

        existing = await self.repo.get_active_escrow_for_project(project_id)
        if existing is not None:
            raise ConflictError(
                "An active escrow already exists for this project.",
                error_code="ESCROW_ALREADY_EXISTS",
            )

        now = _utcnow()
        status_val = EscrowStatus.CREATED.value
        funding_ref = None
        funded_at = None
        held_at = None
        if payload.fund_immediately:
            status_val = EscrowStatus.HELD.value if (payload.hold_immediately or project.assigned_freelancer_id) else EscrowStatus.FUNDED.value
            funding_ref = f"sim_fund_{uuid.uuid4().hex[:12]}"
            funded_at = now
            if status_val == EscrowStatus.HELD.value:
                held_at = now

        escrow = EscrowPayment(
            project_id=project_id,
            owner_id=project.owner_id,
            freelancer_id=project.assigned_freelancer_id,
            amount=project.budget,
            currency=project.currency,
            status=status_val,
            funding_reference=funding_ref,
            funded_at=funded_at,
            held_at=held_at,
            created_at=now,
            updated_at=now,
        )
        self.repo.add_escrow(escrow)
        self.repo.add_transaction(
            EscrowTransaction(
                escrow=escrow,
                project_id=project_id,
                actor_id=actor.id,
                transaction_type=TransactionType.CREATE.value,
                amount=project.budget,
                currency=project.currency,
                idempotency_key=idempotency_key,
                reference_id=f"esc_init_{uuid.uuid4().hex[:10]}",
                notes=payload.notes or "Simulated escrow created.",
                created_at=now,
            )
        )
        self.repo.add_event(
            PaymentEvent(
                escrow=escrow,
                actor_id=actor.id,
                from_status=None,
                to_status=EscrowStatus.CREATED.value,
                detail=f"Escrow initialized for {project.budget} {project.currency}.",
                request_id=request_id,
                created_at=now,
            )
        )
        if payload.fund_immediately:
            self.repo.add_transaction(
                EscrowTransaction(
                    escrow=escrow,
                    project_id=project_id,
                    actor_id=actor.id,
                    transaction_type=TransactionType.FUND.value,
                    amount=project.budget,
                    currency=project.currency,
                    idempotency_key=idempotency_key,
                    reference_id=funding_ref,
                    notes="Escrow funded on initialization.",
                    created_at=now,
                )
            )
            self.repo.add_event(
                PaymentEvent(
                    escrow=escrow,
                    actor_id=actor.id,
                    from_status=EscrowStatus.CREATED.value,
                    to_status=status_val,
                    detail=f"Escrow funded via simulated rail ({funding_ref}).",
                    request_id=request_id,
                    created_at=now,
                )
            )

        await self.session.flush()
        loaded = await self.repo.get_escrow_by_id(escrow.id)
        assert loaded is not None
        response = EscrowPaymentResponse.model_validate(loaded)
        self._save_idempotency(
            actor_id=actor.id,
            operation_key=op_key,
            idempotency_key=idempotency_key,
            request_hash=req_hash,
            status_code=201,
            response=response,
        )
        await self.session.commit()

        await self.telemetry_client.audit(
            actor_id=actor.id,
            actor_role=actor.role,
            action="ESCROW_CREATED",
            resource_type="escrow_payment",
            resource_id=str(response.id),
            project_id=project_id,
            metadata={"amount": str(response.amount), "currency": response.currency, "status": response.status},
            request_id=request_id,
        )
        return response

    async def fund_escrow(
        self,
        *,
        escrow_id: uuid.UUID,
        payload: FundEscrowRequest,
        actor: AuthenticatedUser,
        idempotency_key: str | None,
        request_id: str | None,
    ) -> EscrowPaymentResponse:
        op_key = f"fund:{escrow_id}"
        req_hash = hash_request_payload({"escrow_id": str(escrow_id), **payload.model_dump()})
        replay = await self._check_idempotency(
            actor_id=actor.id,
            operation_key=op_key,
            idempotency_key=idempotency_key,
            request_hash=req_hash,
        )
        if replay is not None:
            return replay

        escrow = await self.repo.get_escrow_by_id(escrow_id, for_update=True)
        if escrow is None:
            raise NotFoundError()
        self._require_owner_or_admin_for_escrow(escrow, actor)
        if escrow.status != EscrowStatus.CREATED.value:
            raise ConflictError(
                f"Cannot fund escrow in {escrow.status} status.",
                error_code="INVALID_ESCROW_STATE",
            )

        project = await self.project_client.get_project(
            project_id=escrow.project_id,
            access_token=actor.access_token,
            request_id=request_id,
        )
        if project.assigned_freelancer_id and not escrow.freelancer_id:
            escrow.freelancer_id = project.assigned_freelancer_id

        now = _utcnow()
        should_hold = payload.hold_if_assigned and escrow.freelancer_id is not None
        next_status = EscrowStatus.HELD.value if should_hold else EscrowStatus.FUNDED.value
        ref = f"sim_fund_{uuid.uuid4().hex[:12]}"

        escrow.status = next_status
        escrow.funding_reference = ref
        escrow.funded_at = now
        if should_hold:
            escrow.held_at = now
        escrow.updated_at = now

        self.repo.add_transaction(
            EscrowTransaction(
                escrow_id=escrow.id,
                project_id=escrow.project_id,
                actor_id=actor.id,
                transaction_type=TransactionType.FUND.value,
                amount=escrow.amount,
                currency=escrow.currency,
                idempotency_key=idempotency_key,
                reference_id=ref,
                notes=payload.notes or f"Funded via {payload.payment_method_reference}",
                created_at=now,
            )
        )
        self.repo.add_event(
            PaymentEvent(
                escrow_id=escrow.id,
                actor_id=actor.id,
                from_status=EscrowStatus.CREATED.value,
                to_status=next_status,
                detail=f"Escrow funded ({ref}).",
                request_id=request_id,
                created_at=now,
            )
        )
        await self.session.flush()
        loaded = await self.repo.get_escrow_by_id(escrow.id)
        assert loaded is not None
        response = EscrowPaymentResponse.model_validate(loaded)
        self._save_idempotency(
            actor_id=actor.id,
            operation_key=op_key,
            idempotency_key=idempotency_key,
            request_hash=req_hash,
            status_code=200,
            response=response,
        )
        await self.session.commit()
        return response

    async def hold_escrow(
        self,
        *,
        escrow_id: uuid.UUID,
        payload: EscrowActionRequest,
        actor: AuthenticatedUser,
        request_id: str | None,
    ) -> EscrowPaymentResponse:
        escrow = await self.repo.get_escrow_by_id(escrow_id, for_update=True)
        if escrow is None:
            raise NotFoundError()
        self._require_owner_or_admin_for_escrow(escrow, actor)
        if escrow.status == EscrowStatus.HELD.value:
            return EscrowPaymentResponse.model_validate(escrow)
        if escrow.status != EscrowStatus.FUNDED.value:
            raise ConflictError(
                f"Only FUNDED escrow can be moved to HELD (current: {escrow.status}).",
                error_code="INVALID_ESCROW_STATE",
            )

        project = await self.project_client.get_project(
            project_id=escrow.project_id,
            access_token=actor.access_token,
            request_id=request_id,
        )
        if project.assigned_freelancer_id is None:
            raise ConflictError(
                "Cannot lock escrow into HELD before a freelancer is assigned.",
                error_code="FREELANCER_NOT_ASSIGNED",
            )

        now = _utcnow()
        escrow.freelancer_id = project.assigned_freelancer_id
        escrow.status = EscrowStatus.HELD.value
        escrow.held_at = now
        escrow.updated_at = now
        self.repo.add_transaction(
            EscrowTransaction(
                escrow_id=escrow.id,
                project_id=escrow.project_id,
                actor_id=actor.id,
                transaction_type=TransactionType.HOLD.value,
                amount=escrow.amount,
                currency=escrow.currency,
                reference_id=f"sim_hold_{uuid.uuid4().hex[:10]}",
                notes=payload.reason or "Escrow placed on hold for assigned freelancer.",
                created_at=now,
            )
        )
        self.repo.add_event(
            PaymentEvent(
                escrow_id=escrow.id,
                actor_id=actor.id,
                from_status=EscrowStatus.FUNDED.value,
                to_status=EscrowStatus.HELD.value,
                detail="Escrow funds locked in HELD state.",
                request_id=request_id,
                created_at=now,
            )
        )
        await self.session.commit()
        loaded = await self.repo.get_escrow_by_id(escrow.id)
        assert loaded is not None
        return EscrowPaymentResponse.model_validate(loaded)

    async def release_escrow(
        self,
        *,
        escrow_id: uuid.UUID,
        payload: EscrowActionRequest,
        actor: AuthenticatedUser,
        idempotency_key: str | None,
        request_id: str | None,
    ) -> EscrowPaymentResponse:
        op_key = f"release:{escrow_id}"
        req_hash = hash_request_payload({"escrow_id": str(escrow_id), **payload.model_dump()})
        replay = await self._check_idempotency(
            actor_id=actor.id,
            operation_key=op_key,
            idempotency_key=idempotency_key,
            request_hash=req_hash,
        )
        if replay is not None:
            return replay

        escrow = await self.repo.get_escrow_by_id(escrow_id, for_update=True)
        if escrow is None:
            raise NotFoundError()
        self._require_owner_or_admin_for_escrow(escrow, actor)

        if escrow.status not in {
            EscrowStatus.FUNDED.value,
            EscrowStatus.HELD.value,
            EscrowStatus.RELEASE_PENDING.value,
        }:
            raise ConflictError(
                f"Cannot release escrow in {escrow.status} status.",
                error_code="INVALID_ESCROW_STATE",
            )

        approval = await self.review_client.require_project_approval(
            project_id=escrow.project_id,
            access_token=actor.access_token,
            request_id=request_id,
        )
        project = await self.project_client.get_project(
            project_id=escrow.project_id,
            access_token=actor.access_token,
            request_id=request_id,
        )
        payout_freelancer_id = approval.approved_freelancer_id or project.assigned_freelancer_id or escrow.freelancer_id
        if payout_freelancer_id is None:
            raise ConflictError(
                "No target freelancer could be resolved for escrow release.",
                error_code="FREELANCER_NOT_ASSIGNED",
            )

        previous_status = escrow.status
        now = _utcnow()
        release_ref = f"sim_rel_{uuid.uuid4().hex[:12]}"
        escrow.freelancer_id = payout_freelancer_id
        escrow.status = EscrowStatus.RELEASED.value
        escrow.release_reference = release_ref
        escrow.released_at = now
        escrow.updated_at = now

        self.repo.add_event(
            PaymentEvent(
                escrow_id=escrow.id,
                actor_id=actor.id,
                from_status=previous_status,
                to_status=EscrowStatus.RELEASE_PENDING.value,
                detail="Review approval confirmed; initiating simulated payout release.",
                request_id=request_id,
                created_at=now,
            )
        )
        self.repo.add_transaction(
            EscrowTransaction(
                escrow_id=escrow.id,
                project_id=escrow.project_id,
                actor_id=actor.id,
                transaction_type=TransactionType.RELEASE.value,
                amount=escrow.amount,
                currency=escrow.currency,
                idempotency_key=idempotency_key,
                reference_id=release_ref,
                notes=payload.reason or f"Escrow released for approved submission {approval.approved_submission_id}.",
                created_at=now,
            )
        )
        self.repo.add_event(
            PaymentEvent(
                escrow_id=escrow.id,
                actor_id=actor.id,
                from_status=EscrowStatus.RELEASE_PENDING.value,
                to_status=EscrowStatus.RELEASED.value,
                detail=f"Payout released ({release_ref}) to freelancer {payout_freelancer_id}.",
                request_id=request_id,
                created_at=now,
            )
        )

        await self.session.flush()
        loaded = await self.repo.get_escrow_by_id(escrow.id)
        assert loaded is not None
        response = EscrowPaymentResponse.model_validate(loaded)
        self._save_idempotency(
            actor_id=actor.id,
            operation_key=op_key,
            idempotency_key=idempotency_key,
            request_hash=req_hash,
            status_code=200,
            response=response,
        )
        await self.session.commit()

        await self.telemetry_client.notify(
            user_id=payout_freelancer_id,
            event_type="ESCROW_RELEASED",
            title="Escrow Payment Released",
            message=f"Payment of {escrow.amount} {escrow.currency} was released for '{project.title}'.",
            project_id=escrow.project_id,
            idempotency_key=f"escrow-released-{escrow.id}",
            request_id=request_id,
        )
        await self.telemetry_client.audit(
            actor_id=actor.id,
            actor_role=actor.role,
            action="ESCROW_RELEASED",
            resource_type="escrow_payment",
            resource_id=str(escrow.id),
            project_id=escrow.project_id,
            metadata={"amount": str(escrow.amount), "currency": escrow.currency, "release_reference": release_ref},
            request_id=request_id,
        )
        return response

    async def refund_escrow(
        self,
        *,
        escrow_id: uuid.UUID,
        payload: RefundEscrowRequest,
        actor: AuthenticatedUser,
        idempotency_key: str | None,
        request_id: str | None,
    ) -> EscrowPaymentResponse:
        op_key = f"refund:{escrow_id}"
        req_hash = hash_request_payload({"escrow_id": str(escrow_id), **payload.model_dump()})
        replay = await self._check_idempotency(
            actor_id=actor.id,
            operation_key=op_key,
            idempotency_key=idempotency_key,
            request_hash=req_hash,
        )
        if replay is not None:
            return replay

        escrow = await self.repo.get_escrow_by_id(escrow_id, for_update=True)
        if escrow is None:
            raise NotFoundError()
        self._require_owner_or_admin_for_escrow(escrow, actor)

        if escrow.status == EscrowStatus.RELEASED.value:
            raise ConflictError(
                "Cannot refund an escrow after funds have already been released.",
                error_code="ESCROW_ALREADY_RELEASED",
            )
        if escrow.status in {EscrowStatus.REFUNDED.value, EscrowStatus.CANCELLED.value}:
            raise ConflictError(
                f"Escrow is already in terminal {escrow.status} status.",
                error_code="INVALID_ESCROW_STATE",
            )
        if escrow.status == EscrowStatus.CREATED.value:
            raise ConflictError(
                "Unfunded CREATED escrow should be cancelled rather than refunded.",
                error_code="ESCROW_NOT_FUNDED",
            )

        previous_status = escrow.status
        now = _utcnow()
        refund_ref = f"sim_ref_{uuid.uuid4().hex[:12]}"
        next_status = EscrowStatus.REFUNDED.value if payload.process_immediately else EscrowStatus.REFUND_REQUESTED.value
        escrow.status = next_status
        escrow.refund_reference = refund_ref
        if payload.process_immediately:
            escrow.refunded_at = now
        escrow.updated_at = now

        self.repo.add_transaction(
            EscrowTransaction(
                escrow_id=escrow.id,
                project_id=escrow.project_id,
                actor_id=actor.id,
                transaction_type=(
                    TransactionType.REFUND.value
                    if payload.process_immediately
                    else TransactionType.REFUND_REQUEST.value
                ),
                amount=escrow.amount,
                currency=escrow.currency,
                idempotency_key=idempotency_key,
                reference_id=refund_ref,
                notes=payload.reason,
                created_at=now,
            )
        )
        self.repo.add_event(
            PaymentEvent(
                escrow_id=escrow.id,
                actor_id=actor.id,
                from_status=previous_status,
                to_status=next_status,
                detail=payload.reason,
                request_id=request_id,
                created_at=now,
            )
        )

        await self.session.flush()
        loaded = await self.repo.get_escrow_by_id(escrow.id)
        assert loaded is not None
        response = EscrowPaymentResponse.model_validate(loaded)
        self._save_idempotency(
            actor_id=actor.id,
            operation_key=op_key,
            idempotency_key=idempotency_key,
            request_hash=req_hash,
            status_code=200,
            response=response,
        )
        await self.session.commit()
        return response

    async def cancel_escrow(
        self,
        *,
        escrow_id: uuid.UUID,
        payload: EscrowActionRequest,
        actor: AuthenticatedUser,
        request_id: str | None,
    ) -> EscrowPaymentResponse:
        escrow = await self.repo.get_escrow_by_id(escrow_id, for_update=True)
        if escrow is None:
            raise NotFoundError()
        self._require_owner_or_admin_for_escrow(escrow, actor)
        if escrow.status != EscrowStatus.CREATED.value:
            raise ConflictError(
                f"Only unfunded CREATED escrow can be cancelled (current: {escrow.status}).",
                error_code="INVALID_ESCROW_STATE",
            )
        now = _utcnow()
        escrow.status = EscrowStatus.CANCELLED.value
        escrow.cancelled_at = now
        escrow.updated_at = now
        self.repo.add_transaction(
            EscrowTransaction(
                escrow_id=escrow.id,
                project_id=escrow.project_id,
                actor_id=actor.id,
                transaction_type=TransactionType.CANCEL.value,
                amount=escrow.amount,
                currency=escrow.currency,
                notes=payload.reason or "Unfunded escrow cancelled.",
                created_at=now,
            )
        )
        self.repo.add_event(
            PaymentEvent(
                escrow_id=escrow.id,
                actor_id=actor.id,
                from_status=EscrowStatus.CREATED.value,
                to_status=EscrowStatus.CANCELLED.value,
                detail=payload.reason or "Escrow cancelled before funding.",
                request_id=request_id,
                created_at=now,
            )
        )
        await self.session.commit()
        loaded = await self.repo.get_escrow_by_id(escrow.id)
        assert loaded is not None
        return EscrowPaymentResponse.model_validate(loaded)

    async def _require_read_access(
        self,
        *,
        escrow: EscrowPayment,
        user: AuthenticatedUser,
        request_id: str | None,
    ) -> None:
        if user.role == "ADMIN" or escrow.owner_id == user.id or escrow.freelancer_id == user.id:
            return
        project = await self.project_client.get_project(
            project_id=escrow.project_id,
            access_token=user.access_token,
            request_id=request_id,
        )
        if project.owner_id == user.id or project.assigned_freelancer_id == user.id:
            return
        raise ForbiddenError("You do not have permission to view this escrow record.")

    async def get_escrow(
        self,
        *,
        escrow_id: uuid.UUID,
        user: AuthenticatedUser,
        request_id: str | None,
    ) -> EscrowPaymentResponse:
        escrow = await self.repo.get_escrow_by_id(escrow_id)
        if escrow is None:
            raise NotFoundError()
        await self._require_read_access(escrow=escrow, user=user, request_id=request_id)
        return EscrowPaymentResponse.model_validate(escrow)

    async def list_project_escrows(
        self,
        *,
        project_id: uuid.UUID,
        user: AuthenticatedUser,
        request_id: str | None,
    ) -> EscrowListResponse:
        project = await self.project_client.get_project(
            project_id=project_id,
            access_token=user.access_token,
            request_id=request_id,
        )
        if (
            user.role != "ADMIN"
            and project.owner_id != user.id
            and project.assigned_freelancer_id != user.id
        ):
            raise ForbiddenError("You do not have permission to inspect project escrows.")
        escrows = await self.repo.list_escrows_for_project(project_id)
        return EscrowListResponse(
            project_id=project_id,
            total=len(escrows),
            items=[EscrowPaymentResponse.model_validate(e) for e in escrows],
        )

    async def get_escrow_transactions(
        self,
        *,
        escrow_id: uuid.UUID,
        user: AuthenticatedUser,
        request_id: str | None,
    ) -> list[EscrowTransactionResponse]:
        escrow = await self.repo.get_escrow_by_id(escrow_id)
        if escrow is None:
            raise NotFoundError()
        await self._require_read_access(escrow=escrow, user=user, request_id=request_id)
        txns = await self.repo.list_transactions(escrow_id)
        return [EscrowTransactionResponse.model_validate(t) for t in txns]

    async def create_milestone_order(
        self,
        *,
        payload: MilestoneOrderCreateRequest,
        user: AuthenticatedUser,
        request_id: str | None,
    ) -> MilestoneOrderResponse:
        """Create a funded milestone order via Razorpay Route with transfers locked on-hold in RBI Nodal Escrow."""
        existing = await self.repo.get_milestone_by_idempotency_key(payload.idempotency_key)
        if existing is not None:
            key_id = self.razorpay_client._key_id if self.razorpay_client else "rzp_test_mock_key_id"
            return MilestoneOrderResponse(
                milestone_id=existing.id,
                project_id=existing.project_id,
                task_id=existing.task_id,
                owner_id=existing.owner_id,
                developer_id=existing.developer_id,
                amount_paise=existing.amount_paise,
                platform_fee_paise=existing.platform_fee_paise,
                developer_payout_paise=existing.developer_payout_paise,
                currency=existing.currency,
                razorpay_order_id=existing.razorpay_order_id,
                razorpay_key_id=key_id or "rzp_test_mock_key_id",
                status=existing.status,
                idempotency_key=existing.idempotency_key,
                created_at=existing.created_at,
            )

        existing_task_milestone = await self.repo.get_milestone_by_project_and_task(
            project_id=payload.project_id,
            task_id=payload.task_id,
        )
        if existing_task_milestone is not None and existing_task_milestone.status in {
            MilestoneEscrowStatus.INITIATED.value,
            MilestoneEscrowStatus.HELD_IN_ESCROW.value,
        }:
            key_id = self.razorpay_client._key_id if self.razorpay_client else "rzp_test_mock_key_id"
            return MilestoneOrderResponse(
                milestone_id=existing_task_milestone.id,
                project_id=existing_task_milestone.project_id,
                task_id=existing_task_milestone.task_id,
                owner_id=existing_task_milestone.owner_id,
                developer_id=existing_task_milestone.developer_id,
                amount_paise=existing_task_milestone.amount_paise,
                platform_fee_paise=existing_task_milestone.platform_fee_paise,
                developer_payout_paise=existing_task_milestone.developer_payout_paise,
                currency=existing_task_milestone.currency,
                razorpay_order_id=existing_task_milestone.razorpay_order_id,
                razorpay_key_id=key_id or "rzp_test_mock_key_id",
                status=existing_task_milestone.status,
                idempotency_key=existing_task_milestone.idempotency_key,
                created_at=existing_task_milestone.created_at,
            )

        project = await self.project_client.get_project(
            project_id=payload.project_id,
            access_token=user.access_token,
            request_id=request_id,
        )
        if user.role != "ADMIN" and project.owner_id != user.id:
            raise ForbiddenError("Only project owners or administrators can fund project milestones.")

        amount_paise = payload.amount_paise
        platform_fee_paise = int(amount_paise * 0.10)
        developer_payout_paise = amount_paise - platform_fee_paise

        developer_sub_acc = payload.developer_account_id or f"acc_dev_{payload.developer_id.hex[:12]}"
        receipt = f"cb_rcpt_{payload.task_id.hex[:8]}"

        rz_client = self.razorpay_client
        if rz_client is None:
            from app.core.config import Settings
            rz_client = RazorpayClientAdapter(Settings())

        rz_order = rz_client.create_milestone_order(
            amount_paise=amount_paise,
            developer_account_id=developer_sub_acc,
            developer_payout_paise=developer_payout_paise,
            receipt=receipt,
            notes={
                "project_id": str(payload.project_id),
                "task_id": str(payload.task_id),
                "owner_id": str(user.id),
                "developer_id": str(payload.developer_id),
                "milestone_title": payload.milestone_title or "Milestone Funding",
            },
        )

        rz_order_id = rz_order["id"]
        rz_transfer_id = None
        if rz_order.get("transfers"):
            rz_transfer_id = rz_order["transfers"][0].get("id")

        milestone = EscrowMilestone(
            project_id=payload.project_id,
            task_id=payload.task_id,
            owner_id=user.id,
            developer_id=payload.developer_id,
            amount_paise=amount_paise,
            platform_fee_paise=platform_fee_paise,
            developer_payout_paise=developer_payout_paise,
            currency="INR",
            razorpay_order_id=rz_order_id,
            razorpay_payment_id=None,
            razorpay_transfer_id=rz_transfer_id,
            status=MilestoneEscrowStatus.INITIATED.value,
            idempotency_key=payload.idempotency_key,
        )
        self.repo.add_milestone(milestone)
        await self.session.commit()

        key_id = rz_client._key_id or "rzp_test_mock_key_id"
        return MilestoneOrderResponse(
            milestone_id=milestone.id,
            project_id=milestone.project_id,
            task_id=milestone.task_id,
            owner_id=milestone.owner_id,
            developer_id=milestone.developer_id,
            amount_paise=milestone.amount_paise,
            platform_fee_paise=milestone.platform_fee_paise,
            developer_payout_paise=milestone.developer_payout_paise,
            currency=milestone.currency,
            razorpay_order_id=milestone.razorpay_order_id,
            razorpay_key_id=key_id,
            status=milestone.status,
            idempotency_key=milestone.idempotency_key,
            created_at=milestone.created_at,
        )

    async def verify_milestone_payment(
        self,
        *,
        payload: MilestoneVerifyRequest,
        user: AuthenticatedUser,
        request_id: str | None,
    ) -> MilestoneVerifyResponse:
        """Verify the HMAC signature from Razorpay Checkout modal and transition milestone to HELD_IN_ESCROW."""
        milestone = await self.repo.get_milestone_by_order_id(payload.razorpay_order_id)
        if milestone is None:
            raise NotFoundError("Escrow milestone matching Razorpay order ID not found.")

        if user.role != "ADMIN" and milestone.owner_id != user.id:
            raise ForbiddenError("Only the milestone funder or an administrator may verify this payment.")

        if milestone.status == MilestoneEscrowStatus.HELD_IN_ESCROW.value:
            return MilestoneVerifyResponse(
                milestone_id=milestone.id,
                project_id=milestone.project_id,
                task_id=milestone.task_id,
                status=milestone.status,
                amount_paise=milestone.amount_paise,
                currency=milestone.currency,
                razorpay_order_id=milestone.razorpay_order_id,
                razorpay_payment_id=milestone.razorpay_payment_id or payload.razorpay_payment_id,
                held_at=milestone.held_at or _utcnow(),
            )

        rz_client = self.razorpay_client
        if rz_client is None:
            from app.core.config import Settings
            rz_client = RazorpayClientAdapter(Settings())

        is_valid = rz_client.verify_payment_signature(
            razorpay_order_id=payload.razorpay_order_id,
            razorpay_payment_id=payload.razorpay_payment_id,
            razorpay_signature=payload.razorpay_signature,
        )
        if not is_valid:
            raise ValidationError("Invalid Razorpay payment signature.")

        milestone.razorpay_payment_id = payload.razorpay_payment_id
        milestone.status = MilestoneEscrowStatus.HELD_IN_ESCROW.value
        milestone.held_at = _utcnow()
        await self.session.commit()

        await self.telemetry_client.audit(
            actor_id=user.id,
            actor_role=user.role,
            action="PAYMENT_MILESTONE_HELD_IN_ESCROW",
            resource_type="escrow_milestone",
            resource_id=str(milestone.id),
            project_id=milestone.project_id,
            metadata={
                "task_id": str(milestone.task_id),
                "amount_paise": milestone.amount_paise,
                "currency": milestone.currency,
                "razorpay_order_id": milestone.razorpay_order_id,
                "razorpay_payment_id": milestone.razorpay_payment_id,
            },
            request_id=request_id,
        )

        return MilestoneVerifyResponse(
            milestone_id=milestone.id,
            project_id=milestone.project_id,
            task_id=milestone.task_id,
            status=milestone.status,
            amount_paise=milestone.amount_paise,
            currency=milestone.currency,
            razorpay_order_id=milestone.razorpay_order_id,
            razorpay_payment_id=milestone.razorpay_payment_id,
            held_at=milestone.held_at,
        )

    async def release_milestone_payout(
        self,
        *,
        identifier: str,
        user: AuthenticatedUser,
        request_id: str | None,
    ) -> MilestoneReleaseResponse:
        """Lift nodal hold on Razorpay Route transfer, deduct Section 194-O TDS if applicable, and credit developer instantly."""
        milestone = None
        try:
            m_id = uuid.UUID(identifier)
            milestone = await self.repo.get_milestone_by_id(m_id, for_update=True)
        except ValueError:
            pass

        if milestone is None:
            milestone = await self.repo.get_milestone_by_order_id(identifier)
        if milestone is None:
            milestone = await self.repo.get_milestone_by_transfer_id(identifier)

        if milestone is None:
            raise NotFoundError("Escrow milestone matching identifier not found.")

        if user.role != "ADMIN" and milestone.owner_id != user.id:
            raise ForbiddenError("Only project owners or administrators may release milestone funds.")

        if milestone.status == MilestoneEscrowStatus.RELEASED.value:
            return MilestoneReleaseResponse(
                milestone_id=milestone.id,
                project_id=milestone.project_id,
                task_id=milestone.task_id,
                developer_id=milestone.developer_id,
                status=milestone.status,
                developer_payout_paise=milestone.developer_payout_paise,
                tds_deducted_paise=0,
                net_payout_paise=milestone.developer_payout_paise,
                currency=milestone.currency,
                released_at=milestone.released_at or _utcnow(),
            )

        if milestone.status != MilestoneEscrowStatus.HELD_IN_ESCROW.value:
            raise ValidationError(
                f"Cannot release milestone in status '{milestone.status}'. Milestone must be in 'HELD_IN_ESCROW'."
            )

        fy = _current_financial_year()
        tds_ledger = await self.repo.get_tds_ledger(
            developer_id=milestone.developer_id,
            financial_year=fy,
            for_update=True,
        )
        if tds_ledger is None:
            tds_ledger = DeveloperTdsLedger(
                developer_id=milestone.developer_id,
                financial_year=fy,
                cumulative_gross_payout_paise=0,
                tds_threshold_crossed=False,
                total_tds_deducted_paise=0,
            )
            self.repo.add_tds_ledger(tds_ledger)

        # Section 194-O TDS: ₹5 Lakhs = 50,000,000 paise threshold
        TDS_THRESHOLD_PAISE = 50_000_000
        payout_paise = milestone.developer_payout_paise
        projected_payout = tds_ledger.cumulative_gross_payout_paise + payout_paise

        tds_paise = 0
        if projected_payout >= TDS_THRESHOLD_PAISE or tds_ledger.tds_threshold_crossed:
            tds_ledger.tds_threshold_crossed = True
            tds_paise = int(payout_paise * 0.01)

        net_payout_paise = payout_paise - tds_paise
        tds_ledger.cumulative_gross_payout_paise = projected_payout
        tds_ledger.total_tds_deducted_paise += tds_paise

        rz_client = self.razorpay_client
        if rz_client is None:
            from app.core.config import Settings
            rz_client = RazorpayClientAdapter(Settings())

        if milestone.razorpay_transfer_id:
            rz_client.release_transfer(milestone.razorpay_transfer_id)

        milestone.status = MilestoneEscrowStatus.RELEASED.value
        milestone.released_at = _utcnow()
        await self.session.commit()

        await self.telemetry_client.audit(
            actor_id=user.id,
            actor_role=user.role,
            action="PAYMENT_MILESTONE_SETTLED_INSTANT",
            resource_type="escrow_milestone",
            resource_id=str(milestone.id),
            project_id=milestone.project_id,
            metadata={
                "task_id": str(milestone.task_id),
                "developer_id": str(milestone.developer_id),
                "payout_paise": payout_paise,
                "tds_deducted_paise": tds_paise,
                "net_payout_paise": net_payout_paise,
                "currency": milestone.currency,
                "transfer_id": milestone.razorpay_transfer_id,
            },
            request_id=request_id,
        )

        return MilestoneReleaseResponse(
            milestone_id=milestone.id,
            project_id=milestone.project_id,
            task_id=milestone.task_id,
            developer_id=milestone.developer_id,
            status=milestone.status,
            developer_payout_paise=payout_paise,
            tds_deducted_paise=tds_paise,
            net_payout_paise=net_payout_paise,
            currency=milestone.currency,
            released_at=milestone.released_at,
        )

    async def refund_milestone_escrow(
        self,
        *,
        identifier: str,
        payload: MilestoneRefundRequest,
        user: AuthenticatedUser,
        request_id: str | None,
    ) -> MilestoneRefundResponse:
        """Reverse held funds back to client's original UPI/card source."""
        milestone = None
        try:
            m_id = uuid.UUID(identifier)
            milestone = await self.repo.get_milestone_by_id(m_id, for_update=True)
        except ValueError:
            pass

        if milestone is None:
            milestone = await self.repo.get_milestone_by_order_id(identifier)
        if milestone is None:
            milestone = await self.repo.get_milestone_by_transfer_id(identifier)

        if milestone is None:
            raise NotFoundError("Escrow milestone matching identifier not found.")

        if user.role != "ADMIN" and milestone.owner_id != user.id:
            raise ForbiddenError("Only project owners or administrators may refund milestones.")

        if milestone.status == MilestoneEscrowStatus.REFUNDED.value:
            return MilestoneRefundResponse(
                milestone_id=milestone.id,
                project_id=milestone.project_id,
                task_id=milestone.task_id,
                status=milestone.status,
                refunded_amount_paise=milestone.amount_paise,
                currency=milestone.currency,
                refunded_at=milestone.refunded_at or _utcnow(),
            )

        if milestone.status not in {
            MilestoneEscrowStatus.INITIATED.value,
            MilestoneEscrowStatus.HELD_IN_ESCROW.value,
            MilestoneEscrowStatus.DISPUTED.value,
        }:
            raise ValidationError(
                f"Cannot refund milestone in status '{milestone.status}'. Milestone has already settled."
            )

        rz_client = self.razorpay_client
        if rz_client is None:
            from app.core.config import Settings
            rz_client = RazorpayClientAdapter(Settings())

        if milestone.razorpay_transfer_id and milestone.status == MilestoneEscrowStatus.HELD_IN_ESCROW.value:
            rz_client.reverse_transfer(
                transfer_id=milestone.razorpay_transfer_id,
                amount_paise=milestone.developer_payout_paise,
                reverse_all=True,
            )

        milestone.status = MilestoneEscrowStatus.REFUNDED.value
        milestone.refunded_at = _utcnow()
        await self.session.commit()

        await self.telemetry_client.audit(
            actor_id=user.id,
            actor_role=user.role,
            action="PAYMENT_MILESTONE_REVERSED_REFUND",
            resource_type="escrow_milestone",
            resource_id=str(milestone.id),
            project_id=milestone.project_id,
            metadata={
                "task_id": str(milestone.task_id),
                "reason": payload.reason,
                "amount_paise": milestone.amount_paise,
                "currency": milestone.currency,
            },
            request_id=request_id,
        )

        return MilestoneRefundResponse(
            milestone_id=milestone.id,
            project_id=milestone.project_id,
            task_id=milestone.task_id,
            status=milestone.status,
            refunded_amount_paise=milestone.amount_paise,
            currency=milestone.currency,
            refunded_at=milestone.refunded_at,
        )

    async def process_razorpay_webhook(
        self,
        *,
        raw_body: bytes,
        signature: str,
        request_id: str | None,
    ) -> WebhookResponse:
        """Handle Razorpay webhooks (payment.captured, transfer.processed, transfer.reversed) with HMAC validation."""
        rz_client = self.razorpay_client
        if rz_client is None:
            from app.core.config import Settings
            rz_client = RazorpayClientAdapter(Settings())

        is_valid = rz_client.verify_webhook_signature(body=raw_body, signature=signature)
        if not is_valid:
            raise ValidationError("Invalid Razorpay webhook signature header.")

        try:
            event_data = json.loads(raw_body.decode("utf-8"))
        except Exception:
            raise ValidationError("Malformed JSON in webhook payload.")

        event_name = event_data.get("event", "")
        reconciled = False
        milestone_id = None

        if event_name == "payment.captured":
            pay_entity = event_data.get("payload", {}).get("payment", {}).get("entity", {})
            order_id = pay_entity.get("order_id")
            payment_id = pay_entity.get("id")
            if order_id:
                milestone = await self.repo.get_milestone_by_order_id(order_id)
                if milestone and milestone.status == MilestoneEscrowStatus.INITIATED.value:
                    milestone.status = MilestoneEscrowStatus.HELD_IN_ESCROW.value
                    milestone.razorpay_payment_id = payment_id
                    milestone.held_at = _utcnow()
                    await self.session.commit()
                    reconciled = True
                    milestone_id = str(milestone.id)

        elif event_name in {"transfer.processed", "settlement.processed"}:
            trf_entity = event_data.get("payload", {}).get("transfer", {}).get("entity", {})
            transfer_id = trf_entity.get("id")
            if transfer_id:
                milestone = await self.repo.get_milestone_by_transfer_id(transfer_id)
                if milestone and milestone.status == MilestoneEscrowStatus.HELD_IN_ESCROW.value:
                    milestone.status = MilestoneEscrowStatus.RELEASED.value
                    milestone.released_at = _utcnow()
                    await self.session.commit()
                    reconciled = True
                    milestone_id = str(milestone.id)

        elif event_name in {"transfer.reversed", "refund.processed"}:
            trf_entity = event_data.get("payload", {}).get("transfer", {}).get("entity", {})
            transfer_id = trf_entity.get("id")
            if transfer_id:
                milestone = await self.repo.get_milestone_by_transfer_id(transfer_id)
                if milestone and milestone.status != MilestoneEscrowStatus.REFUNDED.value:
                    milestone.status = MilestoneEscrowStatus.REFUNDED.value
                    milestone.refunded_at = _utcnow()
                    await self.session.commit()
                    reconciled = True
                    milestone_id = str(milestone.id)

        return WebhookResponse(
            status="ok",
            event=event_name,
            reconciled=reconciled,
            milestone_id=milestone_id,
        )

    async def get_developer_tds_summary(
        self,
        *,
        developer_id: uuid.UUID,
        financial_year: str | None = None,
    ) -> DeveloperTdsSummaryResponse:
        """Return cumulative annual Section 194-O TDS standing for a developer."""
        fy = financial_year or _current_financial_year()
        ledger = await self.repo.get_tds_ledger(
            developer_id=developer_id,
            financial_year=fy,
        )
        if ledger is None:
            return DeveloperTdsSummaryResponse(
                developer_id=developer_id,
                financial_year=fy,
                cumulative_gross_payout_paise=0,
                tds_threshold_crossed=False,
                total_tds_deducted_paise=0,
            )
        return DeveloperTdsSummaryResponse(
            developer_id=ledger.developer_id,
            financial_year=ledger.financial_year,
            cumulative_gross_payout_paise=ledger.cumulative_gross_payout_paise,
            tds_threshold_crossed=ledger.tds_threshold_crossed,
            total_tds_deducted_paise=ledger.total_tds_deducted_paise,
        )

    async def _find_milestone_by_identifier(self, identifier: str) -> EscrowMilestone | None:
        """Locate milestone by either its UUID or razorpay_order_id or razorpay_transfer_id."""
        milestone = None
        try:
            m_id = uuid.UUID(identifier)
            milestone = await self.repo.get_milestone_by_id(m_id)
        except ValueError:
            pass

        if milestone is None:
            milestone = await self.repo.get_milestone_by_order_id(identifier)
        if milestone is None:
            milestone = await self.repo.get_milestone_by_order_id(identifier)
        if milestone is None:
            milestone = await self.repo.get_milestone_by_transfer_id(identifier)
        return milestone

    async def execute_ai_guarded_auto_release(
        self,
        *,
        identifier: str,
        payload: AutoReleaseExecutionRequest,
        actor: AuthenticatedUser,
        request_id: str | None = None,
    ) -> AutoReleaseExecutionResponse:
        """
        AI-Guarded 5-Day Auto-Release:
        Protects freelancers from client ghosting.
        Auto-releases funds ONLY IF:
          1. Submission age >= 5.0 days
          2. GitHub Actions CI status is 100% Green (status == 'completed', conclusion == 'success')
          3. Gemini AI Audit Score >= 95 with zero security vulnerabilities, no mock code, and recommendation == 'APPROVED_FOR_RELEASE'
        """
        milestone = await self._find_milestone_by_identifier(identifier)
        if milestone is None:
            raise NotFoundError(f"Milestone not found for identifier '{identifier}'.")

        rejection_reasons: list[str] = []

        if payload.submission_age_days < 5.0:
            rejection_reasons.append(
                f"Submission age is {payload.submission_age_days:.1f} days; minimum 5 days required for auto-release."
            )

        ci_passed = (payload.ci_status == "completed" and payload.ci_conclusion == "success")
        if not ci_passed:
            rejection_reasons.append(
                f"CI status is not 100% green (status={payload.ci_status}, conclusion={payload.ci_conclusion})."
            )

        ai_passed = (
            payload.ai_audit_score >= 95
            and payload.security_vulnerabilities_count == 0
            and not payload.hollow_mock_code_detected
            and payload.ai_recommendation == "APPROVED_FOR_RELEASE"
        )
        if not ai_passed:
            if payload.ai_audit_score < 95:
                rejection_reasons.append(
                    f"AI audit score is {payload.ai_audit_score}/100, which is below the 95% threshold."
                )
            if payload.security_vulnerabilities_count > 0:
                rejection_reasons.append(
                    f"AI forensic scanner detected {payload.security_vulnerabilities_count} security vulnerabilities."
                )
            if payload.hollow_mock_code_detected:
                rejection_reasons.append("AI forensic scanner detected hollow mock code.")
            if payload.ai_recommendation != "APPROVED_FOR_RELEASE":
                rejection_reasons.append(
                    f"AI recommendation is '{payload.ai_recommendation}', not APPROVED_FOR_RELEASE."
                )

        if rejection_reasons:
            return AutoReleaseExecutionResponse(
                milestone_id=milestone.id,
                task_id=milestone.task_id,
                status=milestone.status,
                auto_released=False,
                rejection_reasons=rejection_reasons,
            )

        # Pre-conditions met! Release payout via standard release pipeline
        # System-authorized auto release can act on behalf of owner or platform admin
        admin_actor = AuthenticatedUser(
            id=actor.id,
            email=actor.email,
            full_name=actor.full_name,
            role="ADMIN",
            is_active=actor.is_active,
            is_verified=actor.is_verified,
            access_token=actor.access_token,
        )
        release_res = await self.release_milestone_payout(
            identifier=identifier,
            user=admin_actor,
            request_id=request_id,
        )

        return AutoReleaseExecutionResponse(
            milestone_id=release_res.milestone_id,
            task_id=release_res.task_id,
            status=release_res.status,
            auto_released=True,
            rejection_reasons=[],
            developer_payout_paise=release_res.developer_payout_paise,
            tds_deducted_paise=release_res.tds_deducted_paise,
            net_payout_paise=release_res.net_payout_paise,
            released_at=release_res.released_at,
        )




