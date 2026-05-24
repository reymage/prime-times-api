from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "user_preferences"
        ADD COLUMN IF NOT EXISTS "city" VARCHAR(100) NOT NULL DEFAULT 'Lagos';
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "user_preferences" DROP COLUMN IF EXISTS "city";
    """
