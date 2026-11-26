"""Tests for GitHub Actions CI Webhooks and AI-Guarded PayRail Auto-Release."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import (
    ADMIN_TOKEN,
    FREELANCER_TOKEN,
    OWNER_TOKEN,
    PROJECT_ID,
    auth_headers,
)


@pytest.mark.asyncio
async def test_github_workflow_run_webhook(client: AsyncClient, app) -> None:
    secret = app.state.settings.GITHUB_WEBHOOK_SECRET
    payload = {
        "action": "completed",
        "workflow_run": {
            "id": 123456789,
            "workflow_id": 987654,
            "head_sha": "abc1234567890def",
            "head_branch": "main",
            "status": "completed",
            "conclusion": "success",
            "pull_requests": [{"number": 42}],
        },
        "repository": {
            "full_name": "codebridge/payment-repo",
        },
    }
    raw_body = json.dumps(payload).encode("utf-8")
    sig = "sha256=" + hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

    # 1. Invalid signature should be rejected with 401
    bad_resp = await client.post(
        "/api/v1/verification/webhooks/github/workflow-run",
        content=raw_body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": "sha256=invalidhex"},
    )
    assert bad_resp.status_code == 401

    # 2. Valid signature should successfully record the CI run
    resp = await client.post(
        "/api/v1/verification/webhooks/github/workflow-run",
        content=raw_body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["run_id"] == 123456789
    assert data["head_sha"] == "abc1234567890def"
    assert data["status"] == "completed"
    assert data["conclusion"] == "success"
    assert data["pr_number"] == 42


@pytest.mark.asyncio
async def test_payrail_auto_release_check(client: AsyncClient, app) -> None:
    task_id = uuid.uuid4()
    head_sha = "green-ci-sha-12345"
    secret = app.state.settings.GITHUB_WEBHOOK_SECRET

    # Ingest a green CI run
    ci_payload = {
        "action": "completed",
        "workflow_run": {
            "id": 999111,
            "workflow_id": 111,
            "head_sha": head_sha,
            "head_branch": "feature/fix",
            "status": "completed",
            "conclusion": "success",
            "pull_requests": [{"number": 10}],
        },
        "repository": {
            "full_name": "codebridge/demo",
        },
    }
    raw = json.dumps(ci_payload).encode("utf-8")
    sig = "sha256=" + hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    await client.post(
        "/api/v1/verification/webhooks/github/workflow-run",
        content=raw,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
    )

    # 1. Reject if submission age < 5 days
    check_young = await client.post(
        "/api/v1/verification/payrail/auto-release-check?ai_audit_score=98&ai_recommendation=APPROVED_FOR_RELEASE",
        json={
            "project_id": str(PROJECT_ID),
            "task_id": str(task_id),
            "head_sha": head_sha,
            "submission_age_days": 3.5,
        },
    )
    assert check_young.status_code == 200
    res_young = check_young.json()
    assert res_young["eligible_for_auto_release"] is False
    assert any("5 full calendar days required" in r for r in res_young["rejection_reasons"])

    # 2. Reject if AI score < 95
    check_low_ai = await client.post(
        "/api/v1/verification/payrail/auto-release-check?ai_audit_score=85&ai_recommendation=APPROVED_FOR_RELEASE",
        json={
            "project_id": str(PROJECT_ID),
            "task_id": str(task_id),
            "head_sha": head_sha,
            "submission_age_days": 5.2,
        },
    )
    assert check_low_ai.status_code == 200
    res_low_ai = check_low_ai.json()
    assert res_low_ai["eligible_for_auto_release"] is False
    assert any("below the 95% sovereign release threshold" in r for r in res_low_ai["rejection_reasons"])

    # 3. Reject if security vulnerability detected
    check_sec = await client.post(
        "/api/v1/verification/payrail/auto-release-check?ai_audit_score=98&ai_recommendation=SECURITY_ALERT&security_vulnerabilities_count=2",
        json={
            "project_id": str(PROJECT_ID),
            "task_id": str(task_id),
            "head_sha": head_sha,
            "submission_age_days": 6.0,
        },
    )
    assert check_sec.status_code == 200
    res_sec = check_sec.json()
    assert res_sec["eligible_for_auto_release"] is False
    assert any("security vulnerabilities" in r for r in res_sec["rejection_reasons"])

    # 4. Reject if hollow mock code detected
    check_hollow = await client.post(
        "/api/v1/verification/payrail/auto-release-check?ai_audit_score=96&ai_recommendation=APPROVED_FOR_RELEASE&hollow_mock_code_detected=true",
        json={
            "project_id": str(PROJECT_ID),
            "task_id": str(task_id),
            "head_sha": head_sha,
            "submission_age_days": 5.5,
        },
    )
    assert check_hollow.status_code == 200
    res_hollow = check_hollow.json()
    assert res_hollow["eligible_for_auto_release"] is False
    assert any("hollow or hardcoded mock code" in r for r in res_hollow["rejection_reasons"])

    # 5. Approve when 5+ days, 100% Green CI, 95%+ AI Score, 0 vulnerabilities, no mock code
    check_pass = await client.post(
        "/api/v1/verification/payrail/auto-release-check?ai_audit_score=97&ai_recommendation=APPROVED_FOR_RELEASE",
        json={
            "project_id": str(PROJECT_ID),
            "task_id": str(task_id),
            "head_sha": head_sha,
            "submission_age_days": 5.1,
        },
    )
    assert check_pass.status_code == 200
    res_pass = check_pass.json()
    assert res_pass["eligible_for_auto_release"] is True
    assert len(res_pass["rejection_reasons"]) == 0
    assert res_pass["ci_passed"] is True
    assert res_pass["ai_passed"] is True
