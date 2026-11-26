"""Centralized lifecycle-managed asynchronous HTTPX client for downstream calls."""

from __future__ import annotations

import httpx

from app.clients.circuit_breaker import CircuitBreakerRegistry
from app.config import Settings
from app.core.exceptions import (
    ServiceConfigurationError,
    ServiceTimeoutError,
    ServiceUnavailableError,
)
from app.core.logging import get_logger

logger = get_logger("clients.http_client")


class GatewayHTTPClient:
    """Manages a single reusable httpx.AsyncClient with circuit breaking across the Gateway lifecycle."""

    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
        circuit_breakers: CircuitBreakerRegistry | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._circuit_breakers = circuit_breakers or CircuitBreakerRegistry()

    @property
    def is_open(self) -> bool:
        """Return True when the underlying AsyncClient is initialized and open."""
        return self._client is not None and not self._client.is_closed

    @property
    def circuit_breakers(self) -> CircuitBreakerRegistry:
        """Access the circuit breaker registry for monitoring and stats."""
        return self._circuit_breakers

    async def startup(self) -> None:
        """Initialize the reusable AsyncClient during FastAPI lifespan startup."""
        if self.is_open:
            return

        timeout = httpx.Timeout(
            timeout=self._settings.REQUEST_TIMEOUT_SECONDS,
            connect=min(
                self._settings.CONNECT_TIMEOUT_SECONDS,
                self._settings.REQUEST_TIMEOUT_SECONDS,
            ),
        )
        limits = httpx.Limits(
            max_connections=self._settings.HTTP_MAX_CONNECTIONS,
            max_keepalive_connections=self._settings.HTTP_MAX_KEEPALIVE_CONNECTIONS,
        )
        client_kwargs: dict = {
            "timeout": timeout,
            "limits": limits,
            "follow_redirects": False,
        }
        if self._transport is not None:
            client_kwargs["transport"] = self._transport

        self._client = httpx.AsyncClient(**client_kwargs)
        logger.info(
            "Gateway HTTPX AsyncClient initialized",
            extra={"event": "http_client_startup"},
        )

    async def shutdown(self) -> None:
        """Close the reusable AsyncClient cleanly during application shutdown."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            logger.info(
                "Gateway HTTPX AsyncClient closed",
                extra={"event": "http_client_shutdown"},
            )

    async def forward(
        self,
        *,
        service_name: str,
        method: str,
        url: str,
        headers: dict[str, str],
        params: list[tuple[str, str]] | None = None,
        content: bytes | None = None,
        timeout_seconds: float | None = None,
    ) -> httpx.Response:
        """Forward a synchronous HTTP request to a downstream microservice."""
        if not self.is_open or self._client is None:
            raise ServiceConfigurationError()

        # Fail-fast if downstream circuit breaker is currently OPEN
        self._circuit_breakers.check_and_execute(service_name)

        request_timeout = (
            httpx.Timeout(
                timeout=timeout_seconds,
                connect=min(self._settings.CONNECT_TIMEOUT_SECONDS, timeout_seconds),
            )
            if timeout_seconds is not None
            else None
        )

        try:
            response = await self._client.request(
                method=method,
                url=url,
                params=tuple(params) if params else None,
                content=content,
                headers=headers,
                timeout=request_timeout,
            )
            if response.status_code >= 500:
                self._circuit_breakers.get_breaker(service_name).record_failure()
            else:
                self._circuit_breakers.get_breaker(service_name).record_success()
            return response
        except httpx.TimeoutException as exc:
            self._circuit_breakers.get_breaker(service_name).record_failure()
            logger.warning(
                "Downstream request timed out",
                extra={
                    "event": "downstream_timeout",
                    "target_service": service_name,
                    "error_code": "SERVICE_TIMEOUT",
                },
            )
            raise ServiceTimeoutError() from exc
        except httpx.ConnectError as exc:
            self._circuit_breakers.get_breaker(service_name).record_failure()
            logger.error(
                "Downstream service connection failed",
                extra={
                    "event": "downstream_connect_error",
                    "target_service": service_name,
                    "error_code": "SERVICE_UNAVAILABLE",
                },
            )
            raise ServiceUnavailableError() from exc
        except httpx.HTTPError as exc:
            self._circuit_breakers.get_breaker(service_name).record_failure()
            logger.error(
                "Downstream HTTP transport error",
                extra={
                    "event": "downstream_transport_error",
                    "target_service": service_name,
                    "error_code": "SERVICE_UNAVAILABLE",
                },
            )
            raise ServiceUnavailableError(
                message="Upstream service communication failed.",
                status_code=502,
            ) from exc

