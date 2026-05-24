from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "users" ADD COLUMN "avatar_url" VARCHAR(500);
        ALTER TABLE "users" ADD COLUMN "phone" VARCHAR(20);
        ALTER TABLE "users" ADD COLUMN "state" VARCHAR(100);
        ALTER TABLE "users" ADD COLUMN "is_diaspora" BOOL NOT NULL DEFAULT false;

        CREATE TABLE "user_preferences" (
            "id" SERIAL NOT NULL PRIMARY KEY,
            "user_id" UUID NOT NULL REFERENCES "users" ("id") ON DELETE CASCADE,
            "topics" JSONB NOT NULL DEFAULT '[]',
            "notify_breaking" BOOL NOT NULL DEFAULT true,
            "notify_digest" BOOL NOT NULL DEFAULT true,
            "updated_at" TIMESTAMPTZ NOT NULL,
            CONSTRAINT "uid_user_prefer_user_id" UNIQUE ("user_id")
        );"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS "user_preferences";
        ALTER TABLE "users" DROP COLUMN IF EXISTS "is_diaspora";
        ALTER TABLE "users" DROP COLUMN IF EXISTS "state";
        ALTER TABLE "users" DROP COLUMN IF EXISTS "phone";
        ALTER TABLE "users" DROP COLUMN IF EXISTS "avatar_url";"""
