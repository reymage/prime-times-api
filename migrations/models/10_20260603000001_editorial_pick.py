from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "console_stories"
            ADD COLUMN IF NOT EXISTS "is_editorial_pick" BOOL NOT NULL DEFAULT FALSE;
        ALTER TABLE "articles"
            ADD COLUMN IF NOT EXISTS "is_editorial_pick" BOOL NOT NULL DEFAULT FALSE;
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "articles" DROP COLUMN IF EXISTS "is_editorial_pick";
        ALTER TABLE "console_stories" DROP COLUMN IF EXISTS "is_editorial_pick";
    """
