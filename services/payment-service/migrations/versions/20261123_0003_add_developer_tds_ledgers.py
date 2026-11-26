"""Add developer_tds_ledgers table for Section 194-O TDS compliance.

Revision ID: 20261123_0003
Revises: 20261123_0002
Create Date: 2026-11-23 22:08:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261123_0003"
down_revision: str | Sequence[str] | None = "20261123_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "developer_tds_ledgers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("developer_id", sa.Uuid(), nullable=False),
        sa.Column("financial_year", sa.String(length=16), nullable=False),
        sa.Column("cumulative_gross_payout_paise", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("tds_threshold_crossed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("total_tds_deducted_paise", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("developer_id", "financial_year", name="uq_dev_tds_developer_fy"),
    )
    op.create_index("ix_developer_tds_ledgers_developer_id", "developer_tds_ledgers", ["developer_id"])


def downgrade() -> None:
    op.drop_index("ix_developer_tds_ledgers_developer_id", table_name="developer_tds_ledgers")
    op.drop_table("developer_tds_ledgers")
