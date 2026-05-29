from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        -- ── articles: link back to the ConsoleStory that produced this article ─
        ALTER TABLE "articles"
            ADD COLUMN IF NOT EXISTS "console_story_id" UUID;
        CREATE INDEX IF NOT EXISTS "idx_articles_console_story_id"
            ON "articles" ("console_story_id");

        -- ── paywall_read_events: per-reader per-story paywall unlock events ─────
        -- One row per unique (reader, story) pair. Used as the authoritative read
        -- source for contributor reward distribution (replaces lifetime counter).
        CREATE TABLE IF NOT EXISTS "paywall_read_events" (
            "id"               SERIAL PRIMARY KEY,
            "read_at"          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            "console_story_id" UUID NOT NULL REFERENCES "console_stories" ("id") ON DELETE CASCADE,
            "reader_id"        UUID NOT NULL REFERENCES "users" ("id") ON DELETE CASCADE,
            UNIQUE ("console_story_id", "reader_id")
        );
        CREATE INDEX IF NOT EXISTS "idx_paywall_read_events_story"
            ON "paywall_read_events" ("console_story_id");
        CREATE INDEX IF NOT EXISTS "idx_paywall_read_events_reader"
            ON "paywall_read_events" ("reader_id");
        CREATE INDEX IF NOT EXISTS "idx_paywall_read_events_read_at"
            ON "paywall_read_events" ("read_at");

        -- ── contributor_bank_accounts: one per contributor ─────────────────────
        CREATE TABLE IF NOT EXISTS "contributor_bank_accounts" (
            "id"             UUID NOT NULL PRIMARY KEY,
            "account_name"   VARCHAR(200) NOT NULL,
            "bank_code"      VARCHAR(20) NOT NULL,
            "bank_name"      VARCHAR(200) NOT NULL,
            "account_number" VARCHAR(20) NOT NULL,
            "is_verified"    BOOLEAN NOT NULL DEFAULT FALSE,
            "created_at"     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            "updated_at"     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            "contributor_id" UUID NOT NULL UNIQUE REFERENCES "users" ("id") ON DELETE CASCADE
        );

        -- ── payout_requests ────────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS "payout_requests" (
            "id"                     UUID NOT NULL PRIMARY KEY,
            "requested_amount"       NUMERIC(14,2) NOT NULL,
            "bank_account_snapshot"  JSONB NOT NULL,
            "status"                 VARCHAR(20) NOT NULL DEFAULT 'pending_admin',
            "admin_note"             TEXT,
            "approved_at"            TIMESTAMPTZ,
            "paid_at"                TIMESTAMPTZ,
            "created_at"             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            "updated_at"             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            "contributor_id"         UUID NOT NULL REFERENCES "users" ("id") ON DELETE CASCADE,
            "approved_by_id"         UUID REFERENCES "users" ("id") ON DELETE SET NULL
        );
        COMMENT ON COLUMN "payout_requests"."status"
            IS 'pending_admin | approved | processing | paid | rejected | failed';
        CREATE INDEX IF NOT EXISTS "idx_payout_requests_contributor"
            ON "payout_requests" ("contributor_id");
        CREATE INDEX IF NOT EXISTS "idx_payout_requests_status"
            ON "payout_requests" ("status");

        -- ── payout_request_earnings: junction (payout ↔ earnings) ──────────────
        CREATE TABLE IF NOT EXISTS "payout_request_earnings" (
            "id"                 UUID NOT NULL PRIMARY KEY,
            "payout_request_id"  UUID NOT NULL REFERENCES "payout_requests" ("id") ON DELETE CASCADE,
            "earning_id"         UUID NOT NULL REFERENCES "contributor_earnings" ("id") ON DELETE CASCADE,
            UNIQUE ("payout_request_id", "earning_id")
        );
        CREATE INDEX IF NOT EXISTS "idx_payout_req_earnings_payout"
            ON "payout_request_earnings" ("payout_request_id");
        CREATE INDEX IF NOT EXISTS "idx_payout_req_earnings_earning"
            ON "payout_request_earnings" ("earning_id");
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS "payout_request_earnings";
        DROP TABLE IF EXISTS "payout_requests";
        DROP TABLE IF EXISTS "contributor_bank_accounts";
        DROP TABLE IF EXISTS "paywall_read_events";
        DROP INDEX IF EXISTS "idx_articles_console_story_id";
        ALTER TABLE "articles" DROP COLUMN IF EXISTS "console_story_id";
    """
