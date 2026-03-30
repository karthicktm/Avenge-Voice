"""Main FastAPI application entry point."""

# Fix passlib bcrypt version detection issue FIRST before any imports
# passlib tries to access bcrypt.__about__.__version__ which doesn't exist in newer bcrypt
# This must be done before passlib is imported anywhere
from types import SimpleNamespace

import bcrypt as _bcrypt_module

if not hasattr(_bcrypt_module, "__about__"):
    _bcrypt_module.__about__ = SimpleNamespace(__version__=_bcrypt_module.__version__)  # type: ignore[attr-defined]

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api import (
    agents,
    auth,
    billing,
    calls,
    campaigns,
    category_trees,
    compliance,
    crm,
    documents,
    embed,
    health,
    integrations,
    lookup,
    organizations,
    password_reset,
    phone_numbers,
    realtime,
    setup,
    site_indexer,
    telephony,
    telephony_ws,
    tools,
    usage,
    usage_ws,
    users,
    webhooks,
    workspaces,
)
from app.api import (
    gemini as gemini_api,
)
from app.api import internal as internal_api
from app.api import settings as settings_api
from app.core.config import settings
from app.core.limiter import limiter
from app.db.redis import close_redis, get_redis
from app.db.session import engine
from app.middleware.request_tracing import RequestTracingMiddleware
from app.middleware.security import SecurityHeadersMiddleware
from app.services.campaign_worker import start_campaign_worker, stop_campaign_worker
from app.services.site_crawl_worker import start_site_crawl_worker, stop_site_crawl_worker

# Configure structured logging with async processors
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        logging.WARNING if not settings.DEBUG else logging.DEBUG
    ),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:  # noqa: PLR0915
    """Lifespan context manager for startup and shutdown events."""
    # Startup
    logger.info("Starting application", app_name=settings.APP_NAME)

    try:
        # Initialize Redis (fatal if fails)
        await get_redis()
        logger.info("Redis connection established")
    except Exception:
        logger.exception("Failed to initialize Redis - application cannot start")
        raise  # Re-raise to prevent app startup

    # Create default super admin user if configured via environment variables
    try:
        from app.cli import create_superuser_from_env

        await create_superuser_from_env()
    except Exception:
        logger.exception("Failed to check/create super admin from environment - continuing anyway")

    # Initialize Sentry if configured (non-fatal)
    if settings.SENTRY_DSN:
        try:
            import sentry_sdk

            sentry_sdk.init(
                dsn=settings.SENTRY_DSN,
                environment=settings.SENTRY_ENVIRONMENT,
                traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
            )
            logger.info("Sentry initialized")
        except Exception:
            logger.exception("Failed to initialize Sentry - continuing without error tracking")

    # Start campaign worker (non-fatal)
    try:
        # Use PUBLIC_URL from settings if available, otherwise default to localhost
        base_url = settings.PUBLIC_URL or f"http://{settings.HOST}:{settings.PORT}"
        await start_campaign_worker(base_url=base_url)
        logger.info("Campaign worker started", base_url=base_url)
    except Exception:
        logger.exception("Failed to start campaign worker - campaigns will not process")

    # Start site crawl worker (non-fatal)
    try:
        await start_site_crawl_worker()
        logger.info("Site crawl worker started")
    except Exception:
        logger.exception("Failed to start site crawl worker - scheduled crawls will not run")

    yield

    # Shutdown
    logger.info("Shutting down application")

    # Stop campaign worker
    try:
        await stop_campaign_worker()
        logger.info("Campaign worker stopped")
    except Exception:
        logger.exception("Error stopping campaign worker")

    # Stop site crawl worker
    try:
        await stop_site_crawl_worker()
        logger.info("Site crawl worker stopped")
    except Exception:
        logger.exception("Error stopping site crawl worker")

    # Close Redis connection
    try:
        await close_redis()
        logger.info("Redis connection closed")
    except Exception:
        logger.exception("Error closing Redis connection")

    # Dispose database engine and close all connections
    try:
        await engine.dispose()
        logger.info("Database connections closed")
    except Exception:
        logger.exception("Error closing database connections")


# Create FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# Add rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]


# Global exception handler to prevent unhandled 500s from bypassing CORS middleware
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch unhandled exceptions and return a proper JSON response.

    Without this, unhandled exceptions produce a plain 500 response from
    Starlette's ServerErrorMiddleware that bypasses CORSMiddleware headers.
    """
    logger.exception("unhandled_exception", path=request.url.path, error=str(exc))
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


# Add request tracing middleware (runs first, wraps everything)
app.add_middleware(RequestTracingMiddleware)

# Add security headers middleware
app.add_middleware(SecurityHeadersMiddleware)

# Build CORS origins: start with configured list, ensure FRONTEND_URL and PUBLIC_URL are included
cors_origins: list[str] = list(settings.CORS_ORIGINS)
for url in [settings.FRONTEND_URL, settings.PUBLIC_URL]:
    if url and url not in cors_origins:
        cors_origins.append(url)
logger.info("cors_origins_configured", origins=cors_origins)

# Add CORS middleware (must be added AFTER security headers so it runs first)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=settings.CORS_ALLOW_METHODS,
    allow_headers=settings.CORS_ALLOW_HEADERS,
)

# Include routers
app.include_router(health.router, tags=["health"])
app.include_router(crm.router, prefix=settings.API_V1_PREFIX)
app.include_router(workspaces.router, prefix=settings.API_V1_PREFIX)
app.include_router(agents.router)
app.include_router(settings_api.router)
app.include_router(realtime.router)
app.include_router(realtime.webrtc_router)  # WebRTC session endpoint
app.include_router(gemini_api.router)  # Gemini Live token endpoint
app.include_router(internal_api.router)  # Internal API for agent worker
app.include_router(tools.router)  # Tool execution endpoint
app.include_router(telephony.router)  # Telephony API (phone numbers, calls)
app.include_router(telephony.webhook_router)  # Twilio/Telnyx webhooks
app.include_router(telephony_ws.router)  # Telephony WebSocket for media streams
app.include_router(calls.router)  # Call history API
app.include_router(campaigns.router, prefix=settings.API_V1_PREFIX)  # Campaigns API
app.include_router(phone_numbers.router)  # Phone numbers API
app.include_router(auth.router)  # Authentication API
app.include_router(password_reset.router)  # Password reset API
app.include_router(compliance.router)  # Compliance API (GDPR/CCPA)
app.include_router(integrations.router)  # Integrations API (external tools)
app.include_router(documents.router)  # Documents API (Knowledge Base/RAG)
app.include_router(lookup.router, prefix=settings.API_V1_PREFIX)  # Lookup API
app.include_router(category_trees.router, prefix=settings.API_V1_PREFIX)  # Category Trees API
app.include_router(site_indexer.router)  # Site indexer API (web crawl)
app.include_router(embed.router)  # Public embed API (unauthenticated)
app.include_router(embed.ws_router)  # Public embed WebSocket
app.include_router(setup.router)  # First-run setup API (unauthenticated)
app.include_router(users.router)  # User management API (admin only)
app.include_router(organizations.router)  # Organization management API
app.include_router(billing.router)  # Billing & subscription API
app.include_router(usage.router)  # Usage tracking API
app.include_router(usage_ws.router)  # Usage WebSocket for real-time updates
app.include_router(webhooks.router)  # External webhooks (Stripe)


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint."""
    return {
        "message": f"Welcome to {settings.APP_NAME}",
        "version": settings.APP_VERSION,
        "docs": "/docs",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.RELOAD,
    )
