"""Tests for Circuit Breaker, Security Headers, and Health Probes in API Gateway."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.clients.circuit_breaker import CircuitBreaker, CircuitBreakerRegistry, CircuitState
from app.core.exceptions import ServiceUnavailableError
from app.main import create_app


def test_circuit_breaker_transitions():
    """Verify circuit transitions from CLOSED -> OPEN -> HALF_OPEN -> CLOSED."""
    breaker = CircuitBreaker("test-service", failure_threshold=3, recovery_timeout=0.1)

    assert breaker.state == CircuitState.CLOSED
    assert breaker.can_execute() is True

    # Record 2 failures (threshold is 3)
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.state == CircuitState.CLOSED

    # 3rd failure trips the circuit
    breaker.record_failure()
    assert breaker.state == CircuitState.OPEN
    assert breaker.can_execute() is False

    # Simulate waiting past recovery timeout
    breaker._last_failure_time -= 0.2
    assert breaker.state == CircuitState.HALF_OPEN
    assert breaker.can_execute() is True

    # Successful call in HALF_OPEN resets to CLOSED
    breaker.record_success()
    assert breaker.state == CircuitState.CLOSED
    assert breaker.can_execute() is True


def test_circuit_breaker_registry_fast_fail():
    """Verify registry raises ServiceUnavailableError when circuit is OPEN."""
    registry = CircuitBreakerRegistry(failure_threshold=2, recovery_timeout=60.0)
    breaker = registry.get_breaker("payment-service")

    breaker.record_failure()
    breaker.record_failure()
    assert breaker.state == CircuitState.OPEN

    with pytest.raises(ServiceUnavailableError) as exc_info:
        registry.check_and_execute("payment-service")
    assert "temporarily unavailable" in str(exc_info.value.message)


@pytest.mark.asyncio
async def test_security_headers_middleware():
    """Verify all OWASP security headers are present in gateway HTTP responses."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        headers = response.headers

        assert headers.get("x-content-type-options") == "nosniff"
        assert headers.get("x-frame-options") == "DENY"
        assert headers.get("x-xss-protection") == "1; mode=block"
        assert "max-age=31536000" in headers.get("strict-transport-security", "")
        assert headers.get("referrer-policy") == "strict-origin-when-cross-origin"
        assert "geolocation=()" in headers.get("permissions-policy", "")


@pytest.mark.asyncio
async def test_liveness_and_readiness_probes():
    """Verify Kubernetes /health/live and /health/ready endpoints."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Liveness check
        live_res = await client.get("/health/live")
        assert live_res.status_code == 200
        live_data = live_res.json()
        assert live_data["status"] == "healthy"
        assert "circuit_breakers" in live_data

        # Readiness check
        ready_res = await client.get("/health/ready")
        assert ready_res.status_code in (200, 503)
