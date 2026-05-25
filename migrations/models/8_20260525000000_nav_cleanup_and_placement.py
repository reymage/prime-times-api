from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        -- ── Remove stale / incorrect console nav items (from seed script) ─────────
        DELETE FROM nav_menus WHERE slug IN (
            'console-dashboard',
            'console-articles',
            'console-editors'
        );

        -- ── Rename and reorganise existing console nav items ─────────────────────
        -- Overview → Dashboard
        UPDATE nav_menus SET label = 'Dashboard', position = 0
            WHERE slug = 'console-overview';

        -- Contributions → My Stories (all writing roles)
        UPDATE nav_menus
            SET label   = 'My Stories',
                slug    = 'console-stories',
                roles   = '["contributor","columnist","reporter","editor","admin","super_admin"]'::jsonb,
                position = 1
            WHERE slug = 'console-contributions';

        -- Remove Pending Reviews from main nav (it lives inside the Stories page for editors)
        DELETE FROM nav_menus WHERE slug = 'console-reviews';

        -- Issue Trackers → Issues (reporters + editors)
        UPDATE nav_menus
            SET label    = 'Issues',
                slug     = 'console-issues-v2',
                roles    = '["reporter","editor","admin","super_admin"]'::jsonb,
                position = 2
            WHERE slug = 'console-issues';

        -- Add Research nav item (reporters + editors)
        INSERT INTO nav_menus (label, slug, href, area, item_type, position, is_active, roles, created_at, updated_at)
        VALUES (
            'Research', 'console-research', '/console/research',
            'console', 'primary', 3, TRUE,
            '["reporter","editor","admin","super_admin"]'::jsonb,
            NOW(), NOW()
        )
        ON CONFLICT (slug) DO NOTHING;

        -- Earnings stays, update position
        UPDATE nav_menus SET position = 4 WHERE slug = 'console-earnings';

        -- Portfolio stays (all writing roles), update position
        UPDATE nav_menus
            SET roles    = '["contributor","columnist","reporter","editor","admin","super_admin"]'::jsonb,
                position = 5
            WHERE slug = 'console-portfolio';

        -- Add columnist to UserRole enum on the users table if it exists as a check constraint
        -- (No-op if the backend uses a plain VARCHAR for role — safe to include)
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'users' AND column_name = 'role'
            ) THEN
                ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check;
                ALTER TABLE users ADD CONSTRAINT users_role_check
                    CHECK (role IN ('reader','contributor','columnist','reporter','editor','admin','super_admin'));
            END IF;
        END $$;

        -- ── Add placement fields to console_stories ───────────────────────────────
        ALTER TABLE console_stories
            ADD COLUMN IF NOT EXISTS geo_regions  JSONB        NOT NULL DEFAULT '[]',
            ADD COLUMN IF NOT EXISTS is_featured  BOOLEAN      NOT NULL DEFAULT FALSE;
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE console_stories
            DROP COLUMN IF EXISTS geo_regions,
            DROP COLUMN IF EXISTS is_featured;

        DELETE FROM nav_menus WHERE slug IN ('console-research', 'console-stories');

        UPDATE nav_menus SET label = 'Overview', slug = 'console-overview'  WHERE slug = 'console-dashboard' OR label = 'Dashboard';
        UPDATE nav_menus SET label = 'Contributions', slug = 'console-contributions' WHERE slug = 'console-stories';
        UPDATE nav_menus SET label = 'Issue Trackers', slug = 'console-issues' WHERE slug = 'console-issues-v2';
        UPDATE nav_menus SET position = 2 WHERE slug = 'console-earnings';
        UPDATE nav_menus SET position = 3 WHERE slug = 'console-portfolio';
    """
