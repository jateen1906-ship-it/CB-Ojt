"""Tests for CodeBridge Sovereign PayRail (Razorpay Route Milestone Escrow)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient

from tests.conftest import (
    ADMIN_TOKEN,
    FREELANCER_ID,
    FREELANCER_TOKEN,
    OTHER_OWNER_TOKEN,
    OWNER_ID,
    OWNER_TOKEN,
    PROJECT_ID,
    auth_headers,
)


@pytest.mark.asyncio
async def test_create_milestone_order_success(client: AsyncClient, app: Any) -> None:
    """Project owner creates a milestone order locked on-hold in RBI Nodal Escrow."""
    task_id = uuid.uuid4()
    amount_paise = 500000  # ₹5,000

    payload = {
        "project_id": str(PROJECT_ID),
        "task_id": str(task_id),
        "developer_id": str(FREELANCER_ID),
        "amount_paise": amount_paise,
        "currency": "INR",
        "milestone_title": "Implement OAuth Microservice",
        "idempotency_key": str(uuid.uuid4()),
    }

    res = await client.post(
        "/api/v1/payment/orders",
        json=payload,
        headers=auth_headers(OWNER_TOKEN),
    )
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["amount_paise"] == 500000
    assert data["platform_fee_paise"] == 50000  # 10%
    assert data["developer_payout_paise"] == 450000  # 90%
    assert data["currency"] == "INR"
    assert data["status"] == "INITIATED"
    assert data["razorpay_order_id"].startswith("order_")
    assert "razorpay_key_id" in data


@pytest.mark.asyncio
async def test_create_milestone_order_forbidden_for_non_owner(client: AsyncClient) -> None:
    """Non-owner user cannot create an escrow order for someone else's project."""
    payload = {
        "project_id": str(PROJECT_ID),
        "task_id": str(uuid.uuid4()),
        "developer_id": str(FREELANCER_ID),
        "amount_paise": 200000,
        "currency": "INR",
        "idempotency_key": str(uuid.uuid4()),
    }

    res = await client.post(
        "/api/v1/payment/orders",
        json=payload,
        headers=auth_headers(OTHER_OWNER_TOKEN),
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_milestone_order_idempotency(client: AsyncClient) -> None:
    """Sending identical idempotency_key returns original order without duplication."""
    idem_key = str(uuid.uuid4())
    task_id = uuid.uuid4()
    payload = {
        "project_id": str(PROJECT_ID),
        "task_id": str(task_id),
        "developer_id": str(FREELANCER_ID),
        "amount_paise": 300000,
        "currency": "INR",
        "idempotency_key": idem_key,
    }

    res1 = await client.post("/api/v1/payment/orders", json=payload, headers=auth_headers(OWNER_TOKEN))
    assert res1.status_code == 201
    order1 = res1.json()

    # Retry same payload
    res2 = await client.post("/api/v1/payment/orders", json=payload, headers=auth_headers(OWNER_TOKEN))
    assert res2.status_code == 201
    order2 = res2.json()

    assert order1["milestone_id"] == order2["milestone_id"]
    assert order1["razorpay_order_id"] == order2["razorpay_order_id"]


@pytest.mark.asyncio
async def test_verify_milestone_payment_success(client: AsyncClient, app: Any) -> None:
    """Valid HMAC signature moves milestone status to HELD_IN_ESCROW."""
    task_id = uuid.uuid4()
    create_res = await client.post(
        "/api/v1/payment/orders",
        json={
            "project_id": str(PROJECT_ID),
            "task_id": str(task_id),
            "developer_id": str(FREELANCER_ID),
            "amount_paise": 500000,
            "currency": "INR",
            "idempotency_key": str(uuid.uuid4()),
        },
        headers=auth_headers(OWNER_TOKEN),
    )
    assert create_res.status_code == 201
    order_data = create_res.json()
    rz_order_id = order_data["razorpay_order_id"]
    payment_id = f"pay_{uuid.uuid4().hex[:14]}"

    # Use client adapter helper to produce authentic HMAC-SHA256 signature
    rz_adapter = app.state.razorpay_client
    valid_sig = rz_adapter.generate_mock_signature(rz_order_id, payment_id)

    verify_payload = {
        "razorpay_order_id": rz_order_id,
        "razorpay_payment_id": payment_id,
        "razorpay_signature": valid_sig,
    }

    verify_res = await client.post(
        "/api/v1/payment/verify",
        json=verify_payload,
        headers=auth_headers(OWNER_TOKEN),
    )
    assert verify_res.status_code == 200, verify_res.text
    verify_data = verify_res.json()
    assert verify_data["status"] == "HELD_IN_ESCROW"
    assert verify_data["razorpay_order_id"] == rz_order_id
    assert verify_data["razorpay_payment_id"] == payment_id
    assert verify_data["amount_paise"] == 500000
    assert "held_at" in verify_data


@pytest.mark.asyncio
async def test_verify_milestone_payment_invalid_signature(client: AsyncClient) -> None:
    """Invalid HMAC signature returns 422 Unprocessable Entity / Validation Error."""
    task_id = uuid.uuid4()
    create_res = await client.post(
        "/api/v1/payment/orders",
        json={
            "project_id": str(PROJECT_ID),
            "task_id": str(task_id),
            "developer_id": str(FREELANCER_ID),
            "amount_paise": 100000,
            "currency": "INR",
            "idempotency_key": str(uuid.uuid4()),
        },
        headers=auth_headers(OWNER_TOKEN),
    )
    assert create_res.status_code == 201
    rz_order_id = create_res.json()["razorpay_order_id"]

    verify_res = await client.post(
        "/api/v1/payment/verify",
        json={
            "razorpay_order_id": rz_order_id,
            "razorpay_payment_id": "pay_fake_99999",
            "razorpay_signature": "invalid_forged_signature_12345",
        },
        headers=auth_headers(OWNER_TOKEN),
    )
    assert verify_res.status_code == 422


@pytest.mark.asyncio
async def test_release_milestone_payout_instant(client: AsyncClient, app: Any) -> None:
    """Project owner releases milestone payout, lifting nodal hold instantly via IMPS/UPI."""
    task_id = uuid.uuid4()
    # 1. Create order
    create_res = await client.post(
        "/api/v1/payment/orders",
        json={
            "project_id": str(PROJECT_ID),
            "task_id": str(task_id),
            "developer_id": str(FREELANCER_ID),
            "amount_paise": 500000,
            "currency": "INR",
            "idempotency_key": str(uuid.uuid4()),
        },
        headers=auth_headers(OWNER_TOKEN),
    )
    assert create_res.status_code == 201
    order_data = create_res.json()
    rz_order_id = order_data["razorpay_order_id"]
    milestone_id = order_data["milestone_id"]

    # 2. Verify payment into HELD_IN_ESCROW
    payment_id = f"pay_{uuid.uuid4().hex[:14]}"
    sig = app.state.razorpay_client.generate_mock_signature(rz_order_id, payment_id)
    verify_res = await client.post(
        "/api/v1/payment/verify",
        json={
            "razorpay_order_id": rz_order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": sig,
        },
        headers=auth_headers(OWNER_TOKEN),
    )
    assert verify_res.status_code == 200

    # 3. Release payout
    rel_res = await client.patch(
        f"/api/v1/payment/transfers/{milestone_id}/release",
        headers=auth_headers(OWNER_TOKEN),
    )
    assert rel_res.status_code == 200, rel_res.text
    rel_data = rel_res.json()
    assert rel_data["status"] == "RELEASED"
    assert rel_data["developer_payout_paise"] == 450000
    assert rel_data["net_payout_paise"] == 450000
    assert "released_at" in rel_data


@pytest.mark.asyncio
async def test_section_194_o_tds_deduction_above_threshold(client: AsyncClient, app: Any) -> None:
    """Cumulative payouts exceeding ₹5 Lakhs trigger 1% Section 194-O TDS deduction."""
    dev_id = uuid.uuid4()

    # Milestone 1: ₹5,00,000 gross (payout ₹4,50,000 = 45,000,000 paise - below 50M threshold)
    create1 = await client.post(
        "/api/v1/payment/orders",
        json={
            "project_id": str(PROJECT_ID),
            "task_id": str(uuid.uuid4()),
            "developer_id": str(dev_id),
            "amount_paise": 50000000,  # ₹5,00,000
            "currency": "INR",
            "idempotency_key": str(uuid.uuid4()),
        },
        headers=auth_headers(OWNER_TOKEN),
    )
    assert create1.status_code == 201
    m1_data = create1.json()

    # Verify M1
    p1 = f"pay_{uuid.uuid4().hex[:14]}"
    sig1 = app.state.razorpay_client.generate_mock_signature(m1_data["razorpay_order_id"], p1)
    await client.post(
        "/api/v1/payment/verify",
        json={"razorpay_order_id": m1_data["razorpay_order_id"], "razorpay_payment_id": p1, "razorpay_signature": sig1},
        headers=auth_headers(OWNER_TOKEN),
    )

    # Release M1 (below 50,000,000 threshold: gross payout = 45,000,000)
    rel1 = await client.patch(
        f"/api/v1/payment/transfers/{m1_data['milestone_id']}/release",
        headers=auth_headers(OWNER_TOKEN),
    )
    assert rel1.status_code == 200
    assert rel1.json()["tds_deducted_paise"] == 0

    # Milestone 2: Another ₹1,00,000 gross (payout ₹90,000 = 9,000,000 paise -> total 54,000,000 crosses threshold!)
    create2 = await client.post(
        "/api/v1/payment/orders",
        json={
            "project_id": str(PROJECT_ID),
            "task_id": str(uuid.uuid4()),
            "developer_id": str(dev_id),
            "amount_paise": 10000000,  # ₹1,00,000
            "currency": "INR",
            "idempotency_key": str(uuid.uuid4()),
        },
        headers=auth_headers(OWNER_TOKEN),
    )
    assert create2.status_code == 201
    m2_data = create2.json()

    # Verify M2
    p2 = f"pay_{uuid.uuid4().hex[:14]}"
    sig2 = app.state.razorpay_client.generate_mock_signature(m2_data["razorpay_order_id"], p2)
    await client.post(
        "/api/v1/payment/verify",
        json={"razorpay_order_id": m2_data["razorpay_order_id"], "razorpay_payment_id": p2, "razorpay_signature": sig2},
        headers=auth_headers(OWNER_TOKEN),
    )

    # Release M2 -> triggers 1% TDS
    rel2 = await client.patch(
        f"/api/v1/payment/transfers/{m2_data['milestone_id']}/release",
        headers=auth_headers(OWNER_TOKEN),
    )
    assert rel2.status_code == 200
    res2_data = rel2.json()
    assert res2_data["tds_deducted_paise"] == 90000  # 1% of 9,000,000
    assert res2_data["net_payout_paise"] == 9000000 - 90000

    # Inspect TDS ledger
    tds_summary = await client.get(
        f"/api/v1/payment/developers/{dev_id}/tds",
        headers=auth_headers(OWNER_TOKEN),
    )
    assert tds_summary.status_code == 200
    tds_data = tds_summary.json()
    assert tds_data["tds_threshold_crossed"] is True
    assert tds_data["total_tds_deducted_paise"] == 90000


@pytest.mark.asyncio
async def test_refund_milestone_escrow(client: AsyncClient, app: Any) -> None:
    """Project owner reverses held funds back to client's original UPI/card source."""
    task_id = uuid.uuid4()
    create_res = await client.post(
        "/api/v1/payment/orders",
        json={
            "project_id": str(PROJECT_ID),
            "task_id": str(task_id),
            "developer_id": str(FREELANCER_ID),
            "amount_paise": 400000,
            "currency": "INR",
            "idempotency_key": str(uuid.uuid4()),
        },
        headers=auth_headers(OWNER_TOKEN),
    )
    assert create_res.status_code == 201
    order_data = create_res.json()
    m_id = order_data["milestone_id"]

    ref_res = await client.post(
        f"/api/v1/payment/transfers/{m_id}/refund",
        json={"reason": "Freelancer requested scope cancellation."},
        headers=auth_headers(OWNER_TOKEN),
    )
    assert ref_res.status_code == 200, ref_res.text
    ref_data = ref_res.json()
    assert ref_data["status"] == "REFUNDED"
    assert ref_data["refunded_amount_paise"] == 400000
    assert "refunded_at" in ref_data


@pytest.mark.asyncio
async def test_razorpay_webhook_reconciliation(client: AsyncClient, app: Any) -> None:
    """Cryptographic webhook reconciles network-drop payment into HELD_IN_ESCROW."""
    import json
    task_id = uuid.uuid4()
    create_res = await client.post(
        "/api/v1/payment/orders",
        json={
            "project_id": str(PROJECT_ID),
            "task_id": str(task_id),
            "developer_id": str(FREELANCER_ID),
            "amount_paise": 500000,
            "currency": "INR",
            "idempotency_key": str(uuid.uuid4()),
        },
        headers=auth_headers(OWNER_TOKEN),
    )
    assert create_res.status_code == 201
    rz_order_id = create_res.json()["razorpay_order_id"]

    # Webhook payload for payment.captured
    webhook_payload = {
        "entity": "event",
        "account_id": "acc_mock_1234",
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": f"pay_{uuid.uuid4().hex[:14]}",
                    "order_id": rz_order_id,
                    "amount": 500000,
                    "currency": "INR",
                    "status": "captured",
                }
            }
        },
    }
    raw_body = json.dumps(webhook_payload).encode("utf-8")
    valid_sig = app.state.razorpay_client.generate_mock_webhook_signature(raw_body)

    wh_res = await client.post(
        "/api/v1/payment/webhook",
        content=raw_body,
        headers={"X-Razorpay-Signature": valid_sig, "Content-Type": "application/json"},
    )
    assert wh_res.status_code == 200, wh_res.text
    wh_data = wh_res.json()
    assert wh_data["status"] == "ok"
    assert wh_data["event"] == "payment.captured"
    assert wh_data["reconciled"] is True


@pytest.mark.asyncio
async def test_ai_guarded_auto_release_flow(client: AsyncClient, app: Any) -> None:
    """Verifies the 5-day AI-guarded auto-release mechanism in payment-service."""
    task_id = uuid.uuid4()
    # 1. Create order & verify hold
    create_res = await client.post(
        "/api/v1/payment/orders",
        json={
            "project_id": str(PROJECT_ID),
            "task_id": str(task_id),
            "developer_id": str(FREELANCER_ID),
            "amount_paise": 600000,
            "currency": "INR",
            "idempotency_key": str(uuid.uuid4()),
        },
        headers=auth_headers(OWNER_TOKEN),
    )
    assert create_res.status_code == 201
    rz_order_id = create_res.json()["razorpay_order_id"]

    verify_res = await client.post(
        "/api/v1/payment/verify",
        json={
            "razorpay_order_id": rz_order_id,
            "razorpay_payment_id": "pay_test_autorel",
            "razorpay_signature": app.state.razorpay_client.generate_mock_signature(
                rz_order_id, "pay_test_autorel"
            ),
        },
        headers=auth_headers(OWNER_TOKEN),
    )
    assert verify_res.status_code == 200

    # 2. Reject auto-release when age < 5 days
    reject_young = await client.post(
        f"/api/v1/payment/transfers/{rz_order_id}/auto-release",
        json={
            "submission_age_days": 4.0,
            "ci_status": "completed",
            "ci_conclusion": "success",
            "ai_audit_score": 98,
            "ai_recommendation": "APPROVED_FOR_RELEASE",
        },
        headers=auth_headers(FREELANCER_TOKEN),
    )
    assert reject_young.status_code == 200
    res_y = reject_young.json()
    assert res_y["auto_released"] is False
    assert any("minimum 5 days required" in r for r in res_y["rejection_reasons"])

    # 3. Reject auto-release when AI score < 95
    reject_low_ai = await client.post(
        f"/api/v1/payment/transfers/{rz_order_id}/auto-release",
        json={
            "submission_age_days": 5.5,
            "ci_status": "completed",
            "ci_conclusion": "success",
            "ai_audit_score": 88,
            "ai_recommendation": "REVISION_REQUIRED",
        },
        headers=auth_headers(FREELANCER_TOKEN),
    )
    assert reject_low_ai.status_code == 200
    res_lai = reject_low_ai.json()
    assert res_lai["auto_released"] is False
    assert any("below the 95% threshold" in r for r in res_lai["rejection_reasons"])

    # 4. Successful auto-release when all guard conditions pass
    approve_rel = await client.post(
        f"/api/v1/payment/transfers/{rz_order_id}/auto-release",
        json={
            "submission_age_days": 5.5,
            "ci_status": "completed",
            "ci_conclusion": "success",
            "ai_audit_score": 99,
            "ai_recommendation": "APPROVED_FOR_RELEASE",
            "hollow_mock_code_detected": False,
            "security_vulnerabilities_count": 0,
        },
        headers=auth_headers(FREELANCER_TOKEN),
    )
    assert approve_rel.status_code == 200
    res_app = approve_rel.json()
    assert res_app["auto_released"] is True
    assert res_app["status"] == "RELEASED"
    assert res_app["developer_payout_paise"] == 540000  # 90% of 600000


