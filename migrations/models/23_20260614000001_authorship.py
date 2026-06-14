from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        -- ── User stable slug ────────────────────────────────────────────────
        ALTER TABLE "users" ADD COLUMN IF NOT EXISTS "slug" VARCHAR(120);

        -- Backfill a unique, readable slug for every existing user.
        WITH base AS (
            SELECT
                id,
                COALESCE(
                    NULLIF(
                        trim(both '-' FROM regexp_replace(
                            lower(COALESCE(NULLIF(display_name, ''), split_part(email, '@', 1))),
                            '[^a-z0-9]+', '-', 'g'
                        )),
                        ''
                    ),
                    'user'
                ) AS b,
                created_at
            FROM "users"
        ),
        numbered AS (
            SELECT id, b,
                   ROW_NUMBER() OVER (PARTITION BY b ORDER BY created_at, id) AS rn
            FROM base
        )
        UPDATE "users" u
        SET "slug" = CASE WHEN n.rn = 1 THEN n.b ELSE n.b || '-' || n.rn END
        FROM numbered n
        WHERE u.id = n.id AND u."slug" IS NULL;

        CREATE UNIQUE INDEX IF NOT EXISTS "uid_users_slug" ON "users" ("slug");

        -- ── Article stable author link + cached slug ────────────────────────
        ALTER TABLE "articles" ADD COLUMN IF NOT EXISTS "author_id" UUID;
        ALTER TABLE "articles" ADD COLUMN IF NOT EXISTS "author_slug" VARCHAR(120);
        CREATE INDEX IF NOT EXISTS "idx_articles_author_id" ON "articles" ("author_id");
        CREATE INDEX IF NOT EXISTS "idx_articles_author_slug" ON "articles" ("author_slug");

        -- Backfill the link from the originating console story's author. (At this
        -- point no story has an assignee, so byline author == story author.)
        UPDATE "articles" a
        SET "author_id" = cs."author_id",
            "author_slug" = u."slug"
        FROM "console_stories" cs
        JOIN "users" u ON u.id = cs."author_id"
        WHERE a."console_story_id" = cs.id;

        -- ── Console story assignment + edit audit ───────────────────────────
        ALTER TABLE "console_stories" ADD COLUMN IF NOT EXISTS "assigned_to_id" UUID
            REFERENCES "users" ("id") ON DELETE SET NULL;
        ALTER TABLE "console_stories" ADD COLUMN IF NOT EXISTS "last_edited_by_id" UUID
            REFERENCES "users" ("id") ON DELETE SET NULL;
        ALTER TABLE "console_stories" ADD COLUMN IF NOT EXISTS "last_edited_at" TIMESTAMPTZ;
        CREATE INDEX IF NOT EXISTS "idx_console_stories_assigned" ON "console_stories" ("assigned_to_id");
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "console_stories" DROP COLUMN IF EXISTS "last_edited_at";
        ALTER TABLE "console_stories" DROP COLUMN IF EXISTS "last_edited_by_id";
        ALTER TABLE "console_stories" DROP COLUMN IF EXISTS "assigned_to_id";
        DROP INDEX IF EXISTS "idx_articles_author_slug";
        DROP INDEX IF EXISTS "idx_articles_author_id";
        ALTER TABLE "articles" DROP COLUMN IF EXISTS "author_slug";
        ALTER TABLE "articles" DROP COLUMN IF EXISTS "author_id";
        DROP INDEX IF EXISTS "uid_users_slug";
        ALTER TABLE "users" DROP COLUMN IF EXISTS "slug";
    """
