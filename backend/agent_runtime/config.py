"""Settings for the agent runtime process."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentRuntimeSettings(BaseSettings):
    """Settings read from environment variables in the agent container."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Required: which agent this runtime serves
    AGENT_ID: str

    # Database
    DATABASE_URL: str

    # Redis
    REDIS_URL: str

    # Voice / AI service keys (forwarded from control plane)
    OPENAI_API_KEY: str | None = None
    DEEPGRAM_API_KEY: str | None = None
    ELEVENLABS_API_KEY: str | None = None

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8001


runtime_settings = AgentRuntimeSettings()
