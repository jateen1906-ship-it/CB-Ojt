"""Add ci_workflow_runs table for GitHub Actions PayRail verification.

Revision ID: 20261123_0002
Revises: 20261112_0001
Create Date: 2026-11-23 22:25:00
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
        "ci_workflow_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repository_full_name", sa.String(length=255), nullable=False),
        sa.Column("workflow_id", sa.BigInteger(), nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("head_sha", sa.String(length=64), nullable=False),
        sa.Column("head_branch", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=48), nullable=False),
        sa.Column("conclusion", sa.String(length=48), nullable=True),
        sa.Column("event", sa.String(length=48), nullable=False, server_default="workflow_run"),
        sa.Column("pr_number", sa.Integer(), nullable=True),
        sa.Column("raw_payload_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ci_workflow_runs")),
    )
    op.create_index(op.f("ix_ci_workflow_runs_repository_full_name"), "ci_workflow_runs", ["repository_full_name"])
    op.create_index(op.f("ix_ci_workflow_runs_run_id"), "ci_workflow_runs", ["run_id"])
    op.create_index(op.f("ix_ci_workflow_runs_head_sha"), "ci_workflow_runs", ["head_sha"])
    op.create_index(op.f("ix_ci_workflow_runs_pr_number"), "ci_workflow_runs", ["pr_number"])


def downgrade() -> None:
    op.drop_index(op.f("ix_ci_workflow_runs_pr_number"), table_name="ci_workflow_runs")
    op.drop_index(op.f("ix_ci_workflow_runs_head_sha"), table_name="ci_workflow_runs")
    op.drop_index(op.f("ix_ci_workflow_runs_run_id"), table_name="ci_workflow_runs")
    op.drop_index(op.f("ix_ci_workflow_runs_repository_full_name"), table_name="ci_workflow_runs")
    op.drop_table("ci_workflow_runs")
