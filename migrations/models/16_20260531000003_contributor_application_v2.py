from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "contributor_applications"
            ADD COLUMN IF NOT EXISTS "first_name" VARCHAR(100),
            ADD COLUMN IF NOT EXISTS "last_name" VARCHAR(100),
            ADD COLUMN IF NOT EXISTS "dob" VARCHAR(20),
            ADD COLUMN IF NOT EXISTS "gender" VARCHAR(50),
            ADD COLUMN IF NOT EXISTS "state_of_residence" VARCHAR(100),
            ADD COLUMN IF NOT EXISTS "employment_status" VARCHAR(50),
            ADD COLUMN IF NOT EXISTS "phone" VARCHAR(30),
            ADD COLUMN IF NOT EXISTS "pitch" VARCHAR(280),
            ADD COLUMN IF NOT EXISTS "handle_x" VARCHAR(100),
            ADD COLUMN IF NOT EXISTS "handle_fb" VARCHAR(300),
            ADD COLUMN IF NOT EXISTS "handle_li" VARCHAR(300),
            ADD COLUMN IF NOT EXISTS "best_piece_url" VARCHAR(500),
            ADD COLUMN IF NOT EXISTS "best_work_file_url" VARCHAR(500),
            ADD COLUMN IF NOT EXISTS "reporting_methods" JSONB,
            ADD COLUMN IF NOT EXISTS "primary_vertical" VARCHAR(100),
            ADD COLUMN IF NOT EXISTS "secondary_vertical" VARCHAR(100);
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "contributor_applications"
            DROP COLUMN IF EXISTS "first_name",
            DROP COLUMN IF EXISTS "last_name",
            DROP COLUMN IF EXISTS "dob",
            DROP COLUMN IF EXISTS "gender",
            DROP COLUMN IF EXISTS "state_of_residence",
            DROP COLUMN IF EXISTS "employment_status",
            DROP COLUMN IF EXISTS "phone",
            DROP COLUMN IF EXISTS "pitch",
            DROP COLUMN IF EXISTS "handle_x",
            DROP COLUMN IF EXISTS "handle_fb",
            DROP COLUMN IF EXISTS "handle_li",
            DROP COLUMN IF EXISTS "best_piece_url",
            DROP COLUMN IF EXISTS "best_work_file_url",
            DROP COLUMN IF EXISTS "reporting_methods",
            DROP COLUMN IF EXISTS "primary_vertical",
            DROP COLUMN IF EXISTS "secondary_vertical";
    """
