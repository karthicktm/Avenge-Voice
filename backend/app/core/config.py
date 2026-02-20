"""Application configuration using Pydantic settings."""

from typing import Any

from pydantic import PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Application
    APP_NAME: str = "Voice Noob API"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    RELOAD: bool = False
    PUBLIC_URL: str | None = None  # Public URL for webhook callbacks (e.g., ngrok URL)

    @field_validator("PUBLIC_URL", mode="before")
    @classmethod
    def strip_trailing_slash(cls, v: Any) -> Any:
        """Strip trailing slash so URLs like https://host/ don't produce double slashes."""
        if isinstance(v, str):
            return v.rstrip("/")
        return v

    # Database
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "voicenoob"
    DATABASE_URL: PostgresDsn | None = None

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def assemble_db_connection(cls, v: str | None, info: Any) -> str:
        """Build database URL from components if not provided."""
        if isinstance(v, str):
            # Convert postgres:// to postgresql+asyncpg:// for SQLAlchemy async support
            if v.startswith("postgres://"):
                v = v.replace("postgres://", "postgresql+asyncpg://", 1)
            elif v.startswith("postgresql://"):
                v = v.replace("postgresql://", "postgresql+asyncpg://", 1)
            return v

        data = info.data
        return str(
            PostgresDsn.build(
                scheme="postgresql+asyncpg",
                username=data.get("POSTGRES_USER"),
                password=data.get("POSTGRES_PASSWORD"),
                host=data.get("POSTGRES_SERVER"),
                port=data.get("POSTGRES_PORT"),
                path=f"{data.get('POSTGRES_DB') or ''}",
            ),
        )

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str | None = None
    REDIS_URL: RedisDsn | None = None

    @field_validator("REDIS_URL", mode="before")
    @classmethod
    def assemble_redis_connection(cls, v: str | None, info: Any) -> str:
        """Build Redis URL from components if not provided."""
        if isinstance(v, str):
            return v

        data = info.data
        password_part = f":{data.get('REDIS_PASSWORD')}@" if data.get("REDIS_PASSWORD") else ""
        return f"redis://{password_part}{data.get('REDIS_HOST')}:{data.get('REDIS_PORT')}/{data.get('REDIS_DB')}"

    # Security
    SECRET_KEY: str = "change-this-to-a-random-secret-key-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # CORS
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3002",
        "http://localhost:8000",
        "https://avenge-voice-production.up.railway.app",
        "https://avenge-voice-backend-production.up.railway.app",
    ]
    CORS_ALLOW_CREDENTIALS: bool = True
    CORS_ALLOW_METHODS: list[str] = ["*"]
    CORS_ALLOW_HEADERS: list[str] = ["*"]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: Any) -> list[str]:
        """Parse CORS origins from env var (supports comma-separated or JSON list)."""
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            # Handle comma-separated string: "url1,url2"
            if v.startswith("["):
                import json

                return json.loads(v)  # type: ignore[no-any-return]
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v  # type: ignore[return-value]

    # Rate Limiting
    RATE_LIMIT_PER_MINUTE: int = 60

    # Email Service (SMTP - Legacy)
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    FROM_EMAIL: str = "noreply@avenge-voice.com"
    FROM_NAME: str = "Avenge Voice"
    FRONTEND_URL: str = "http://localhost:3000"

    # Resend Email Service (Primary)
    RESEND_API_KEY: str | None = None
    RESEND_FROM_EMAIL: str = "noreply@avengeai.com"
    VERIFICATION_CODE_EXPIRY_MINUTES: int = 10
    EMAIL_VERIFICATION_REQUIRED: bool = True

    # Super Admin (created on startup if environment variables are set)
    SUPER_ADMIN_EMAIL: str | None = None
    SUPER_ADMIN_PASSWORD: str | None = None
    SUPER_ADMIN_NAME: str = "Super Admin"

    # Legacy Admin User (deprecated - use SUPER_ADMIN_* instead)
    ADMIN_EMAIL: str = "admin@voicenoob.com"
    ADMIN_PASSWORD: str = "admin"
    ADMIN_NAME: str = "Admin"

    # Voice & AI Services
    OPENAI_API_KEY: str | None = None
    DEEPGRAM_API_KEY: str | None = None
    ELEVENLABS_API_KEY: str | None = None

    # Telephony
    TELNYX_API_KEY: str | None = None
    TELNYX_PUBLIC_KEY: str | None = None
    TWILIO_ACCOUNT_SID: str | None = None
    TWILIO_AUTH_TOKEN: str | None = None

    # External Service Timeouts (seconds)
    # These are critical for preventing hung connections during voice calls
    OPENAI_TIMEOUT: float = 30.0  # LLM inference can be slow
    DEEPGRAM_TIMEOUT: float = 15.0  # Real-time STT should be fast
    ELEVENLABS_TIMEOUT: float = 20.0  # TTS synthesis timeout
    TELNYX_TIMEOUT: float = 10.0  # Telephony API calls
    TWILIO_TIMEOUT: float = 10.0  # Telephony API calls
    GOOGLE_API_TIMEOUT: float = 15.0  # Calendar, Drive, etc.
    DEFAULT_EXTERNAL_TIMEOUT: float = 30.0  # Fallback for other APIs

    # Retry Configuration
    MAX_RETRIES: int = 3  # Number of retry attempts for failed requests
    RETRY_BACKOFF_FACTOR: float = 2.0  # Exponential backoff multiplier

    # Monitoring
    SENTRY_DSN: str | None = None
    SENTRY_ENVIRONMENT: str = "development"
    SENTRY_TRACES_SAMPLE_RATE: float = 1.0

    # OpenTelemetry
    OTEL_ENABLED: bool = False
    OTEL_SERVICE_NAME: str = "voicenoob-api"
    OTEL_EXPORTER_OTLP_ENDPOINT: str | None = None

    # RAG / Knowledge Base Settings
    RAG_CHUNK_SIZE: int = 500  # Characters per chunk
    RAG_CHUNK_OVERLAP: int = 50  # Overlap between chunks
    RAG_EMBEDDING_MODEL: str = "text-embedding-3-small"  # OpenAI embedding model
    RAG_MAX_FILE_SIZE: int = 52_428_800  # 50MB max file size
    RAG_MAX_DOCUMENTS_PER_AGENT: int = 50  # Max documents per agent


settings = Settings()
