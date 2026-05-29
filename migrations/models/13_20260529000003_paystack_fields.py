from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        -- contributor_bank_accounts: Paystack transfer recipient code
        ALTER TABLE "contributor_bank_accounts"
            ADD COLUMN IF NOT EXISTS "paystack_recipient_code" VARCHAR(100);

        -- payout_requests: Paystack transfer code for tracking initiated transfers
        ALTER TABLE "payout_requests"
            ADD COLUMN IF NOT EXISTS "paystack_transfer_code" VARCHAR(100);
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "contributor_bank_accounts"
            DROP COLUMN IF EXISTS "paystack_recipient_code";
        ALTER TABLE "payout_requests"
            DROP COLUMN IF EXISTS "paystack_transfer_code";
    """
