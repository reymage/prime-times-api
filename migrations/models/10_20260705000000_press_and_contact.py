from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "press_releases" (
            "id" UUID NOT NULL PRIMARY KEY,
            "slug" VARCHAR(220) NOT NULL UNIQUE,
            "title" VARCHAR(500) NOT NULL,
            "excerpt" TEXT NOT NULL DEFAULT '',
            "content" TEXT NOT NULL DEFAULT '',
            "category" VARCHAR(100) NOT NULL DEFAULT 'Announcement',
            "image_url" VARCHAR(500) NOT NULL DEFAULT '',
            "is_featured" BOOL NOT NULL DEFAULT FALSE,
            "is_published" BOOL NOT NULL DEFAULT TRUE,
            "published_at" TIMESTAMPTZ NOT NULL,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS "idx_press_releases_slug" ON "press_releases" ("slug");
        CREATE INDEX IF NOT EXISTS "idx_press_releases_category" ON "press_releases" ("category");
        CREATE INDEX IF NOT EXISTS "idx_press_releases_published" ON "press_releases" ("published_at");

        CREATE TABLE IF NOT EXISTS "contact_messages" (
            "id" SERIAL NOT NULL PRIMARY KEY,
            "name" VARCHAR(200) NOT NULL,
            "email" VARCHAR(320) NOT NULL,
            "organisation" VARCHAR(200),
            "reason" VARCHAR(30) NOT NULL DEFAULT 'other',
            "subject" VARCHAR(300) NOT NULL DEFAULT '',
            "message" TEXT NOT NULL,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS "idx_contact_messages_created" ON "contact_messages" ("created_at");
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS "contact_messages";
        DROP TABLE IF EXISTS "press_releases";
    """
