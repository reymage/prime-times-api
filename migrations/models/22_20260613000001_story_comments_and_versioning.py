from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "console_stories" ADD COLUMN IF NOT EXISTS "version" INT NOT NULL DEFAULT 1;
        CREATE TABLE IF NOT EXISTS "story_comments" (
            "id" UUID NOT NULL PRIMARY KEY,
            "body" TEXT NOT NULL,
            "is_resolved" BOOLEAN NOT NULL DEFAULT FALSE,
            "resolved_at" TIMESTAMPTZ,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            "story_id" UUID NOT NULL REFERENCES "console_stories" ("id") ON DELETE CASCADE,
            "author_id" UUID NOT NULL REFERENCES "users" ("id") ON DELETE CASCADE,
            "resolved_by_id" UUID REFERENCES "users" ("id") ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS "idx_story_comments_story" ON "story_comments" ("story_id");
        CREATE INDEX IF NOT EXISTS "idx_story_comments_created" ON "story_comments" ("created_at");
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS "story_comments";
        ALTER TABLE "console_stories" DROP COLUMN IF EXISTS "version";
    """
