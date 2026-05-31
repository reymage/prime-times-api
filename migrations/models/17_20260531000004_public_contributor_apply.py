from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "contributor_applications"
            ADD COLUMN IF NOT EXISTS "email" VARCHAR(200),
            ALTER COLUMN "applicant_id" DROP NOT NULL;
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "contributor_applications"
            DROP COLUMN IF EXISTS "email";
    """
