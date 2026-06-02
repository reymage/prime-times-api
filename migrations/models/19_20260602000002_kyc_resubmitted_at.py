from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "contributor_kyc"
            ADD COLUMN IF NOT EXISTS "resubmitted_at" TIMESTAMPTZ;
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "contributor_kyc"
            DROP COLUMN IF EXISTS "resubmitted_at";
    """
