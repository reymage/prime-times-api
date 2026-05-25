from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "issue_clusters" (
            "id" UUID NOT NULL PRIMARY KEY,
            "name" VARCHAR(200) NOT NULL,
            "slug" VARCHAR(220) NOT NULL UNIQUE,
            "description" TEXT NOT NULL DEFAULT '',
            "category" VARCHAR(100) NOT NULL DEFAULT '',
            "status" VARCHAR(20) NOT NULL DEFAULT 'active',
            "breaking_order" INT,
            "cover_image" VARCHAR(500),
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            "created_by_id" UUID NOT NULL REFERENCES "users" ("id") ON DELETE CASCADE,
            "assigned_editor_id" UUID REFERENCES "users" ("id") ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS "idx_issue_clusters_status" ON "issue_clusters" ("status");
        CREATE INDEX IF NOT EXISTS "idx_issue_clusters_updated" ON "issue_clusters" ("updated_at");
        ALTER TABLE "console_stories"
            ADD COLUMN IF NOT EXISTS "issue_cluster_id" UUID REFERENCES "issue_clusters" ("id") ON DELETE SET NULL;
        CREATE INDEX IF NOT EXISTS "idx_console_stories_issue" ON "console_stories" ("issue_cluster_id");
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP INDEX IF EXISTS "idx_console_stories_issue";
        ALTER TABLE "console_stories" DROP COLUMN IF EXISTS "issue_cluster_id";
        DROP TABLE IF EXISTS "issue_clusters";
    """
