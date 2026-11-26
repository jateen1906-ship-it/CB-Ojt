"""Circuit Breaker for downstream microservice resilience."""

from __future__ import annotations

import time
from enum import Enum
from typing import NamedTuple

from app.core.exceptions import ServiceUnavailableError
from app.core.logging import get_logger

logger = get_logger("clients.circuit_breaker")


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitStats(NamedTuple):
    state: CircuitState
    failure_count: int
    last_failure_time: float
    last_state_change: float


class CircuitBreaker:
    """Manages failure thresholds and fail-fast states for a single target service."""

    def __init__(
        self,
        service_name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 10.0,
    ) -> None:
        self.service_name = service_name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout

        self._state: CircuitState = CircuitState.CLOSED
        self._failure_count: int = 0
        self._last_failure_time: float = 0.0
        self._last_state_change: float = time.time()

    @property
    def state(self) -> CircuitState:
        now = time.time()
        if self._state == CircuitState.OPEN:
            if now - self._last_failure_time >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._last_state_change = now
                logger.info(
                    "Circuit breaker entered HALF_OPEN state",
                    extra={"target_service": self.service_name, "state": "HALF_OPEN"},
                )
        return self._state

    def can_execute(self) -> bool:
        """Return True if requests to this service are permitted."""
        current_state = self.state
        return current_state in (CircuitState.CLOSED, CircuitState.HALF_OPEN)

    def record_success(self) -> None:
        """Record a successful response and reset circuit to CLOSED."""
        if self._state != CircuitState.CLOSED:
            logger.info(
                "Circuit breaker recovered to CLOSED state",
                extra={"target_service": self.service_name, "state": "CLOSED"},
            )
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_state_change = time.time()

    def record_failure(self) -> None:
        """Record a downstream failure; trip to OPEN if failure_threshold reached."""
        now = time.time()
        self._last_failure_time = now
        self._failure_count += 1

        if self._state == CircuitState.HALF_OPEN or self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
            self._last_state_change = now
            logger.warning(
                "Circuit breaker TRIPPED to OPEN state",
                extra={
                    "target_service": self.service_name,
                    "state": "OPEN",
                    "failures": self._failure_count,
                    "recovery_timeout": self.recovery_timeout,
                },
            )

    def get_stats(self) -> CircuitStats:
        return CircuitStats(
            state=self.state,
            failure_count=self._failure_count,
            last_failure_time=self._last_failure_time,
            last_state_change=self._last_state_change,
        )


class CircuitBreakerRegistry:
    """Registry maintaining per-service circuit breakers across the API Gateway."""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 10.0,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._breakers: dict[str, CircuitBreaker] = {}

    def get_breaker(self, service_name: str) -> CircuitBreaker:
        if service_name not in self._breakers:
            self._breakers[service_name] = CircuitBreaker(
                service_name=service_name,
                failure_threshold=self.failure_threshold,
                recovery_timeout=self.recovery_timeout,
            )
        return self._breakers[service_name]

    def check_and_execute(self, service_name: str) -> None:
        """Verify if service is available; raises ServiceUnavailableError if OPEN."""
        breaker = self.get_breaker(service_name)
        if not breaker.can_execute():
            logger.warning(
                "Request fast-failed by open circuit breaker",
                extra={"target_service": service_name, "error_code": "CIRCUIT_BREAKER_OPEN"},
            )
            raise ServiceUnavailableError(
                message=f"Service '{service_name}' is temporarily unavailable (circuit breaker open).",
                status_code=503,
            )
