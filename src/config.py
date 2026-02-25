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

    @field_validator("database_url")
    @classmethod
    def normalize_database_url(cls, v: str) -> str:
        """Convert Render's postgres:// to postgresql+asyncpg://."""
        if v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+asyncpg://", 1)
        if v.startswith("postgresql://") and "+asyncpg" not in v:
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    @property
    def database_url_sync(self) -> str:
        """Synchronous database URL for Alembic migrations."""
        return self.database_url.replace("+asyncpg", "")


class LLMSettings(BaseSettings):
    """LLM configuration — supports Ollama (local) and DeepInfra (cloud)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Provider switch: "deepinfra" or "ollama"
    llm_provider: str = Field(default="deepinfra", description="LLM backend: 'deepinfra' or 'ollama'")

    # DeepInfra settings
    deepinfra_api_key: str = Field(default="", description="DeepInfra API key (Bearer token)")
    deepinfra_base_url: str = Field(
        default="https://api.deepinfra.com/v1/openai",
        description="DeepInfra OpenAI-compatible base URL",
    )

    # Ollama settings (used when llm_provider=ollama)
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        description="Ollama API base URL",
    )

    # Model names (format depends on provider)
    conversation_model: str = Field(
        default="Qwen/Qwen3-14B",
        description="Model for conversation",
    )
    vision_model: str = Field(
        default="Qwen/Qwen3-VL-30B-A3B-Instruct",
        description="Model for OCR / vision",
    )
    conversation_timeout: int = Field(default=30, description="Conversation LLM timeout in seconds")
    ocr_timeout: int = Field(default=120, description="OCR LLM timeout in seconds (includes model swap)")
    keep_alive: str = Field(default="-1m", description="Ollama keep_alive parameter (-1m = never unload)")
    conversation_max_tokens: int = Field(default=400, description="Max tokens for conversation responses")
    ocr_max_tokens: int = Field(default=2048, description="Max tokens for OCR extraction responses")


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
    telegram_webhook_url: str = Field(
        default="",
        description="Webhook URL (empty = polling mode)",
    )
    telegram_webhook_secret: str = Field(
        default="",
        description="Secret for X-Telegram-Bot-Api-Secret-Token header",
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
    whatsapp_app_secret: str = Field(default="", description="Meta app secret for X-Hub-Signature-256 verification")


class SchedulingSettings(BaseSettings):
    """Cal.com / Calendly integration settings."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    calcom_api_url: str = Field(default="https://api.cal.com/v1", description="Cal.com API URL")
    calcom_api_key: str = Field(default="", description="Cal.com API key")


class RateLimitSettings(BaseSettings):
    """Rate limiting thresholds."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    message_rate_limit: int = Field(default=15, description="Max messages per window")
    message_rate_window: int = Field(default=60, description="Message window in seconds")
    upload_rate_limit: int = Field(default=5, description="Max uploads per window")
    upload_rate_window: int = Field(default=60, description="Upload window in seconds")
    upload_max_size_bytes: int = Field(default=5_242_880, description="Max upload size (5 MB)")


class SecuritySettings(BaseSettings):
    """Encryption and authentication settings."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    encryption_key: str = Field(
        default="",
        description="32-byte AES key, base64 encoded",
    )
    jwt_secret: str = Field(default="", description="JWT secret for admin web auth (Phase 2)")
    admin_web_password: str = Field(default="", description="HTTP Basic Auth password for admin (Phase 1)")


class PivaSettings(BaseSettings):
    """Agenzia delle Entrate P.IVA validation API settings."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    piva_ade_api_key: str = Field(default="", description="AdE API Management subscription key")
    piva_ade_api_url: str = Field(
        default="https://api.agenziaentrate.gov.it/entrate/api/partita-iva/v0/verifica",
        description="Agenzia delle Entrate P.IVA validation endpoint",
    )
    piva_cache_ttl: int = Field(default=86400, description="Redis cache TTL in seconds (24h)")
    piva_validation_enabled: bool = Field(default=True, description="Enable AdE validation")


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
    rate_limit: RateLimitSettings = Field(default_factory=RateLimitSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    branding: BrandingSettings = Field(default_factory=BrandingSettings)
    piva: PivaSettings = Field(default_factory=PivaSettings)

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
