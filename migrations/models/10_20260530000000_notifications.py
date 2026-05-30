from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "notifications" (
            "id" UUID NOT NULL PRIMARY KEY,
            "notif_type" VARCHAR(40) NOT NULL,
            "title" VARCHAR(200) NOT NULL,
            "body" TEXT NOT NULL DEFAULT '',
            "link" VARCHAR(500),
            "is_read" BOOLEAN NOT NULL DEFAULT FALSE,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            "recipient_id" UUID NOT NULL REFERENCES "users" ("id") ON DELETE CASCADE,
            "sender_id" UUID REFERENCES "users" ("id") ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS "idx_notifications_recipient_read"
            ON "notifications" ("recipient_id", "is_read");
        CREATE INDEX IF NOT EXISTS "idx_notifications_created"
            ON "notifications" ("created_at");
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS "notifications";
    """
