from tortoise import BaseDBAsyncClient

# Seeds the official rebrand announcement (source: press_release.md) and
# removes any placeholder releases from earlier development seeds.

PLACEHOLDER_SLUGS = (
    "'prime-times-daily-relaunches-as-wire24',"
    "'wire24-opens-nationwide-contributor-programme',"
    "'wire24-launches-ai-assisted-newsroom-tools',"
    "'wire24-introduces-personalised-feeds-and-my-news',"
    "'lightway-media-publishes-wire24-editorial-charter'"
)


async def upgrade(db: BaseDBAsyncClient) -> str:
    return f"""
        DELETE FROM "press_releases" WHERE "slug" IN ({PLACEHOLDER_SLUGS});

        INSERT INTO "press_releases"
            ("id", "slug", "title", "excerpt", "content", "category", "is_featured", "published_at")
        VALUES (
            gen_random_uuid(),
            'prime-times-daily-rebrands-as-wire24',
            'Prime Times Daily Rebrands as Wire24',
            $$Lightway Media Ltd announces the rebranding of Prime Times Daily as Wire24 — a significant milestone in the organization's evolution, reaffirming its commitment to independent, public-interest journalism.$$,
            $$LAGOS, Nigeria — July 5, 2026 — Lightway Media Ltd today announced the rebranding of Prime Times Daily as Wire24, marking a significant milestone in the organization's evolution and reaffirming its commitment to independent, public-interest journalism.

Founded in 2019, Prime Times Daily was established with a belief that remains unchanged today—that quality journalism has the power to inform, empower, and strengthen society.

From the beginning, the publication set out to build a newsroom that valued accuracy over speed, substance over sensationalism, and public interest above everything else. Like many independent media organizations, the journey was shaped by both achievements and challenges. Changing industry dynamics, evolving audience expectations, and the realities of sustaining independent journalism required periods of reflection, strategic restructuring, and renewed focus.

Over the past several months, Lightway Media Ltd has undertaken a comprehensive transformation of its news operations, reviewing its leadership structure, strengthening its editorial philosophy, modernizing its technology, refining its newsroom strategy, and developing a clearer long-term vision for its journalism.

That transformation has culminated in the launch of Wire24.

As part of the transition, the publication's online home has moved from primetimesdaily.ng to wire24news.com, reflecting a broader ambition to build a modern, digital-first newsroom designed for the future of journalism.

"This rebranding is about far more than a new name," the company said. "It represents a renewed organization, renewed leadership, and renewed editorial ambition."

Under the Wire24 brand, the newsroom will operate with a strengthened management structure, refreshed editorial leadership, and a refined editorial direction focused on explanatory journalism, investigations, analysis, accountability reporting, and context-driven storytelling.

While Wire24 will continue reporting the news as it happens, the organization said its broader mission is to help readers understand not only what happened, but why it matters.

The company also announced plans to expand the use of AI-assisted newsroom technologies to improve research, editorial workflows, and operational efficiency, while maintaining human editorial oversight for every published story.

Lightway Media Ltd expressed appreciation to readers, contributors, advertisers, and partners who supported Prime Times Daily throughout its journey, describing their confidence and encouragement as instrumental in the organization's growth.

Although the publication's name has changed, the company emphasized that its core values remain the same.

Wire24 reaffirmed its commitment to independent journalism, factual reporting, editorial integrity, fairness, accountability, and serving the public interest.

Looking ahead, the organization said it will continue investing in journalism, technology, editorial excellence, and a growing network of contributors as it works toward building one of Africa's most trusted digital newsrooms.

About Wire24: Wire24 is an independent digital news organization published by Lightway Media Ltd. The publication delivers reporting, analysis, investigations, and explanatory journalism covering Nigeria, Africa, and the wider world. Guided by the principles of accuracy, independence, fairness, context, and accountability, Wire24 is committed to producing journalism that informs, explains, and serves the public interest.$$,
            'Company',
            TRUE,
            '2026-07-05T09:00:00Z'
        )
        ON CONFLICT ("slug") DO NOTHING;
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DELETE FROM "press_releases" WHERE "slug" = 'prime-times-daily-rebrands-as-wire24';
    """
