import json

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _split_comma_list(value: str) -> list[str]:
    stripped = value.strip()
    if stripped.startswith("["):
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed]
        except json.JSONDecodeError:
            stripped = stripped.strip("[]")
    return [x.strip().strip("\"'") for x in stripped.split(",") if x.strip().strip("\"'")]


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
    # Stored as str (not list[str]) so pydantic_settings doesn't try to
    # JSON-parse the env var value before our code can handle it.
    # The CORS_ORIGINS / ALLOWED_HOSTS properties below parse them on demand.
    CORS_ORIGINS_RAW: str = Field(default="http://localhost:5173", alias="CORS_ORIGINS")
    ALLOWED_HOSTS_RAW: str = Field(default="*", alias="ALLOWED_HOSTS")

    @property
    def CORS_ORIGINS(self) -> list[str]:
        return _split_comma_list(self.CORS_ORIGINS_RAW)

    @property
    def ALLOWED_HOSTS(self) -> list[str]:
        return _split_comma_list(self.ALLOWED_HOSTS_RAW)

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

    # ── Paystack ──────────────────────────────────────────────────────────────
    # Swap PAYSTACK_SECRET_KEY to switch between Reymage account and company account.
    # sk_test_... = test mode, sk_live_... = live mode — no code change needed.
    PAYSTACK_SECRET_KEY: str = ""
    PAYSTACK_WEBHOOK_SECRET: str = ""      # from Paystack dashboard → Settings → Webhooks
    PAYSTACK_ENABLED: bool = False         # set True once keys are configured

    @property
    def paystack_live(self) -> bool:
        return self.PAYSTACK_ENABLED and bool(self.PAYSTACK_SECRET_KEY)

    # ── Cloudflare R2 (media storage) ────────────────────────────────────────
    R2_ACCOUNT_ID: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET_NAME: str = ""
    R2_PUBLIC_URL: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
    )

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
