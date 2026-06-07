from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "articles" ADD COLUMN IF NOT EXISTS "unique_view_count" INT NOT NULL DEFAULT 0;

        CREATE TABLE IF NOT EXISTS "article_views" (
            "id"         SERIAL       NOT NULL PRIMARY KEY,
            "article_id" UUID         NOT NULL,
            "device_id"  VARCHAR(64)  NOT NULL,
            "created_at" TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            CONSTRAINT "uid_article_views_article_device" UNIQUE ("article_id", "device_id")
        );
        CREATE INDEX IF NOT EXISTS "idx_article_views_article" ON "article_views" ("article_id");

        CREATE TABLE IF NOT EXISTS "article_feedback" (
            "id"         SERIAL       NOT NULL PRIMARY KEY,
            "article_id" UUID         NOT NULL,
            "device_id"  VARCHAR(64)  NOT NULL,
            "helpful"    BOOL         NOT NULL,
            "created_at" TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            "updated_at" TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            CONSTRAINT "uid_article_feedback_article_device" UNIQUE ("article_id", "device_id")
        );
        CREATE INDEX IF NOT EXISTS "idx_article_feedback_article" ON "article_feedback" ("article_id");

        -- Seed unique_view_count from the existing raw counter so portfolios
        -- aren't reset to zero on rollout.
        UPDATE "articles" SET "unique_view_count" = "view_count" WHERE "unique_view_count" = 0;
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS "article_feedback";
        DROP TABLE IF EXISTS "article_views";
        ALTER TABLE "articles" DROP COLUMN IF EXISTS "unique_view_count";
    """
