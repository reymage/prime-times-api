from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "console_stories" (
    "id" UUID NOT NULL PRIMARY KEY,
    "title" VARCHAR(500) NOT NULL DEFAULT '',
    "standfirst" TEXT NOT NULL DEFAULT '',
    "sections" JSONB NOT NULL DEFAULT '[]',
    "cover_image" VARCHAR(500),
    "category" VARCHAR(100) NOT NULL DEFAULT '',
    "tags" JSONB NOT NULL DEFAULT '[]',
    "story_type" VARCHAR(50) NOT NULL DEFAULT 'article',
    "status" VARCHAR(20) NOT NULL DEFAULT 'auto_draft',
    "scheduled_for" TIMESTAMPTZ,
    "word_count" INT NOT NULL DEFAULT 0,
    "editor_note" TEXT,
    "revision_of_id" UUID REFERENCES "console_stories" ("id") ON DELETE SET NULL,
    "author_id" UUID NOT NULL REFERENCES "users" ("id") ON DELETE CASCADE,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON COLUMN "console_stories"."status" IS 'publish: publish\ndraft: draft\npending_review: pending_review\nfuture: future\nauto_draft: auto_draft\ntrash: trash\nrevision: revision';
CREATE INDEX IF NOT EXISTS "idx_console_stories_author" ON "console_stories" ("author_id");
CREATE INDEX IF NOT EXISTS "idx_console_stories_status" ON "console_stories" ("status");
CREATE INDEX IF NOT EXISTS "idx_console_stories_updated" ON "console_stories" ("updated_at");
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS "console_stories";
    """
