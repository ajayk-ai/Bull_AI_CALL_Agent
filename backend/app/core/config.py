"""Application settings, read from environment variables (and `.env` in development)."""

from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    app_name: str = "Bull AI Voice Calling Platform"
    log_level: str = "INFO"
    log_json: bool = True

    database_url: str = Field(description="postgresql+psycopg://user:pass@host:port/db")
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: SecretStr
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60
    refresh_token_days: int = 7

    # Fernet key for encrypting phone numbers and provider credentials at rest.
    data_encryption_key: SecretStr
    # Separate secret for the keyed hash used to look up and de-duplicate phone numbers.
    phone_hash_key: SecretStr
    default_phone_region: str = "IN"

    cors_origins: list[str] = []

    # Built React app (npm run build). Served at / when present.
    frontend_dist: str = "../frontend/dist"

    # File storage (uploaded imports now, call recordings from Phase 3). "local" = a directory / Docker volume.
    storage_backend: Literal["local"] = "local"
    storage_root: str = "../var/storage"

    # Contact imports
    import_max_bytes: int = 10 * 1024 * 1024
    import_max_rows: int = 10_000

    # Platform-wide cap on simultaneous calls; a campaign's own limit cannot exceed it.
    max_concurrent_calls: int = 5

    # Languages campaigns and contacts may use (BCP-47), and the names accepted for them in uploaded files.
    supported_languages: list[str] = ["ta-IN", "en-IN", "hi-IN"]
    language_aliases: dict[str, str] = {
        "tamil": "ta-IN",
        "english": "en-IN",
        "hindi": "hi-IN",
        "telugu": "te-IN",
        "kannada": "kn-IN",
        "malayalam": "ml-IN",
        "marathi": "mr-IN",
        "bengali": "bn-IN",
    }

    # ---- Calling ----
    # disabled: no calls can be placed. mock: simulated telephony, for development and tests only; every call is
    # stored as simulated. live: real calls through FreJun (Teler).
    telephony_mode: Literal["disabled", "mock", "live"] = "disabled"
    # The https address FreJun uses to reach this server (the Cloudflare tunnel), e.g. https://xyz.example.com
    public_url: str | None = None
    teler_api_key: SecretStr | None = None
    frejun_phone_number: str | None = None
    teler_timeout_seconds: int = 20

    gemini_api_key: SecretStr | None = None
    gemini_live_model: str = "gemini-3.8-live"
    # How long the caller must be silent before the agent answers (Gemini voice activity detection).
    gemini_silence_ms: int = 300
    # Hard stop for any call, whatever the script says, so a stuck call cannot run up charges.
    max_call_seconds_hard: int = 15 * 60
    # Individual calls placed from the app must fall inside these hours (campaigns have their own window).
    individual_call_window_enforced: bool = True

    # Database connection pooling; tests turn it off so connections are never shared across event loops.
    database_pool: bool = True

    @field_validator("jwt_secret", "phone_hash_key")
    @classmethod
    def _long_enough(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("must be at least 32 characters")
        return value

    @model_validator(mode="after")
    def _calling_mode(self) -> Self:
        if self.telephony_mode == "mock" and self.is_production:
            raise ValueError("TELEPHONY_MODE=mock is not allowed when APP_ENV=production")
        if self.telephony_mode == "live":
            missing = [
                name
                for name, value in (
                    ("PUBLIC_URL", self.public_url),
                    ("TELER_API_KEY", self.teler_api_key),
                    ("FREJUN_PHONE_NUMBER", self.frejun_phone_number),
                    ("GEMINI_API_KEY", self.gemini_api_key),
                )
                if not (value.get_secret_value() if isinstance(value, SecretStr) else value)
            ]
            if missing:
                raise ValueError(f"TELEPHONY_MODE=live needs {', '.join(missing)}")
            if not self.public_url.startswith("https://"):
                raise ValueError("PUBLIC_URL must start with https:// (FreJun only calls https addresses)")
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
