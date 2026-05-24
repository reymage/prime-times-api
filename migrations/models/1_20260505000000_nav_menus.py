from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "nav_menus" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "label" VARCHAR(100) NOT NULL,
    "slug" VARCHAR(120) NOT NULL UNIQUE,
    "href" VARCHAR(255),
    "area" VARCHAR(20) NOT NULL DEFAULT 'main',
    "item_type" VARCHAR(20) NOT NULL DEFAULT 'primary',
    "position" INT NOT NULL DEFAULT 0,
    "is_active" BOOL NOT NULL DEFAULT TRUE,
    "roles" JSONB,
    "created_at" TIMESTAMPTZ NOT NULL,
    "updated_at" TIMESTAMPTZ NOT NULL
);
COMMENT ON COLUMN "nav_menus"."area" IS 'main: main\nconsole: console';
COMMENT ON COLUMN "nav_menus"."item_type" IS 'primary: primary\ncategory: category\nbreaking: breaking';

-- ── Main area: primary nav items ───────────────────────────────────────────
INSERT INTO nav_menus (label, slug, href, area, item_type, position, is_active, roles, created_at, updated_at) VALUES
  ('News',         'news',         NULL,              'main', 'primary', 0, TRUE, NULL, NOW(), NOW()),
  ('Weekly Brief', 'weekly-brief', '/week-brief',     'main', 'primary', 1, TRUE, NULL, NOW(), NOW()),
  ('Politics',     'politics',     '/category/politics', 'main', 'primary', 2, TRUE, NULL, NOW(), NOW()),
  ('Economy',      'economy',      '/category/economy',  'main', 'primary', 3, TRUE, NULL, NOW(), NOW());

-- ── Main area: breaking / burning topics ───────────────────────────────────
INSERT INTO nav_menus (label, slug, href, area, item_type, position, is_active, roles, created_at, updated_at) VALUES
  ('Iran Tensions',  'breaking-iran-tensions',  '/', 'main', 'breaking', 0, TRUE, NULL, NOW(), NOW()),
  ('2027 Elections', 'breaking-2027-elections', '/', 'main', 'breaking', 1, TRUE, NULL, NOW(), NOW()),
  ('CBN Rate Cut',   'breaking-cbn-rate-cut',   '/', 'main', 'breaking', 2, TRUE, NULL, NOW(), NOW());

-- ── Main area: mega-menu categories ───────────────────────────────────────
INSERT INTO nav_menus (label, slug, href, area, item_type, position, is_active, roles, created_at, updated_at) VALUES
  ('Latest',          'cat-latest',          '/category/latest',          'main', 'category',  0, TRUE, NULL, NOW(), NOW()),
  ('Nigeria',         'cat-nigeria',         '/category/nigeria',         'main', 'category',  1, TRUE, NULL, NOW(), NOW()),
  ('World',           'cat-world',           '/category/world',           'main', 'category',  2, TRUE, NULL, NOW(), NOW()),
  ('Security',        'cat-security',        '/category/security',        'main', 'category',  3, TRUE, NULL, NOW(), NOW()),
  ('Technology',      'cat-technology',      '/category/technology',      'main', 'category',  4, TRUE, NULL, NOW(), NOW()),
  ('Health',          'cat-health',          '/category/health',          'main', 'category',  5, TRUE, NULL, NOW(), NOW()),
  ('Education',       'cat-education',       '/category/education',       'main', 'category',  6, TRUE, NULL, NOW(), NOW()),
  ('Environment',     'cat-environment',     '/category/environment',     'main', 'category',  7, TRUE, NULL, NOW(), NOW()),
  ('Investigations',  'cat-investigations',  '/category/investigations',  'main', 'category',  8, TRUE, NULL, NOW(), NOW()),
  ('Photo News',      'cat-photo-news',      '/category/photo-news',      'main', 'category',  9, TRUE, NULL, NOW(), NOW()),
  ('Video News',      'cat-video-news',      '/category/video-news',      'main', 'category', 10, TRUE, NULL, NOW(), NOW()),
  ('Politics',        'cat-politics',        '/category/politics',        'main', 'category', 11, TRUE, NULL, NOW(), NOW()),
  ('Money & Economy', 'cat-money-economy',   '/category/money-economy',   'main', 'category', 12, TRUE, NULL, NOW(), NOW()),
  ('Entertainment',   'cat-entertainment',   '/category/entertainment',   'main', 'category', 13, TRUE, NULL, NOW(), NOW()),
  ('Sports',          'cat-sports',          '/category/sports',          'main', 'category', 14, TRUE, NULL, NOW(), NOW());

-- ── Console area: nav items with role-based visibility ─────────────────────
INSERT INTO nav_menus (label, slug, href, area, item_type, position, is_active, roles, created_at, updated_at) VALUES
  ('Overview',        'console-overview',       '/console',           'console', 'primary', 0, TRUE, NULL,                                                                          NOW(), NOW()),
  ('Contributions',   'console-contributions',  '/console/stories',   'console', 'primary', 1, TRUE, '["contributor","reporter","editor","admin","super_admin"]'::jsonb,             NOW(), NOW()),
  ('Pending Reviews', 'console-reviews',        '/console/reviews',   'console', 'primary', 2, TRUE, '["editor","admin","super_admin"]'::jsonb,                                     NOW(), NOW()),
  ('Issue Trackers',  'console-issues',         '/console/issues',    'console', 'primary', 3, TRUE, '["reporter","editor","admin","super_admin"]'::jsonb,                          NOW(), NOW()),
  ('Earnings',        'console-earnings',       '/console/earnings',  'console', 'primary', 4, TRUE, NULL,                                                                          NOW(), NOW()),
  ('Portfolio',       'console-portfolio',      '/console/portfolio', 'console', 'primary', 5, TRUE, '["contributor","reporter","editor","admin","super_admin"]'::jsonb,             NOW(), NOW());
"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS "nav_menus";
"""
