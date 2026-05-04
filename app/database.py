from app.config import settings

TORTOISE_ORM = {
    "connections": {
        "default": settings.DATABASE_URL
    },
    "apps": {
        "models": {
            "models": [
                "app.auth.models",
                "aerich.models",
            ],
            "default_connection": "default",
        }
    },
}
