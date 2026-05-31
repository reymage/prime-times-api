from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "saved_articles" (
            "id" SERIAL NOT NULL PRIMARY KEY,
            "saved_at" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            "user_id" UUID NOT NULL REFERENCES "users" ("id") ON DELETE CASCADE,
            "article_id" UUID NOT NULL REFERENCES "articles" ("id") ON DELETE CASCADE,
            CONSTRAINT "uid_saved_artic_user_id" UNIQUE ("user_id", "article_id")
        );
        CREATE INDEX IF NOT EXISTS "idx_saved_articles_user_id" ON "saved_articles" ("user_id");
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS "saved_articles";
    """
