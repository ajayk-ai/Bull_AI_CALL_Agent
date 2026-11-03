"""Application settings, read from environment variables (and `.env` in development)."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
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

    @field_validator("jwt_secret", "phone_hash_key")
    @classmethod
    def _long_enough(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("must be at least 32 characters")
        return value

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
