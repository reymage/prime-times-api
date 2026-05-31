from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        -- users: public author profile fields
        ALTER TABLE "users"
            ADD COLUMN IF NOT EXISTS "bio" TEXT,
            ADD COLUMN IF NOT EXISTS "linkedin_url" VARCHAR(300),
            ADD COLUMN IF NOT EXISTS "twitter_url" VARCHAR(300),
            ADD COLUMN IF NOT EXISTS "public_email" VARCHAR(320);

        -- DB indexes: notification queries
        CREATE INDEX IF NOT EXISTS "idx_notifications_recipient_id"
            ON "notifications" ("recipient_id");
        CREATE INDEX IF NOT EXISTS "idx_notifications_is_read"
            ON "notifications" ("is_read");

        -- DB indexes: payout requests
        CREATE INDEX IF NOT EXISTS "idx_payout_requests_status"
            ON "payout_requests" ("status");
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "users"
            DROP COLUMN IF EXISTS "bio",
            DROP COLUMN IF EXISTS "linkedin_url",
            DROP COLUMN IF EXISTS "twitter_url",
            DROP COLUMN IF EXISTS "public_email";

        DROP INDEX IF EXISTS "idx_notifications_recipient_id";
        DROP INDEX IF EXISTS "idx_notifications_is_read";
        DROP INDEX IF EXISTS "idx_payout_requests_status";
    """
