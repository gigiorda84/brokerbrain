"""Application configuration via pydantic-settings.

All secrets are loaded from environment variables (.env file).
Settings are organized into logical groups and composed into a single Settings object.
"""

from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """PostgreSQL and Redis connection settings."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(
        default="postgresql+asyncpg://brokerbot:brokerbot_dev@localhost:5432/brokerbot",
        description="Async PostgreSQL connection string",
    )
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection string",
    )

    @property
    def database_url_sync(self) -> str:
        """Synchronous database URL for Alembic migrations."""
        return self.database_url.replace("+asyncpg", "")


class LLMSettings(BaseSettings):
    """Ollama LLM configuration."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ollama_base_url: str = Field(
        default="http://localhost:11434",
        description="Ollama API base URL",
    )
    conversation_model: str = Field(
        default="qwen3:8b-q4_K_M",
        description="Model for conversation (Qwen3 8B)",
    )
    vision_model: str = Field(
        default="qwen2.5-vl:7b-q4_K_M",
        description="Model for OCR (Qwen2.5-VL 7B)",
    )
    conversation_timeout: int = Field(default=30, description="Conversation LLM timeout in seconds")
    ocr_timeout: int = Field(default=120, description="OCR LLM timeout in seconds (includes model swap)")
    keep_alive: str = Field(default="-1m", description="Ollama keep_alive parameter (-1m = never unload)")
    conversation_max_tokens: int = Field(default=400, description="Max tokens for conversation responses")
    ocr_max_tokens: int = Field(default=600, description="Max tokens for OCR extraction responses")


class TelegramSettings(BaseSettings):
    """Telegram bot tokens and admin IDs."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_user_bot_token: str = Field(
        default="",
        description="Telegram user-facing bot token",
    )
    telegram_admin_bot_token: str = Field(
        default="",
        description="Telegram admin bot token",
    )
    admin_telegram_ids: str = Field(
        default="",
        description="Comma-separated Telegram user IDs for admin access",
    )

    @property
    def admin_ids(self) -> list[int]:
        """Parse comma-separated admin IDs into a list of integers."""
        if not self.admin_telegram_ids:
            return []
        return [int(id_.strip()) for id_ in self.admin_telegram_ids.split(",") if id_.strip()]


class WhatsAppSettings(BaseSettings):
    """WhatsApp Business API configuration (Phase 1b)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    whatsapp_api_url: str = Field(default="", description="WhatsApp Business API URL")
    whatsapp_api_token: str = Field(default="", description="WhatsApp API token")
    whatsapp_verify_token: str = Field(default="", description="Webhook verification token")


class SchedulingSettings(BaseSettings):
    """Cal.com / Calendly integration settings."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    calcom_api_url: str = Field(default="https://api.cal.com/v1", description="Cal.com API URL")
    calcom_api_key: str = Field(default="", description="Cal.com API key")


class SecuritySettings(BaseSettings):
    """Encryption and authentication settings."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    encryption_key: str = Field(
        default="",
        description="32-byte AES key, base64 encoded",
    )
    jwt_secret: str = Field(default="", description="JWT secret for admin web auth (Phase 2)")
    admin_web_password: str = Field(default="", description="HTTP Basic Auth password for admin (Phase 1)")


class BrandingSettings(BaseSettings):
    """Branding and legal identity constants."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    bot_name: str = Field(default="ameconviene.it")
    legal_entity: str = Field(default="Primo Network Srl")
    oam_number: str = Field(default="M94")
    toll_free: str = Field(default="800.99.00.90")
    info_email: str = Field(default="info@primonetwork.it")


class Settings(BaseSettings):
    """Root settings composing all sub-settings.

    Usage:
        settings = Settings()
        settings.db.database_url
        settings.llm.conversation_model
        settings.telegram.admin_ids
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Environment
    environment: str = Field(default="development")
    log_level: str = Field(default="DEBUG")
    document_retention_days: int = Field(default=30)
    data_retention_months: int = Field(default=12)

    # Composed settings (loaded from same .env)
    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    telegram: TelegramSettings = Field(default_factory=TelegramSettings)
    whatsapp: WhatsAppSettings = Field(default_factory=WhatsAppSettings)
    scheduling: SchedulingSettings = Field(default_factory=SchedulingSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    branding: BrandingSettings = Field(default_factory=BrandingSettings)

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Ensure log level is valid."""
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in valid:
            msg = f"Invalid log level: {v}. Must be one of {valid}"
            raise ValueError(msg)
        return upper

    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.environment == "production"


# Module-level singleton — import this wherever settings are needed.
settings = Settings()
