"""Pydantic schemas for Payment Service simulated escrow lifecycle."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class CreateEscrowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Decimal | None = Field(default=None, gt=Decimal(0))
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    fund_immediately: bool = False
    hold_immediately: bool = False
    notes: str | None = Field(default=None, max_length=500)


class FundEscrowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payment_method_reference: str = Field(default="sim_card_visa_4242", min_length=3, max_length=128)
    hold_if_assigned: bool = True
    notes: str | None = Field(default=None, max_length=500)


class EscrowActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=500)


class RefundEscrowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(..., min_length=5, max_length=1000)
    process_immediately: bool = True


class EscrowTransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    escrow_id: uuid.UUID
    project_id: uuid.UUID
    actor_id: uuid.UUID
    transaction_type: str
    amount: Decimal
    currency: str
    idempotency_key: str | None = None
    reference_id: str | None = None
    notes: str | None = None
    created_at: datetime


class PaymentEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    actor_id: uuid.UUID
    from_status: str | None = None
    to_status: str
    detail: str | None = None
    request_id: str | None = None
    created_at: datetime


class EscrowPaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    owner_id: uuid.UUID
    freelancer_id: uuid.UUID | None = None
    amount: Decimal
    currency: str
    status: str
    funding_reference: str | None = None
    release_reference: str | None = None
    refund_reference: str | None = None
    funded_at: datetime | None = None
    held_at: datetime | None = None
    released_at: datetime | None = None
    refunded_at: datetime | None = None
    cancelled_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    transactions: list[EscrowTransactionResponse] = Field(default_factory=list)
    events: list[PaymentEventResponse] = Field(default_factory=list)


class EscrowListResponse(BaseModel):
    project_id: uuid.UUID
    total: int
    items: list[EscrowPaymentResponse]


class MilestoneOrderCreateRequest(BaseModel):
    """Payload for funding a project milestone via Razorpay Route."""

    model_config = ConfigDict(extra="forbid")

    project_id: uuid.UUID
    task_id: uuid.UUID
    developer_id: uuid.UUID
    amount_paise: int = Field(..., gt=100, description="Milestone amount in paise (e.g. 500000 = ₹5,000)")
    currency: str = Field(default="INR", min_length=3, max_length=8)
    milestone_title: str | None = Field(default=None, max_length=255)
    developer_account_id: str | None = Field(
        default=None,
        description="Linked developer sub-account or VPA in Razorpay Route",
    )
    idempotency_key: uuid.UUID = Field(default_factory=uuid.uuid4)


class MilestoneOrderResponse(BaseModel):
    """Checkout response payload returned to client to launch Razorpay Checkout."""

    model_config = ConfigDict(from_attributes=True)

    milestone_id: uuid.UUID
    project_id: uuid.UUID
    task_id: uuid.UUID
    owner_id: uuid.UUID
    developer_id: uuid.UUID
    amount_paise: int
    platform_fee_paise: int
    developer_payout_paise: int
    currency: str
    razorpay_order_id: str
    razorpay_key_id: str
    status: str
    idempotency_key: uuid.UUID
    created_at: datetime


class MilestoneVerifyRequest(BaseModel):
    """HMAC signature verification payload posted upon successful Razorpay modal checkout."""

    model_config = ConfigDict(extra="forbid")

    razorpay_order_id: str = Field(..., min_length=3, max_length=64)
    razorpay_payment_id: str = Field(..., min_length=3, max_length=64)
    razorpay_signature: str = Field(..., min_length=10, max_length=128)


class MilestoneVerifyResponse(BaseModel):
    """Confirmation payload returned after verifying signature and locking funds in RBI Nodal Escrow."""

    model_config = ConfigDict(from_attributes=True)

    milestone_id: uuid.UUID
    project_id: uuid.UUID
    task_id: uuid.UUID
    status: str
    amount_paise: int
    currency: str
    razorpay_order_id: str
    razorpay_payment_id: str
    held_at: datetime


class MilestoneReleaseResponse(BaseModel):
    """Payload returned upon releasing a milestone payout to the developer."""

    model_config = ConfigDict(from_attributes=True)

    milestone_id: uuid.UUID
    project_id: uuid.UUID
    task_id: uuid.UUID
    developer_id: uuid.UUID
    status: str
    developer_payout_paise: int
    tds_deducted_paise: int
    net_payout_paise: int
    currency: str
    released_at: datetime


class MilestoneRefundRequest(BaseModel):
    """Payload for reversing an escrow milestone back to the client."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(..., min_length=3, max_length=500)


class MilestoneRefundResponse(BaseModel):
    """Payload returned upon reversing held funds."""

    model_config = ConfigDict(from_attributes=True)

    milestone_id: uuid.UUID
    project_id: uuid.UUID
    task_id: uuid.UUID
    status: str
    refunded_amount_paise: int
    currency: str
    refunded_at: datetime


class WebhookResponse(BaseModel):
    """Acknowledgment payload returned to Razorpay Webhooks."""

    status: str
    event: str
    reconciled: bool
    milestone_id: str | None = None


class DeveloperTdsSummaryResponse(BaseModel):
    """Cumulative annual Section 194-O TDS summary for a developer."""

    model_config = ConfigDict(from_attributes=True)

    developer_id: uuid.UUID
    financial_year: str
    cumulative_gross_payout_paise: int
    tds_threshold_crossed: bool
    total_tds_deducted_paise: int


class AutoReleaseExecutionRequest(BaseModel):
    """Payload to trigger an AI-guarded auto-release for an escrow milestone."""

    model_config = ConfigDict(extra="forbid")

    submission_age_days: float = Field(..., ge=0.0)
    ci_status: str = Field(default="completed")
    ci_conclusion: str = Field(default="success")
    ai_audit_score: int = Field(..., ge=0, le=100)
    ai_recommendation: str = Field(...)
    hollow_mock_code_detected: bool = False
    security_vulnerabilities_count: int = 0


class AutoReleaseExecutionResponse(BaseModel):
    """Result of attempting an AI-guarded auto-release."""

    milestone_id: uuid.UUID
    task_id: uuid.UUID
    status: str
    auto_released: bool
    rejection_reasons: list[str]
    developer_payout_paise: int | None = None
    tds_deducted_paise: int | None = None
    net_payout_paise: int | None = None
    released_at: datetime | None = None




