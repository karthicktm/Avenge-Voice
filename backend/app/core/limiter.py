"""Rate limiter configuration.

Provides two approaches:
1. slowapi decorator: `@limiter.limit("30/minute")` — legacy, has compatibility
   issues with Starlette 0.50+ (bypasses middleware headers on errors).
2. Dependency-based: `Depends(RateLimit("30/minute"))` — works correctly with
   all Starlette versions since exceptions flow through normal FastAPI handling.

Use the dependency approach for new endpoints. Existing slowapi decorators will
be migrated over time.
"""

import time

import structlog
from fastapi import HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.db.redis import get_redis

# Legacy slowapi limiter (for existing endpoints)
limiter = Limiter(key_func=get_remote_address)


class RateLimit:
    """Dependency-based rate limiter using Redis.

    Usage:
        @router.post("/endpoint")
        async def endpoint(
            request: Request,
            _rate_limit: None = Depends(RateLimit("30/minute")),
        ):
            ...
    """

    def __init__(self, rate: str) -> None:
        """Parse rate limit string like '30/minute', '5/hour'."""
        parts = rate.split("/")
        self.max_requests = int(parts[0])
        unit = parts[1] if len(parts) > 1 else "minute"
        self.window_seconds = {
            "second": 1,
            "minute": 60,
            "hour": 3600,
            "day": 86400,
        }.get(unit, 60)

    async def __call__(self, request: Request) -> None:
        """Check rate limit for the current request."""
        client_ip = _get_client_ip(request)
        key = f"ratelimit:{request.url.path}:{client_ip}"

        try:
            redis = await get_redis()
            now = time.time()
            window_start = now - self.window_seconds

            # Use a sorted set: score = timestamp, member = unique request ID
            pipe = redis.pipeline()
            pipe.zremrangebyscore(key, 0, window_start)  # Remove expired entries
            pipe.zcard(key)  # Count current entries
            pipe.zadd(key, {f"{now}": now})  # Add current request
            pipe.expire(key, self.window_seconds + 1)  # Set TTL
            results = await pipe.execute()

            current_count = results[1]
            if current_count >= self.max_requests:
                _raise_rate_limit(self.max_requests, self.window_seconds)
        except HTTPException:
            raise
        except Exception:
            # If Redis is unavailable, allow the request (fail open)
            structlog.get_logger().debug("rate_limit_check_failed", key=key)


def _raise_rate_limit(max_requests: int, window_seconds: int) -> None:
    """Raise rate limit exceeded error."""
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=f"Rate limit exceeded. Maximum {max_requests} requests per {window_seconds}s.",
    )


def _get_client_ip(request: Request) -> str:
    """Extract client IP from request, handling proxies."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip
    if request.client:
        return request.client.host
    return "unknown"
