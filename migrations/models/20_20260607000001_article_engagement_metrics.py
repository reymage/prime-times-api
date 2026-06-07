from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "articles" ADD COLUMN IF NOT EXISTS "share_count" INT NOT NULL DEFAULT 0;
        ALTER TABLE "articles" ADD COLUMN IF NOT EXISTS "helpful_yes" INT NOT NULL DEFAULT 0;
        ALTER TABLE "articles" ADD COLUMN IF NOT EXISTS "helpful_no"  INT NOT NULL DEFAULT 0;
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "articles" DROP COLUMN IF EXISTS "share_count";
        ALTER TABLE "articles" DROP COLUMN IF EXISTS "helpful_yes";
        ALTER TABLE "articles" DROP COLUMN IF EXISTS "helpful_no";
    """
