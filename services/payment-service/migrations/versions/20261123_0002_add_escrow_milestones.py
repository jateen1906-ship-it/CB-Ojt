"""Add escrow_milestones table for Razorpay Route Sovereign PayRail.

Revision ID: 20261123_0002
Revises: 20261112_0001
Create Date: 2026-11-23 21:55:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261123_0002"
down_revision: str | Sequence[str] | None = "20261112_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "escrow_milestones",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("developer_id", sa.Uuid(), nullable=False),
        sa.Column("amount_paise", sa.BigInteger(), nullable=False),
        sa.Column("platform_fee_paise", sa.BigInteger(), nullable=False),
        sa.Column("developer_payout_paise", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="INR"),
        sa.Column("razorpay_order_id", sa.String(length=64), nullable=False),
        sa.Column("razorpay_payment_id", sa.String(length=64), nullable=True),
        sa.Column("razorpay_transfer_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="INITIATED"),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("ai_audit_score", sa.Integer(), nullable=True),
        sa.Column("ai_audit_recommendation", sa.String(length=32), nullable=True),
        sa.Column("held_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "task_id", name="uq_escrow_milestones_project_task"),
        sa.UniqueConstraint("idempotency_key", name="uq_escrow_milestones_idempotency_key"),
        sa.UniqueConstraint("razorpay_order_id", name="uq_escrow_milestones_razorpay_order_id"),
        sa.UniqueConstraint("razorpay_payment_id", name="uq_escrow_milestones_razorpay_payment_id"),
        sa.UniqueConstraint("razorpay_transfer_id", name="uq_escrow_milestones_razorpay_transfer_id"),
    )
    op.create_index("ix_escrow_milestones_project_id", "escrow_milestones", ["project_id"])
    op.create_index("ix_escrow_milestones_task_id", "escrow_milestones", ["task_id"])
    op.create_index("ix_escrow_milestones_owner_id", "escrow_milestones", ["owner_id"])
    op.create_index("ix_escrow_milestones_developer_id", "escrow_milestones", ["developer_id"])
    op.create_index("ix_escrow_milestones_status", "escrow_milestones", ["status"])


def downgrade() -> None:
    op.drop_index("ix_escrow_milestones_status", table_name="escrow_milestones")
    op.drop_index("ix_escrow_milestones_developer_id", table_name="escrow_milestones")
    op.drop_index("ix_escrow_milestones_owner_id", table_name="escrow_milestones")
    op.drop_index("ix_escrow_milestones_task_id", table_name="escrow_milestones")
    op.drop_index("ix_escrow_milestones_project_id", table_name="escrow_milestones")
    op.drop_table("escrow_milestones")
