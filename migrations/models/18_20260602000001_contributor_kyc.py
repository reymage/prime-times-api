from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "contributor_kyc" (
            "id" UUID NOT NULL PRIMARY KEY DEFAULT gen_random_uuid(),
            "status" VARCHAR(20) NOT NULL DEFAULT 'pending',
            "full_name" VARCHAR(300) NOT NULL,
            "nin_or_bvn" VARCHAR(50) NOT NULL,
            "document_type" VARCHAR(30) NOT NULL,
            "document_url" VARCHAR(500) NOT NULL,
            "reviewer_note" VARCHAR(1000),
            "submitted_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            "reviewed_at" TIMESTAMPTZ,
            "contributor_id" UUID NOT NULL UNIQUE REFERENCES "users" ("id") ON DELETE CASCADE,
            "reviewed_by_id" UUID REFERENCES "users" ("id") ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS "idx_contributor_kyc_status" ON "contributor_kyc" ("status");
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS "contributor_kyc";
    """
