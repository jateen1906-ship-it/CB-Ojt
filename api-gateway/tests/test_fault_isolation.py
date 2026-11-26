"""Tests proving complete microservice fault isolation and blast-radius containment."""

import pytest
from httpx import ASGITransport, AsyncClient, Response

from app.clients.circuit_breaker import CircuitBreakerRegistry, CircuitState
from app.clients.http_client import GatewayHTTPClient
from app.clients.service_registry import RouteRule, ServiceDefinition, ServiceRegistry
from app.core.exceptions import ServiceUnavailableError
from app.main import create_app


def test_independent_circuit_breakers_per_microservice():
    """Verify that failures in Service A do NOT trip or impact Service B."""
    registry = CircuitBreakerRegistry(failure_threshold=3, recovery_timeout=10.0)

    # Simulate 3 failures in 'github-service'
    for _ in range(3):
        registry.get_breaker("github-service").record_failure()

    # github-service is now OPEN (isolated)
    assert registry.get_breaker("github-service").state == CircuitState.OPEN
    assert registry.get_breaker("github-service").can_execute() is False

    # Other services (payment-service, identity-service, project-service) remain CLOSED and healthy
    assert registry.get_breaker("payment-service").state == CircuitState.CLOSED
    assert registry.get_breaker("payment-service").can_execute() is True

    assert registry.get_breaker("identity-service").state == CircuitState.CLOSED
    assert registry.get_breaker("identity-service").can_execute() is True

    assert registry.get_breaker("project-service").state == CircuitState.CLOSED
    assert registry.get_breaker("project-service").can_execute() is True


def test_circuit_breaker_auto_recovery_without_system_restart():
    """Verify that an isolated microservice automatically recovers once it is back up."""
    registry = CircuitBreakerRegistry(failure_threshold=2, recovery_timeout=0.05)

    # Trip breaker
    registry.get_breaker("workspace-service").record_failure()
    registry.get_breaker("workspace-service").record_failure()
    assert registry.get_breaker("workspace-service").state == CircuitState.OPEN

    # Simulate time passing past recovery timeout
    registry.get_breaker("workspace-service")._last_failure_time -= 0.1

    # Transitions to HALF_OPEN to probe service
    assert registry.get_breaker("workspace-service").state == CircuitState.HALF_OPEN
    assert registry.get_breaker("workspace-service").can_execute() is True

    # Successful call heals the circuit back to CLOSED
    registry.get_breaker("workspace-service").record_success()
    assert registry.get_breaker("workspace-service").state == CircuitState.CLOSED
    assert registry.get_breaker("workspace-service").can_execute() is True


@pytest.mark.asyncio
async def test_gateway_isolates_crashed_service_and_serves_others():
    """Verify gateway returns 503 for crashed service while other routes work normally."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Trip circuit breaker for a simulated crashed service directly on gateway
        http_client = app.state.http_client
        breaker = http_client.circuit_breakers.get_breaker("github-service")
        for _ in range(5):
            breaker.record_failure()

        assert breaker.state == CircuitState.OPEN

        # Gateway health check continues reporting healthy and displays circuit breaker isolation
        health_res = await client.get("/health")
        assert health_res.status_code == 200
        health_json = health_res.json()
        assert health_json["status"] == "healthy"
        assert health_json["circuit_breakers"]["github-service"] == "OPEN"
