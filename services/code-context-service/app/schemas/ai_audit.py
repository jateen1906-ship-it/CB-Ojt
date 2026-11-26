"""Pydantic schemas for AI Forensic Audit and Sovereign PayRail verification."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RequirementAudit(BaseModel):
    """Evaluation of an individual task/PRD requirement against code diff evidence."""

    model_config = ConfigDict(extra="forbid")

    requirement_id: str
    description: str
    implemented: bool
    evidence_line_range: str = Field(default="N/A", description="Line range or file proof")
    confidence: float = Field(ge=0.0, le=1.0, default=0.95)


class AuditReportCard(BaseModel):
    """Objective, structured forensic audit card generated for the project owner."""

    model_config = ConfigDict(from_attributes=True)

    project_id: uuid.UUID
    pr_number: int
    overall_score: int = Field(ge=0, le=100, description="Comprehensive confidence score out of 100")
    requirements_breakdown: list[RequirementAudit]
    security_vulnerabilities: list[str] = Field(default_factory=list)
    hollow_mock_code_detected: bool = False
    performance_complexity_score: int = Field(ge=0, le=100, default=90)
    recommendation: Literal["APPROVED_FOR_RELEASE", "REVISION_REQUIRED", "SECURITY_ALERT"]
    executive_summary_for_client: str


class AuditPRRequest(BaseModel):
    """Payload to trigger an AI Forensic Audit on a pull request."""

    model_config = ConfigDict(extra="forbid")

    project_id: uuid.UUID
    pr_number: int = Field(default=1, ge=1)
    pr_diff: str = Field(..., min_length=5, description="Git unified diff or code solution")
    prd_spec: str = Field(..., min_length=5, description="Client PRD requirements or task specifications")
    task_id: uuid.UUID | None = None
