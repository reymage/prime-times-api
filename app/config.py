import json

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── Core ──────────────────────────────────────────────────────────────────
    DATABASE_URL: str
    SECRET_KEY: str

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def normalise_db_url(cls, v: str) -> str:
        # Tortoise ORM requires postgres:// not postgresql://
        if isinstance(v, str) and v.startswith("postgresql://"):
            return "postgres" + v[len("postgresql"):]
        return v
    ENVIRONMENT: str = "development"

    # ── Security ──────────────────────────────────────────────────────────────
    CORS_ORIGINS: list[str] = ["http://localhost:5173"]
    ALLOWED_HOSTS: list[str] = ["*"]

    # ── Rate limiting ─────────────────────────────────────────────────────────
    RATE_LIMIT_DEFAULT: str = "100/minute"

    # ── JWT ───────────────────────────────────────────────────────────────────
    ACCESS_TOKEN_EXPIRE_SECONDS: int = 3600

    # ── Frontend ──────────────────────────────────────────────────────────────
    FRONTEND_URL: str = "http://localhost:8080"

    # ── Email ─────────────────────────────────────────────────────────────────
    EMAIL_PROVIDER: str = "brevo"
    BREVO_API_KEY: str = ""
    EMAIL_FROM_ADDRESS: str = "support@getweva.com"
    EMAIL_FROM_NAME: str = "Prime Times Daily"

    # ── AI / LLM ──────────────────────────────────────────────────────────────
    LLM_PROVIDER: str = "groq"                # groq | openai | anthropic
    GROQ_API_KEY: str = ""
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-3-5-haiku-20241022"

    # ── Tavily ────────────────────────────────────────────────────────────────
    TAVILY_API_KEY: str = ""

    # ── Prompts ───────────────────────────────────────────────────────────────
    PROMPTS_DIR: str = "prompts"              # relative to api/ working dir

    # ── Cache ─────────────────────────────────────────────────────────────────
    REDIS_URL: str = ""                       # empty = use in-memory LRU
    CACHE_TTL_SECONDS: int = 3600

    # ── AI rate limiting (per reporter_id) ────────────────────────────────────
    AI_RATE_LIMIT: int = 10                   # requests per window
    AI_RATE_LIMIT_WINDOW: int = 60            # seconds

    # ── Cloudflare R2 (media storage) ────────────────────────────────────────
    R2_ACCOUNT_ID: str = ""       # Cloudflare account ID (32-char hex)
    R2_ACCESS_KEY_ID: str = ""    # R2 API token → Access Key ID
    R2_SECRET_ACCESS_KEY: str = ""  # R2 API token → Secret Access Key
    R2_BUCKET_NAME: str = ""      # e.g. ptd-media
    R2_PUBLIC_URL: str = ""       # e.g. https://pub-XXXX.r2.dev  (no trailing /)

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
                raise ValueError(
                    "SECRET_KEY must be at least 32 characters in production"
                )
            if "changethistosomethingverylongandrandominproduction" in self.SECRET_KEY:
                raise ValueError(
                    "SECRET_KEY must not use the example default in production"
                )
            if "*" in self.ALLOWED_HOSTS:
                raise ValueError("ALLOWED_HOSTS must not contain '*' in production")
        return self

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"


settings = Settings()
