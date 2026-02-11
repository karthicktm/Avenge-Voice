"""Request tracing middleware for correlation IDs and logging.

Uses pure ASGI instead of BaseHTTPMiddleware to avoid the known Starlette
issue where BaseHTTPMiddleware swallows exceptions and returns bare 500
responses that bypass CORSMiddleware header injection.
"""

import time
import uuid
from collections.abc import MutableMapping
from typing import Any

import structlog
from starlette.types import ASGIApp, Receive, Scope, Send

logger = structlog.get_logger()


class RequestTracingMiddleware:
    """Pure ASGI middleware to add request tracing with correlation IDs.

    This middleware:
    1. Generates or extracts a correlation ID for each request
    2. Adds the correlation ID to structlog context
    3. Logs request start and completion with timing
    4. Adds correlation ID to response headers
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Process request with tracing."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Get or generate correlation ID
        headers_raw: list[tuple[bytes, bytes]] = scope.get("headers", [])
        correlation_id: str | None = None
        for key, value in headers_raw:
            if key.lower() == b"x-correlation-id":
                correlation_id = value.decode("latin-1")
                break
        if not correlation_id:
            correlation_id = str(uuid.uuid4())

        request_id = str(uuid.uuid4())[:8]

        # Extract client IP
        client_ip = self._get_client_ip(scope)

        # Extract path and method
        method = scope.get("method", "")
        path = scope.get("path", "")

        # Start timing
        start_time = time.perf_counter()

        # Bind context for all logs during this request
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            correlation_id=correlation_id,
            request_id=request_id,
            method=method,
            path=path,
            client_ip=client_ip,
        )

        # Extract query string for logging
        query_string = scope.get("query_string", b"")
        query_params = query_string.decode("latin-1") if query_string else None

        logger.info(
            "request_started",
            query_params=query_params or None,
        )

        response_status: int | None = None

        async def send_with_tracing(message: MutableMapping[str, Any]) -> None:
            nonlocal response_status
            if message["type"] == "http.response.start":
                response_status = message.get("status", 0)
                headers = list(message.get("headers", []))
                headers.append((b"x-correlation-id", correlation_id.encode("latin-1")))
                headers.append((b"x-request-id", request_id.encode("latin-1")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_tracing)

            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.info(
                "request_completed",
                status_code=response_status,
                duration_ms=round(duration_ms, 2),
            )
        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.exception(
                "request_failed",
                error=str(e),
                error_type=type(e).__name__,
                duration_ms=round(duration_ms, 2),
            )
            raise

    def _get_client_ip(self, scope: Scope) -> str:
        """Extract client IP, handling proxies."""
        headers_raw: list[tuple[bytes, bytes]] = scope.get("headers", [])

        for key, value in headers_raw:
            key_lower = key.lower()
            if key_lower == b"x-forwarded-for":
                return value.decode("latin-1").split(",")[0].strip()
            if key_lower == b"x-real-ip":
                return value.decode("latin-1")

        client: tuple[str, int] | None = scope.get("client")
        if client:
            return client[0]

        return "unknown"
