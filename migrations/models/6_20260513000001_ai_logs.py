from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "ai_logs" (
            "id"                UUID          NOT NULL PRIMARY KEY,
            "reporter_id"       VARCHAR(255)  NOT NULL,
            "endpoint"          VARCHAR(20)   NOT NULL,
            "story_type"        VARCHAR(50),
            "llm_provider"      VARCHAR(30),
            "llm_model"         VARCHAR(100),
            "llm_input_tokens"  INT           NOT NULL DEFAULT 0,
            "llm_output_tokens" INT           NOT NULL DEFAULT 0,
            "llm_cost_usd"      DECIMAL(12,8) NOT NULL DEFAULT 0,
            "tavily_searches"   INT           NOT NULL DEFAULT 0,
            "tavily_cost_usd"   DECIMAL(12,8) NOT NULL DEFAULT 0,
            "cache_hit"         BOOL          NOT NULL DEFAULT FALSE,
            "attempts"          INT           NOT NULL DEFAULT 0,
            "rewrites"          INT           NOT NULL DEFAULT 0,
            "score"             INT,
            "success"           BOOL          NOT NULL DEFAULT TRUE,
            "error_code"        VARCHAR(50),
            "duration_ms"       INT           NOT NULL DEFAULT 0,
            "created_at"        TIMESTAMPTZ   NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS "idx_ai_logs_reporter_id" ON "ai_logs" ("reporter_id");
        CREATE INDEX IF NOT EXISTS "idx_ai_logs_created_at"  ON "ai_logs" ("created_at");
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return 'DROP TABLE IF EXISTS "ai_logs";'
