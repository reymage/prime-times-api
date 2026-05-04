import json

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── Core ──────────────────────────────────────────────────────────────────
    DATABASE_URL: str
    SECRET_KEY: str
    ENVIRONMENT: str = "development"

    # ── Security ──────────────────────────────────────────────────────────────
    # Accept a JSON array string: '["https://example.com"]'
    # or comma-separated: 'https://example.com,https://www.example.com'
    CORS_ORIGINS: list[str] = ["http://localhost:5173"]
    ALLOWED_HOSTS: list[str] = ["*"]

    # ── Rate limiting ─────────────────────────────────────────────────────────
    RATE_LIMIT_DEFAULT: str = "100/minute"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @field_validator("CORS_ORIGINS", "ALLOWED_HOSTS", mode="before")
    @classmethod
    def parse_string_list(cls, v: object) -> list[str]:
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            stripped = v.strip()
            if stripped.startswith("["):
                return json.loads(stripped)
            return [item.strip() for item in stripped.split(",") if item.strip()]
        return v  # type: ignore[return-value]

    @model_validator(mode="after")
    def validate_production_requirements(self) -> "Settings":
        if self.ENVIRONMENT == "production":
            if len(self.SECRET_KEY) < 32:
                raise ValueError("SECRET_KEY must be at least 32 characters in production")
            if "changethistosomethingverylongandrandominproduction" in self.SECRET_KEY:
                raise ValueError("SECRET_KEY must not use the example default in production")
            if "*" in self.ALLOWED_HOSTS:
                raise ValueError("ALLOWED_HOSTS must not contain '*' in production")
        return self

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"


settings = Settings()
