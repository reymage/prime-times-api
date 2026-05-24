from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        -- Article columns
        ALTER TABLE "articles"
            ADD COLUMN IF NOT EXISTS "is_premium" BOOLEAN NOT NULL DEFAULT FALSE;
        ALTER TABLE "articles"
            ADD COLUMN IF NOT EXISTS "author_avatar" VARCHAR(500);

        -- Gating policy (single-row config table)
        CREATE TABLE IF NOT EXISTS "gating_policy" (
            "id"                    SERIAL PRIMARY KEY,
            "gating_start_date"     TIMESTAMPTZ,
            "free_article_threshold" INT NOT NULL DEFAULT 3,
            "day_pass_price_kobo"   INT NOT NULL DEFAULT 10000,
            "week_pass_price_kobo"  INT NOT NULL DEFAULT 40000,
            "updated_at"            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            "updated_by"            UUID
        );

        -- Seed default policy row
        INSERT INTO "gating_policy"
            ("free_article_threshold", "day_pass_price_kobo", "week_pass_price_kobo")
        VALUES (3, 10000, 40000)
        ON CONFLICT DO NOTHING;

        -- Premium reads tracker
        CREATE TABLE IF NOT EXISTS "premium_reads" (
            "id"         SERIAL PRIMARY KEY,
            "user_id"    UUID NOT NULL REFERENCES "users"("id") ON DELETE CASCADE,
            "article_id" UUID NOT NULL REFERENCES "articles"("id") ON DELETE CASCADE,
            "read_at"    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE ("user_id", "article_id")
        );

        -- Purchased passes
        CREATE TABLE IF NOT EXISTS "purchased_passes" (
            "id"           SERIAL PRIMARY KEY,
            "user_id"      UUID NOT NULL REFERENCES "users"("id") ON DELETE CASCADE,
            "pass_type"    VARCHAR(10) NOT NULL,
            "purchased_at" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            "expires_at"   TIMESTAMPTZ NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_purchased_passes_user_expires
            ON "purchased_passes" ("user_id", "expires_at");
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS "purchased_passes";
        DROP TABLE IF EXISTS "premium_reads";
        DROP TABLE IF EXISTS "gating_policy";
        ALTER TABLE "articles" DROP COLUMN IF EXISTS "author_avatar";
        ALTER TABLE "articles" DROP COLUMN IF EXISTS "is_premium";
    """
