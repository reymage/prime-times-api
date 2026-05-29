from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "issue_clusters"
            ADD COLUMN IF NOT EXISTS "breaking_expires_at" TIMESTAMPTZ;

        ALTER TABLE "articles"
            ADD COLUMN IF NOT EXISTS "issue_cluster_id" UUID REFERENCES "issue_clusters" ("id") ON DELETE SET NULL;

        CREATE INDEX IF NOT EXISTS "idx_articles_issue_cluster" ON "articles" ("issue_cluster_id");

        UPDATE articles a
        SET issue_cluster_id = cs.issue_cluster_id
        FROM console_stories cs
        WHERE a.source_url = 'ptd:console:' || cs.id::text
          AND cs.issue_cluster_id IS NOT NULL
          AND cs.status = 'publish';
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP INDEX IF EXISTS "idx_articles_issue_cluster";
        ALTER TABLE "articles" DROP COLUMN IF EXISTS "issue_cluster_id";
        ALTER TABLE "issue_clusters" DROP COLUMN IF EXISTS "breaking_expires_at";
    """
