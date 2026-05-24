from app.config import settings

TORTOISE_ORM = {
    "connections": {
        "default": settings.DATABASE_URL
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
