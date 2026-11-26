"""Comprehensive status code error-handling and diagnostic headers test suite."""

import pytest
from httpx import ASGITransport, AsyncClient, Response, Request
import httpx

from app.config import Settings
from app.main import create_app
from app.core.exceptions import _default_error_for_status


@pytest.mark.parametrize(
    "status_code, expected_code",
    [
        (400, "VALIDATION_ERROR"),
        (401, "UNAUTHORIZED"),
        (402, "PAYMENT_REQUIRED"),
        (403, "FORBIDDEN"),
        (404, "NOT_FOUND"),
        (405, "VALIDATION_ERROR"),
        (406, "NOT_ACCEPTABLE"),
        (408, "REQUEST_TIMEOUT"),
        (409, "CONFLICT"),
        (410, "GONE"),
        (413, "PAYLOAD_TOO_LARGE"),
        (415, "UNSUPPORTED_MEDIA_TYPE"),
        (422, "VALIDATION_ERROR"),
        (429, "RATE_LIMITED"),
        (500, "INTERNAL_SERVER_ERROR"),
        (501, "NOT_IMPLEMENTED"),
        (502, "SERVICE_UNAVAILABLE"),
        (503, "SERVICE_UNAVAILABLE"),
        (504, "SERVICE_TIMEOUT"),
    ],
)
def test_all_status_codes_mapped_to_diagnostics(status_code: int, expected_code: str):
    """Verify that every status code has an immediate clean error code and human message."""
    code, message = _default_error_for_status(status_code)
    assert code == expected_code
    assert len(message) > 5


@pytest.mark.asyncio
async def test_immediate_diagnostic_headers_on_all_error_responses():
    """Verify error responses include immediate X-Error-Code and X-Status-Code diagnostic headers."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 404 test on unknown path
        res404 = await client.get("/api/v1/unknown-path-xyz")
        assert res404.status_code == 404
        assert res404.headers.get("X-Status-Code") == "404"
        assert res404.headers.get("X-Error-Code") == "NOT_FOUND"
        assert res404.headers.get("X-Request-ID") is not None
        data404 = res404.json()
        assert data404["success"] is False
        assert data404["error"]["code"] == "NOT_FOUND"

        # 405 Method Not Allowed test
        res405 = await client.delete("/health")
        assert res405.status_code == 405
        assert res405.headers.get("X-Status-Code") == "405"
        assert res405.headers.get("X-Request-ID") is not None
        data405 = res405.json()
        assert data405["success"] is False
