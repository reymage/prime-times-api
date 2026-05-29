from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        -- ── Platform reward settings (single row) ────────────────────────────
        CREATE TABLE IF NOT EXISTS "platform_reward_settings" (
            "id"                        SERIAL PRIMARY KEY,
            "reward_start_date"         DATE,
            "contributor_revenue_share" NUMERIC(5,4) NOT NULL DEFAULT 0.6000,
            "updated_at"                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            "updated_by_id"             UUID REFERENCES "users" ("id") ON DELETE SET NULL
        );
        -- Seed the single row so GET always returns something.
        INSERT INTO "platform_reward_settings" ("id") VALUES (1) ON CONFLICT DO NOTHING;

        -- ── Contributor applications ──────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS "contributor_applications" (
            "id"                  UUID NOT NULL PRIMARY KEY,
            "bio"                 TEXT NOT NULL,
            "portfolio_url"       VARCHAR(500),
            "coverage_areas"      JSONB NOT NULL DEFAULT '[]',
            "verticals"           JSONB NOT NULL DEFAULT '[]',
            "kyc_document_type"   VARCHAR(50),
            "kyc_document_ref"    VARCHAR(200),
            "status"              VARCHAR(20) NOT NULL DEFAULT 'pending',
            "reviewer_note"       TEXT,
            "reviewed_at"         TIMESTAMPTZ,
            "submitted_at"        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            "applicant_id"        UUID NOT NULL REFERENCES "users" ("id") ON DELETE CASCADE,
            "reviewer_id"         UUID REFERENCES "users" ("id") ON DELETE SET NULL
        );
        COMMENT ON COLUMN "contributor_applications"."status"
            IS 'pending: pending\napproved: approved\nrejected: rejected';
        CREATE INDEX IF NOT EXISTS "idx_contributor_apps_applicant"
            ON "contributor_applications" ("applicant_id");
        CREATE INDEX IF NOT EXISTS "idx_contributor_apps_status"
            ON "contributor_applications" ("status");

        -- ── Contributor profiles ──────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS "contributor_profiles" (
            "id"                          UUID NOT NULL PRIMARY KEY,
            "first_published_story_date"  DATE,
            "pay_worthy_eligible"         BOOLEAN NOT NULL DEFAULT FALSE,
            "eligibility_checked_at"      TIMESTAMPTZ,
            "eligibility_override"        BOOLEAN,
            "eligibility_override_at"     TIMESTAMPTZ,
            "eligibility_override_note"   TEXT,
            "created_at"                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            "updated_at"                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            "contributor_id"              UUID NOT NULL UNIQUE REFERENCES "users" ("id") ON DELETE CASCADE,
            "eligibility_override_by_id"  UUID REFERENCES "users" ("id") ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS "idx_contributor_profiles_eligible"
            ON "contributor_profiles" ("pay_worthy_eligible");

        -- ── Paywall revenue periods ───────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS "paywall_revenue_periods" (
            "id"                     UUID NOT NULL PRIMARY KEY,
            "week_start"             DATE NOT NULL,
            "week_end"               DATE NOT NULL,
            "gross_paywall_revenue"  NUMERIC(14,2) NOT NULL DEFAULT 0.00,
            "revenue_share_pct"      NUMERIC(5,4) NOT NULL DEFAULT 0.6000,
            "contributor_pool"       NUMERIC(14,2) NOT NULL DEFAULT 0.00,
            "status"                 VARCHAR(20) NOT NULL DEFAULT 'open',
            "distributed_at"         TIMESTAMPTZ,
            "created_at"             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            "distributed_by_id"      UUID REFERENCES "users" ("id") ON DELETE SET NULL
        );
        COMMENT ON COLUMN "paywall_revenue_periods"."status"
            IS 'open: open\nclosed: closed\ndistributed: distributed';
        COMMENT ON COLUMN "paywall_revenue_periods"."gross_paywall_revenue"
            IS 'PAYWALL INCOME ONLY. Ad/sponsorship revenue must never be added here.';
        CREATE INDEX IF NOT EXISTS "idx_revenue_periods_status"
            ON "paywall_revenue_periods" ("status");
        CREATE INDEX IF NOT EXISTS "idx_revenue_periods_week"
            ON "paywall_revenue_periods" ("week_start");

        -- ── Contributor earnings ──────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS "contributor_earnings" (
            "id"               UUID NOT NULL PRIMARY KEY,
            "paywall_reads"    INT NOT NULL DEFAULT 0,
            "pool_total_reads" INT NOT NULL DEFAULT 0,
            "gross_amount"     NUMERIC(14,2) NOT NULL DEFAULT 0.00,
            "status"           VARCHAR(20) NOT NULL DEFAULT 'pending',
            "created_at"       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            "updated_at"       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            "contributor_id"   UUID NOT NULL REFERENCES "users" ("id") ON DELETE CASCADE,
            "period_id"        UUID NOT NULL REFERENCES "paywall_revenue_periods" ("id") ON DELETE CASCADE,
            UNIQUE ("contributor_id", "period_id")
        );
        COMMENT ON COLUMN "contributor_earnings"."status"
            IS 'pending: pending\napproved: approved\npaid: paid\nrejected: rejected';
        CREATE INDEX IF NOT EXISTS "idx_contributor_earnings_contributor"
            ON "contributor_earnings" ("contributor_id");
        CREATE INDEX IF NOT EXISTS "idx_contributor_earnings_period"
            ON "contributor_earnings" ("period_id");
        CREATE INDEX IF NOT EXISTS "idx_contributor_earnings_status"
            ON "contributor_earnings" ("status");

        -- ── console_stories: pay-worthy + reward columns ──────────────────────
        ALTER TABLE "console_stories"
            ADD COLUMN IF NOT EXISTS "is_pay_worthy"      BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS "pay_worthy_rubric"   JSONB,
            ADD COLUMN IF NOT EXISTS "paywall_read_count"  INT NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS "editorial_score"     INT CHECK (editorial_score BETWEEN 0 AND 100),
            ADD COLUMN IF NOT EXISTS "published_at"        TIMESTAMPTZ;

        CREATE INDEX IF NOT EXISTS "idx_console_stories_pay_worthy"
            ON "console_stories" ("is_pay_worthy");
        CREATE INDEX IF NOT EXISTS "idx_console_stories_published_at"
            ON "console_stories" ("published_at");
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP INDEX IF EXISTS "idx_console_stories_published_at";
        DROP INDEX IF EXISTS "idx_console_stories_pay_worthy";
        ALTER TABLE "console_stories"
            DROP COLUMN IF EXISTS "published_at",
            DROP COLUMN IF EXISTS "editorial_score",
            DROP COLUMN IF EXISTS "paywall_read_count",
            DROP COLUMN IF EXISTS "pay_worthy_rubric",
            DROP COLUMN IF EXISTS "is_pay_worthy";
        DROP TABLE IF EXISTS "contributor_earnings";
        DROP TABLE IF EXISTS "paywall_revenue_periods";
        DROP TABLE IF EXISTS "contributor_profiles";
        DROP TABLE IF EXISTS "contributor_applications";
        DROP TABLE IF EXISTS "platform_reward_settings";
    """
