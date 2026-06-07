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
        # Keep a warm pool so requests reuse open connections rather than
        # repeating the multi-second TLS+SCRAM handshake to the remote DB.
        # minsize/maxsize are consumed by Tortoise's asyncpg client;
        # max_inactive_connection_lifetime is forwarded to asyncpg.create_pool.
        "minsize": settings.DB_POOL_MIN_SIZE,
        "maxsize": settings.DB_POOL_MAX_SIZE,
        "max_inactive_connection_lifetime": settings.DB_POOL_MAX_INACTIVE_LIFETIME,
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
                "app.contributors.models",
                "app.notifications.models",
                "aerich.models",
            ],
            "default_connection": "default",
        }
    },
}
