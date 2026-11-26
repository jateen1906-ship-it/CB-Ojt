"""Verification domain service handling issuance, cryptographic verification, public lookup, and revocation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.service_clients import (
    GitHubMetadataClient,
    ProjectClient,
    ReviewClient,
    TelemetryRelayClient,
)
from app.core.config import Settings
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.core.security import (
    AuthenticatedUser,
    canonicalize_payload,
    compute_sha256_hex,
    generate_public_verification_id,
    sign_payload_hmac_sha256,
    verify_payload_signature,
)
from app.models import (
    CIWorkflowRun,
    VerificationEvent,
    VerificationStatus,
    VerifiedWorkRecord,
)
from app.repositories.verification_repository import VerificationRepository
from app.schemas.verification import (
    CIWorkflowRunResponse,
    CreateVerificationRequest,
    FreelancerVerificationListResponse,
    MyVerifiedWorkListResponse,
    PayRailAutoReleaseCheckRequest,
    PayRailAutoReleaseCheckResponse,
    ProjectVerificationListResponse,
    PublicVerificationResponse,
    RevokeVerificationRequest,
    VerificationCheckResponse,
    VerificationEventResponse,
    VerifiedWorkRecordResponse,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class VerificationService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        settings: Settings,
        project_client: ProjectClient,
        review_client: ReviewClient,
        github_client: GitHubMetadataClient,
        telemetry_client: TelemetryRelayClient,
    ) -> None:
        self.session = session
        self.settings = settings
        self.repo = VerificationRepository(session)
        self.project_client = project_client
        self.review_client = review_client
        self.github_client = github_client
        self.telemetry_client = telemetry_client

    def _to_response(self, record: VerifiedWorkRecord) -> VerifiedWorkRecordResponse:
        _, sig_valid = verify_payload_signature(
            canonical_json=record.canonical_payload_json,
            expected_sha256=record.payload_sha256,
            signature_hex=record.signature_hex,
            secret=self.settings.VERIFICATION_SIGNING_SECRET,
        )
        is_active = record.status == VerificationStatus.ACTIVE.value
        return VerifiedWorkRecordResponse(
            id=record.id,
            public_verification_id=record.public_verification_id,
            project_id=record.project_id,
            submission_id=record.submission_id,
            owner_id=record.owner_id,
            freelancer_id=record.freelancer_id,
            project_title=record.project_title,
            submission_title=record.submission_title,
            repository_full_name=record.repository_full_name,
            commit_sha=record.commit_sha,
            status=record.status,
            approved_at=record.approved_at,
            issued_at=record.issued_at,
            revoked_at=record.revoked_at,
            revocation_reason=record.revocation_reason,
            payload_sha256=record.payload_sha256,
            signature_algorithm=record.signature_algorithm,
            signature_hex=record.signature_hex,
            key_id=record.key_id,
            signature_valid=sig_valid,
            is_valid=is_active and sig_valid,
            events=[VerificationEventResponse.model_validate(e) for e in record.events],
        )

    async def issue_record(
        self,
        *,
        payload: CreateVerificationRequest,
        actor: AuthenticatedUser,
        request_id: str | None,
    ) -> VerifiedWorkRecordResponse:
        if actor.role not in {"OWNER", "ADMIN"}:
            raise ForbiddenError("Only the project owner or admin can issue verified work records.")

        project = await self.project_client.get_project(
            project_id=payload.project_id,
            access_token=actor.access_token,
            request_id=request_id,
        )
        if actor.role == "OWNER" and project.owner_id != actor.id:
            raise ForbiddenError("Only the owner of this project can issue verification records.")

        approved_sub = await self.review_client.verify_approved_submission(
            project_id=payload.project_id,
            submission_id=payload.submission_id,
            access_token=actor.access_token,
            request_id=request_id,
        )

        existing = await self.repo.get_active_by_submission(payload.submission_id)
        if existing is not None:
            raise ConflictError(
                "An active verified work record already exists for this submission.",
                error_code="VERIFICATION_ALREADY_EXISTS",
            )

        repo_name = await self.github_client.get_repository_full_name(
            project_id=payload.project_id,
            access_token=actor.access_token,
            request_id=request_id,
        )

        record_id = uuid.uuid4()
        public_id = generate_public_verification_id()
        issued_at = _utcnow()
        canonical_payload = canonicalize_payload(
            {
                "record_id": str(record_id),
                "public_verification_id": public_id,
                "project_id": str(payload.project_id),
                "submission_id": str(approved_sub.id),
                "owner_id": str(project.owner_id),
                "freelancer_id": str(approved_sub.freelancer_id),
                "project_title": project.title,
                "submission_title": approved_sub.title,
                "repository_full_name": repo_name,
                "commit_sha": approved_sub.commit_sha,
                "approved_at": approved_sub.reviewed_at.isoformat(),
                "issued_at": issued_at.isoformat(),
                "key_id": self.settings.VERIFICATION_SIGNING_KEY_ID,
            }
        )
        payload_sha = compute_sha256_hex(canonical_payload)
        sig_hex = sign_payload_hmac_sha256(
            canonical_payload,
            self.settings.VERIFICATION_SIGNING_SECRET,
        )

        record = VerifiedWorkRecord(
            id=record_id,
            public_verification_id=public_id,
            project_id=payload.project_id,
            submission_id=approved_sub.id,
            owner_id=project.owner_id,
            freelancer_id=approved_sub.freelancer_id,
            project_title=project.title,
            submission_title=approved_sub.title,
            repository_full_name=repo_name,
            commit_sha=approved_sub.commit_sha,
            status=VerificationStatus.ACTIVE.value,
            approved_at=approved_sub.reviewed_at,
            issued_at=issued_at,
            canonical_payload_json=canonical_payload,
            payload_sha256=payload_sha,
            signature_algorithm="HMAC-SHA256",
            signature_hex=sig_hex,
            key_id=self.settings.VERIFICATION_SIGNING_KEY_ID,
            created_at=issued_at,
            updated_at=issued_at,
        )
        self.repo.add_record(record)
        self.repo.add_event(
            VerificationEvent(
                record=record,
                actor_id=actor.id,
                event_type="RECORD_ISSUED",
                detail=f"Verified work record {public_id} issued for approved submission {approved_sub.id}.",
                request_id=request_id,
                created_at=issued_at,
            )
        )
        await self.session.commit()

        created = await self.repo.get_by_id(record_id)
        assert created is not None

        await self.telemetry_client.notify(
            user_id=approved_sub.freelancer_id,
            event_type="VERIFICATION_ISSUED",
            title="Verified Work Record Issued",
            message=f"Cryptographically signed verification record {public_id} was issued for '{project.title}'.",
            project_id=payload.project_id,
            idempotency_key=f"verification-issued-{record_id}",
            request_id=request_id,
        )
        await self.telemetry_client.audit(
            actor_id=actor.id,
            actor_role=actor.role,
            action="VERIFICATION_ISSUED",
            resource_type="verified_work_record",
            resource_id=str(record_id),
            project_id=payload.project_id,
            metadata={"public_verification_id": public_id, "submission_id": str(approved_sub.id)},
            request_id=request_id,
        )
        return self._to_response(created)

    async def get_public_record(self, public_verification_id: str) -> PublicVerificationResponse:
        record = await self.repo.get_by_public_id(public_verification_id)
        if record is None:
            raise NotFoundError(
                "No verified work record matched the supplied verification ID.",
                error_code="VERIFICATION_NOT_FOUND",
            )
        _, sig_valid = verify_payload_signature(
            canonical_json=record.canonical_payload_json,
            expected_sha256=record.payload_sha256,
            signature_hex=record.signature_hex,
            secret=self.settings.VERIFICATION_SIGNING_SECRET,
        )
        is_valid = record.status == VerificationStatus.ACTIVE.value and sig_valid
        return PublicVerificationResponse(
            public_verification_id=record.public_verification_id,
            status=record.status,
            is_valid=is_valid,
            signature_valid=sig_valid,
            project_id=record.project_id,
            project_title=record.project_title,
            submission_title=record.submission_title,
            freelancer_id=record.freelancer_id,
            repository_full_name=record.repository_full_name,
            commit_sha=record.commit_sha,
            approved_at=record.approved_at,
            issued_at=record.issued_at,
            revoked_at=record.revoked_at,
            revocation_reason=record.revocation_reason,
            payload_sha256=record.payload_sha256,
            signature_algorithm=record.signature_algorithm,
            key_id=record.key_id,
        )

    async def get_record(
        self,
        *,
        record_id: uuid.UUID,
        user: AuthenticatedUser,
    ) -> VerifiedWorkRecordResponse:
        record = await self.repo.get_by_id(record_id)
        if record is None:
            raise NotFoundError()
        if user.role != "ADMIN" and user.id not in {record.owner_id, record.freelancer_id}:
            raise ForbiddenError("You do not have permission to view this verification record.")
        return self._to_response(record)

    async def list_project_records(
        self,
        *,
        project_id: uuid.UUID,
        user: AuthenticatedUser,
        request_id: str | None,
    ) -> ProjectVerificationListResponse:
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
            raise ForbiddenError("You do not have permission to view project verification records.")
        records = await self.repo.list_by_project(project_id)
        return ProjectVerificationListResponse(
            project_id=project_id,
            total=len(records),
            items=[self._to_response(r) for r in records],
        )

    def _to_public_response(self, record: VerifiedWorkRecord) -> PublicVerificationResponse:
        _, sig_valid = verify_payload_signature(
            canonical_json=record.canonical_payload_json,
            expected_sha256=record.payload_sha256,
            signature_hex=record.signature_hex,
            secret=self.settings.VERIFICATION_SIGNING_SECRET,
        )
        is_valid = record.status == VerificationStatus.ACTIVE.value and sig_valid
        return PublicVerificationResponse(
            public_verification_id=record.public_verification_id,
            status=record.status,
            is_valid=is_valid,
            signature_valid=sig_valid,
            project_id=record.project_id,
            project_title=record.project_title,
            submission_title=record.submission_title,
            freelancer_id=record.freelancer_id,
            repository_full_name=record.repository_full_name,
            commit_sha=record.commit_sha,
            approved_at=record.approved_at,
            issued_at=record.issued_at,
            revoked_at=record.revoked_at,
            revocation_reason=record.revocation_reason,
            payload_sha256=record.payload_sha256,
            signature_algorithm=record.signature_algorithm,
            key_id=record.key_id,
        )

    async def list_my_records(self, *, user: AuthenticatedUser) -> MyVerifiedWorkListResponse:
        records = await self.repo.list_by_freelancer(user.id, active_only=False)
        return MyVerifiedWorkListResponse(
            user_id=user.id,
            total=len(records),
            items=[self._to_response(r) for r in records],
        )

    async def list_freelancer_public_records(
        self,
        *,
        freelancer_id: uuid.UUID,
    ) -> FreelancerVerificationListResponse:
        records = await self.repo.list_by_freelancer(freelancer_id, active_only=True)
        return FreelancerVerificationListResponse(
            freelancer_id=freelancer_id,
            total=len(records),
            items=[self._to_public_response(r) for r in records],
        )

    async def verify_record(self, *, record_id: uuid.UUID) -> VerificationCheckResponse:
        record = await self.repo.get_by_id(record_id)
        if record is None:
            raise NotFoundError()
        hash_ok, sig_valid = verify_payload_signature(
            canonical_json=record.canonical_payload_json,
            expected_sha256=record.payload_sha256,
            signature_hex=record.signature_hex,
            secret=self.settings.VERIFICATION_SIGNING_SECRET,
        )
        is_valid = record.status == VerificationStatus.ACTIVE.value and sig_valid
        return VerificationCheckResponse(
            record_id=record.id,
            public_verification_id=record.public_verification_id,
            status=record.status,
            payload_hash_matches=hash_ok,
            signature_valid=sig_valid,
            is_valid=is_valid,
            checked_at=_utcnow(),
        )

    async def revoke_record(
        self,
        *,
        record_id: uuid.UUID,
        payload: RevokeVerificationRequest,
        actor: AuthenticatedUser,
        request_id: str | None,
    ) -> VerifiedWorkRecordResponse:
        if actor.role not in {"OWNER", "ADMIN"}:
            raise ForbiddenError("Only the project owner or admin may revoke verification records.")

        record = await self.repo.get_by_id(record_id)
        if record is None:
            raise NotFoundError()
        if actor.role == "OWNER" and record.owner_id != actor.id:
            raise ForbiddenError("Only the project owner or admin may revoke this verification record.")
        if record.status != VerificationStatus.ACTIVE.value:
            raise ConflictError(
                f"Record is already in {record.status} status.",
                error_code="VERIFICATION_ALREADY_REVOKED",
            )

        now = _utcnow()
        record.status = payload.status
        record.revoked_at = now
        record.revoked_by = actor.id
        record.revocation_reason = payload.reason
        record.updated_at = now
        self.repo.add_event(
            VerificationEvent(
                record_id=record.id,
                actor_id=actor.id,
                event_type=f"RECORD_{payload.status}",
                detail=payload.reason,
                request_id=request_id,
                created_at=now,
            )
        )
        await self.session.commit()

        updated = await self.repo.get_by_id(record_id)
        assert updated is not None
        await self.telemetry_client.audit(
            actor_id=actor.id,
            actor_role=actor.role,
            action=f"VERIFICATION_{payload.status}",
            resource_type="verified_work_record",
            resource_id=str(record_id),
            project_id=record.project_id,
            metadata={"reason": payload.reason},
            request_id=request_id,
        )
        return self._to_response(updated)

    async def record_github_workflow_run(
        self,
        *,
        payload: dict,
    ) -> CIWorkflowRun:
        """Process and persist GitHub Actions workflow_run webhook event."""
        run_data = payload.get("workflow_run", {})
        repo_data = payload.get("repository", {})
        head_commit = run_data.get("head_commit", {})
        pull_requests = run_data.get("pull_requests", [])
        pr_number = pull_requests[0].get("number") if pull_requests else None

        ci_run = CIWorkflowRun(
            repository_full_name=repo_data.get("full_name") or "unknown/repo",
            workflow_id=run_data.get("workflow_id", 0),
            run_id=run_data.get("id", 0),
            head_sha=run_data.get("head_sha") or head_commit.get("id") or "",
            head_branch=run_data.get("head_branch"),
            status=run_data.get("status", "unknown"),
            conclusion=run_data.get("conclusion"),
            event=payload.get("action", "workflow_run"),
            pr_number=pr_number,
            raw_payload_json=str(payload),
            created_at=_utcnow(),
            completed_at=_utcnow() if run_data.get("conclusion") else None,
        )
        self.repo.add_ci_workflow_run(ci_run)
        await self.session.commit()
        return ci_run

    async def evaluate_payrail_auto_release(
        self,
        *,
        request_data: PayRailAutoReleaseCheckRequest,
        ai_audit_score: int | None = None,
        ai_recommendation: str | None = None,
        hollow_mock_code_detected: bool = False,
        security_vulnerabilities_count: int = 0,
    ) -> PayRailAutoReleaseCheckResponse:
        """
        AI-Guarded 5-Day Auto-Release Guard.
        Auto-release is permitted ONLY IF:
          1. Task age >= 5.0 days since submission.
          2. GitHub Actions CI status is 100% Green (status == 'completed', conclusion == 'success').
          3. Gemini AI Audit Score >= 95 with zero security vulnerabilities and hollow_mock_code_detected == False.
        """
        rejection_reasons: list[str] = []

        # 1. 5-day age check
        if request_data.submission_age_days < 5.0:
            rejection_reasons.append(
                f"Submission age is {request_data.submission_age_days:.1f} days; 5 full calendar days required."
            )

        # 2. CI Run Verification
        ci_run = await self.repo.get_latest_ci_run_by_sha(request_data.head_sha)
        ci_status = ci_run.status if ci_run else None
        ci_conclusion = ci_run.conclusion if ci_run else None
        ci_passed = bool(
            ci_run
            and ci_run.status == "completed"
            and ci_run.conclusion == "success"
        )
        if not ci_passed:
            rejection_reasons.append(
                f"GitHub Actions CI check failed or not green (status={ci_status}, conclusion={ci_conclusion})."
            )

        # 3. AI Audit Guard
        score = ai_audit_score if ai_audit_score is not None else 0
        ai_passed = (
            score >= 95
            and security_vulnerabilities_count == 0
            and not hollow_mock_code_detected
            and ai_recommendation == "APPROVED_FOR_RELEASE"
        )
        if not ai_passed:
            if score < 95:
                rejection_reasons.append(
                    f"Gemini AI audit score is {score}/100, which is below the 95% sovereign release threshold."
                )
            if security_vulnerabilities_count > 0:
                rejection_reasons.append(
                    f"AI forensic scanner detected {security_vulnerabilities_count} critical security vulnerabilities."
                )
            if hollow_mock_code_detected:
                rejection_reasons.append("AI forensic scanner detected hollow or hardcoded mock code stubs.")
            if ai_recommendation != "APPROVED_FOR_RELEASE":
                rejection_reasons.append(f"AI recommendation is '{ai_recommendation}', release not approved.")

        eligible = len(rejection_reasons) == 0

        return PayRailAutoReleaseCheckResponse(
            project_id=request_data.project_id,
            task_id=request_data.task_id,
            submission_age_days=request_data.submission_age_days,
            eligible_for_auto_release=eligible,
            rejection_reasons=rejection_reasons,
            ci_status=ci_status,
            ci_conclusion=ci_conclusion,
            ci_passed=ci_passed,
            ai_score=score,
            ai_passed=ai_passed,
            ai_recommendation=ai_recommendation,
            hollow_mock_code_detected=hollow_mock_code_detected,
            security_vulnerabilities_count=security_vulnerabilities_count,
        )


