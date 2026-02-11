"""Security middleware for adding security headers.

Uses pure ASGI instead of BaseHTTPMiddleware to avoid the known Starlette
issue where BaseHTTPMiddleware swallows exceptions and returns bare 500
responses that bypass CORSMiddleware header injection.
"""

from collections.abc import MutableMapping
from typing import Any

from starlette.types import ASGIApp, Receive, Scope, Send

SECURITY_HEADERS: list[tuple[bytes, bytes]] = [
    (b"x-frame-options", b"DENY"),
    (b"x-content-type-options", b"nosniff"),
    (b"x-xss-protection", b"1; mode=block"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (
        b"content-security-policy",
        b"default-src 'self'; "
        b"script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        b"style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        b"img-src 'self' data: https:; "
        b"font-src 'self' data:; "
        b"connect-src 'self'",
    ),
    (b"permissions-policy", b"geolocation=(), microphone=(), camera=(), payment=()"),
]


class SecurityHeadersMiddleware:
    """Pure ASGI middleware to add security headers to all HTTP responses."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Process request and inject security headers into the response."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: MutableMapping[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(SECURITY_HEADERS)
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
