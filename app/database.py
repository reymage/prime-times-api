from urllib.parse import urlparse

from app.config import settings


def _build_connection(url: str) -> dict:
    p = urlparse(url)
    creds = {
        "host": p.hostname,
        "port": p.port or 5432,
        "user": p.username,
        "password": p.password,
        "database": p.path.lstrip("/"),
        # Disables prepared-statement caching so asyncpg works behind
        # PgBouncer (Supabase pooler uses transaction mode by default).
        "statement_cache_size": 0,
    }
    if p.hostname and ".supabase." in p.hostname:
        creds["ssl"] = "require"
    return {"engine": "tortoise.backends.asyncpg", "credentials": creds}


TORTOISE_ORM = {
    "connections": {
        "default": _build_connection(settings.DATABASE_URL)
    },
    "apps": {
        "models": {
            "models": [
                "app.auth.models",
                "app.nav.models",
                "app.articles.models",
                "app.gating.models",
                "app.ai.models",
                "app.console.models",
                "aerich.models",
            ],
            "default_connection": "default",
        }
    },
}
