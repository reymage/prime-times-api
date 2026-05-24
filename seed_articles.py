"""
Seed script — creates sample articles and nav menu items.

Usage (from the api/ directory):
    python seed_articles.py

Requires a valid .env file with DATABASE_URL and SECRET_KEY.
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))

from tortoise import Tortoise
from app.database import TORTOISE_ORM
from app.articles.models import Article
from app.nav.models import NavMenu, NavArea, NavItemType


def ago(days: int = 0, hours: int = 0) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days, hours=hours)


SEED_ARTICLES = [
    # --- POLITICS ---
    {
        "slug": "senate-passes-infrastructure-bill-2025",
        "title": "Senate Passes Sweeping Infrastructure Bill in Bipartisan Vote",
        "excerpt": "Senators approved a $1.2 trillion package covering roads, bridges, broadband, and clean energy in a rare show of unity.",
        "key_points": [
            "Bill passed 68–32 with significant cross-party support",
            "Funds allocated for 45,000 bridge repairs nationwide",
            "Rural broadband expansion reaches an estimated 30 million homes",
        ],
        "content": """<p>The United States Senate passed a landmark infrastructure package on Thursday, approving $1.2 trillion in spending that lawmakers called the most significant public-works investment in decades.</p>
<p>The vote was 68 to 32, with 19 Republican senators joining the Democratic majority — a margin wide enough to clear the 60-vote threshold needed to advance the bill.</p>
<p>The legislation directs roughly $550 billion in new spending toward roads, bridges, passenger rail, ports, airports, broadband internet, water systems, and clean-energy transmission lines. The remainder reauthorises existing transport programmes.</p>
<p>Transportation Secretary praised the bill as a "once-in-a-generation" investment that would create hundreds of thousands of jobs. Critics on the right argued the price tag was too high; critics on the left said it did not go far enough on climate.</p>""",
        "category": "Politics",
        "image_url": "https://images.unsplash.com/photo-1529107386315-e1a2ed48a620?w=800",
        "author": "Prime Times Daily",
        "source": "Prime Times Daily",
        "is_internal": True,
        "is_featured": True,
        "tags": ["politics", "infrastructure", "senate", "bipartisan"],
        "published_at": ago(hours=2),
    },
    {
        "slug": "election-commission-announces-new-voter-id-rules",
        "title": "Election Commission Announces Updated Voter ID Requirements Ahead of Midterms",
        "excerpt": "The national election body issued revised guidelines that expand acceptable forms of identification at polling stations.",
        "key_points": [
            "Student IDs and utility bills now accepted in 34 states",
            "Provisional ballot window extended to 10 days",
            "Online pre-registration portal launches next month",
        ],
        "content": """<p>The National Election Commission unveiled updated voter identification rules on Wednesday, broadening the list of accepted documents and extending provisional-ballot processing windows ahead of the midterm elections.</p>
<p>Under the new rules, student government-issued IDs, recent utility bills, and bank statements will be accepted alongside traditional photo identification in 34 states that had stricter previous requirements.</p>
<p>Advocacy groups welcomed the changes but said more still needed to be done to reduce barriers for low-income and minority voters. Several state attorneys general indicated they would review whether the federal guidelines conflict with state law.</p>""",
        "category": "Politics",
        "image_url": "https://images.unsplash.com/photo-1494172961521-33799ddd43a5?w=800",
        "author": "Prime Times Daily",
        "source": "Prime Times Daily",
        "is_internal": True,
        "is_featured": False,
        "tags": ["politics", "elections", "voter-id", "democracy"],
        "published_at": ago(days=1),
    },
    # --- BUSINESS ---
    {
        "slug": "fed-holds-interest-rates-june-2025",
        "title": "Federal Reserve Holds Interest Rates Steady, Signals Patience on Cuts",
        "excerpt": "The Fed left its benchmark rate unchanged for the third consecutive meeting, citing persistent services inflation and a still-tight labour market.",
        "key_points": [
            "Fed funds rate remains at 5.25–5.50 percent",
            "Core PCE inflation running at 2.8 percent, above 2 percent target",
            "Chair signals two possible cuts later in the year if data cooperate",
        ],
        "content": """<p>The Federal Reserve held its benchmark interest rate steady on Wednesday, keeping the federal funds rate in the 5.25 to 5.50 percent range for a third consecutive meeting as policymakers said they needed more evidence that inflation was durably returning to their 2 percent target.</p>
<p>In a press conference following the announcement, the Chair acknowledged that progress on inflation had been slower than hoped in early 2025 but expressed confidence that the disinflationary trend remained intact.</p>
<p>Markets had widely expected the pause. Futures traders are currently pricing in roughly two quarter-point cuts before the end of the year, likely beginning in September.</p>
<p>The decision was unanimous, reflecting broad agreement within the committee that patience was warranted given lingering price pressures in shelter and services.</p>""",
        "category": "Business",
        "image_url": "https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?w=800",
        "author": "Prime Times Daily",
        "source": "Prime Times Daily",
        "is_internal": True,
        "is_featured": True,
        "tags": ["business", "federal-reserve", "interest-rates", "inflation"],
        "published_at": ago(hours=5),
    },
    {
        "slug": "nvidia-ai-chip-demand-record-quarter",
        "title": "Nvidia Posts Record Quarter on Surging AI Chip Demand",
        "excerpt": "The chipmaker reported quarterly revenue of $26 billion, more than tripling year-on-year, as hyperscalers raced to build AI infrastructure.",
        "key_points": [
            "Revenue hit $26 billion, up 222 percent year-on-year",
            "Data-centre division alone contributed $22.6 billion",
            "Company guides next quarter above analyst consensus",
        ],
        "content": """<p>Nvidia on Wednesday reported quarterly revenue of $26 billion, far surpassing analyst forecasts and more than tripling the figure from the same period a year ago, driven by insatiable demand for its H100 and H200 graphics processing units used in AI training.</p>
<p>The data-centre division, which sells chips and networking gear to cloud providers and large enterprises, contributed $22.6 billion — virtually all of the company's revenue growth.</p>
<p>Chief Executive Jensen Huang told analysts that the company was supply-constrained, not demand-constrained, and that it expected shipments of its next-generation Blackwell architecture to ramp sharply in the second half of the year.</p>""",
        "category": "Business",
        "image_url": "https://images.unsplash.com/photo-1591696331111-ef9586a5b17a?w=800",
        "author": "Prime Times Daily",
        "source": "Prime Times Daily",
        "is_internal": True,
        "is_featured": False,
        "tags": ["business", "nvidia", "ai", "chips", "earnings"],
        "published_at": ago(days=1, hours=4),
    },
    # --- TECHNOLOGY ---
    {
        "slug": "openai-releases-gpt5-public-preview",
        "title": "OpenAI Releases GPT-5 in Public Preview With Multimodal Reasoning",
        "excerpt": "The new model can analyse images, audio, and documents simultaneously and demonstrates significantly improved logical reasoning over its predecessor.",
        "key_points": [
            "GPT-5 scores in the 99th percentile on standardised reasoning benchmarks",
            "Native audio input and output without a separate speech model",
            "Available to ChatGPT Plus and API users from today",
        ],
        "content": """<p>OpenAI on Tuesday began rolling out GPT-5 to ChatGPT Plus subscribers and API customers, describing the model as its most capable to date and a significant step toward what the company calls "general intelligence."</p>
<p>The model accepts text, images, audio, and documents as input and can reason across modalities without switching between specialised models. In internal benchmarks, it outperforms GPT-4o on mathematics, coding, and multi-step logical reasoning by margins the company described as "substantial."</p>
<p>Independent researchers who received early access said the improvements in long-context reasoning were the most striking, with the model maintaining coherence across documents exceeding 100,000 tokens.</p>
<p>Pricing for API access starts at $10 per million input tokens, roughly double the cost of GPT-4o, reflecting the model's higher compute requirements.</p>""",
        "category": "Technology",
        "image_url": "https://images.unsplash.com/photo-1677442135703-1787eea5ce01?w=800",
        "author": "Prime Times Daily",
        "source": "Prime Times Daily",
        "is_internal": True,
        "is_featured": True,
        "tags": ["technology", "ai", "openai", "gpt-5", "llm"],
        "published_at": ago(hours=8),
    },
    {
        "slug": "apple-vision-pro-developer-adoption",
        "title": "Apple Vision Pro Developer Adoption Accelerates Six Months After Launch",
        "excerpt": "More than 1,500 native visionOS apps are now available, with productivity and medical applications leading the surge.",
        "key_points": [
            "App Store for visionOS crossed 1,500 titles",
            "Medical and surgical training apps seeing fastest growth",
            "Apple confirms Vision Pro 2 hardware in development",
        ],
        "content": """<p>Six months after its launch, Apple's Vision Pro spatial computing headset has attracted more than 1,500 native visionOS applications, a pace that outstripped early iPhone App Store growth, according to data released by the company on Monday.</p>
<p>Productivity suites, medical training simulators, and architectural visualisation tools account for the largest share of new releases, reflecting corporate and professional rather than consumer use cases.</p>
<p>Several hospital networks have begun piloting visionOS surgical-planning apps, and at least two medical device companies have received regulatory clearance for Vision Pro-based diagnostic tools.</p>
<p>Apple's senior vice-president of software engineering confirmed in an interview that a second-generation headset was under development, though he declined to provide a timeline.</p>""",
        "category": "Technology",
        "image_url": "https://images.unsplash.com/photo-1696446702183-cbd25fd591fa?w=800",
        "author": "Prime Times Daily",
        "source": "Prime Times Daily",
        "is_internal": True,
        "is_featured": False,
        "tags": ["technology", "apple", "vision-pro", "visionos", "ar"],
        "published_at": ago(days=2),
    },
    # --- WORLD ---
    {
        "slug": "g7-summit-climate-pledges-2025",
        "title": "G7 Leaders Agree to Phase Out Coal Power by 2035 at Annual Summit",
        "excerpt": "The world's seven largest economies committed to ending unabated coal-fired electricity generation within a decade, a deadline activists called meaningful but insufficient.",
        "key_points": [
            "Coal phase-out deadline set for 2035 across all G7 nations",
            "Joint fund of $50 billion pledged to support developing-nation transitions",
            "Natural gas remains exempt from the phase-out commitment",
        ],
        "content": """<p>Leaders of the Group of Seven nations agreed on Friday to phase out coal-fired power generation by 2035, the most concrete deadline the bloc has set on fossil-fuel elimination and a significant tightening of previous commitments.</p>
<p>The agreement, reached after two days of negotiations at the summit in southern Italy, also pledges a joint $50 billion fund to help lower-income countries build clean-energy capacity as an alternative to coal.</p>
<p>Environmental groups welcomed the coal commitment but criticised the leaders for exempting natural gas from the agreement and for failing to set binding oil-demand reduction targets.</p>
<p>The host nation's prime minister called the outcome "a historic step" while acknowledging that implementation would require significant domestic policy changes in several member states.</p>""",
        "category": "World",
        "image_url": "https://images.unsplash.com/photo-1532996122724-e3c354a0b15b?w=800",
        "author": "Prime Times Daily",
        "source": "Prime Times Daily",
        "is_internal": True,
        "is_featured": False,
        "tags": ["world", "g7", "climate", "coal", "energy"],
        "published_at": ago(days=3),
    },
    {
        "slug": "ukraine-nato-membership-talks-progress",
        "title": "NATO Members Signal Openness to Ukraine Membership Roadmap at Brussels Talks",
        "excerpt": "Alliance foreign ministers gathered in Brussels discussed a formal accession pathway for Ukraine, with several key holdouts softening their positions.",
        "key_points": [
            "Germany and Hungary both dropped outright opposition to a roadmap",
            "Formal accession timeline would begin after active conflict ends",
            "Military aid package worth €8 billion announced alongside talks",
        ],
        "content": """<p>Foreign ministers from NATO member states met in Brussels on Thursday and signalled a significant shift toward offering Ukraine a formal membership roadmap, with two nations that had previously opposed the move dropping their objections.</p>
<p>Germany and Hungary both indicated they would no longer block a communiqué that sets out a structured path to membership, though both governments said formal accession could only proceed after active hostilities cease.</p>
<p>The alliance also announced a new military assistance package worth €8 billion, including air-defence batteries, artillery ammunition, and armoured vehicles, to be drawn from member nations' stockpiles and new production contracts.</p>""",
        "category": "World",
        "image_url": "https://images.unsplash.com/photo-1555848962-6e79363ec58f?w=800",
        "author": "Prime Times Daily",
        "source": "Prime Times Daily",
        "is_internal": True,
        "is_featured": False,
        "tags": ["world", "nato", "ukraine", "geopolitics"],
        "published_at": ago(days=2, hours=6),
    },
    # --- SPORT ---
    {
        "slug": "champions-league-final-preview-2025",
        "title": "Champions League Final Preview: Two Titans Clash in Istanbul",
        "excerpt": "Saturday's final promises a tactical battle between Europe's form sides, with both squads at full fitness and carrying contrasting philosophies into the showpiece.",
        "key_points": [
            "Kick-off at 20:00 local time at Atatürk Olympic Stadium",
            "Both clubs unbeaten in the knockout rounds",
            "Combined market value of starting XIs exceeds €1.5 billion",
        ],
        "content": """<p>Europe's premier club competition reaches its climax on Saturday when two of the continent's most decorated sides meet at the Atatürk Olympic Stadium in Istanbul, a venue already etched into football folklore.</p>
<p>The two finalists arrived at the showpiece unbeaten through the knockout stages, each conceding just three goals across six matches. The contrast in style is stark: one side built on relentless pressing and width, the other on deep defensive structure and devastating counter-attacking transitions.</p>
<p>Both squads reported full fitness in their final pre-match training sessions, removing any injury-related uncertainty from the selection equation ahead of what analysts are calling the most evenly matched final in a decade.</p>""",
        "category": "Sport",
        "image_url": "https://images.unsplash.com/photo-1553778263-73a83bab9b0c?w=800",
        "author": "Prime Times Daily",
        "source": "Prime Times Daily",
        "is_internal": True,
        "is_featured": False,
        "tags": ["sport", "football", "champions-league", "ucl"],
        "published_at": ago(hours=12),
    },
    # --- ENTERTAINMENT ---
    {
        "slug": "cannes-palme-dor-winner-2025",
        "title": "Cannes Palme d'Or Goes to Debut Feature From Nigerian Director",
        "excerpt": "The jury unanimously awarded the festival's top prize to a first-time director whose film about migration and identity drew a 12-minute standing ovation.",
        "key_points": [
            "First Nigerian director to win the Palme d'Or",
            "Film shot over four years with a non-professional cast",
            "International distribution deal signed within hours of the announcement",
        ],
        "content": """<p>The Cannes Film Festival awarded its highest honour, the Palme d'Or, to a debut feature from a Nigerian director on Saturday night, marking a historic first for African cinema at the world's most prestigious film competition.</p>
<p>The film, which follows a young woman's journey from Lagos across the Mediterranean to Northern Europe, drew a 12-minute standing ovation at its premiere and was widely tipped for the top prize by critics throughout the two-week festival.</p>
<p>The jury president called it "a film of devastating humanity and formal rigour — a debut that announces a major new voice in world cinema."</p>
<p>A major international distributor confirmed within hours of the announcement that it had acquired worldwide rights, with a theatrical release planned for the autumn.</p>""",
        "category": "Entertainment",
        "image_url": "https://images.unsplash.com/photo-1489599849927-2ee91cede3ba?w=800",
        "author": "Prime Times Daily",
        "source": "Prime Times Daily",
        "is_internal": True,
        "is_featured": True,
        "tags": ["entertainment", "cannes", "film", "africa", "cinema"],
        "published_at": ago(days=4),
    },
]

SEED_NAV = [
    # Main nav
    {"label": "Home",          "slug": "home",          "href": "/",               "area": NavArea.main,    "item_type": NavItemType.primary,  "position": 0},
    {"label": "Politics",      "slug": "politics",      "href": "/category/politics",    "area": NavArea.main, "item_type": NavItemType.category, "position": 1},
    {"label": "Business",      "slug": "business",      "href": "/category/business",    "area": NavArea.main, "item_type": NavItemType.category, "position": 2},
    {"label": "Technology",    "slug": "technology",    "href": "/category/technology",  "area": NavArea.main, "item_type": NavItemType.category, "position": 3},
    {"label": "World",         "slug": "world",         "href": "/category/world",       "area": NavArea.main, "item_type": NavItemType.category, "position": 4},
    {"label": "Sport",         "slug": "sport",         "href": "/category/sport",       "area": NavArea.main, "item_type": NavItemType.category, "position": 5},
    {"label": "Entertainment", "slug": "entertainment", "href": "/category/entertainment","area": NavArea.main, "item_type": NavItemType.category, "position": 6},
    # Console nav
    {"label": "Dashboard",     "slug": "console-dashboard", "href": "/console",           "area": NavArea.console, "item_type": NavItemType.primary, "position": 0},
    {"label": "Articles",      "slug": "console-articles",  "href": "/console/articles",  "area": NavArea.console, "item_type": NavItemType.primary, "position": 1},
    {"label": "Editors",       "slug": "console-editors",   "href": "/console/editors",   "area": NavArea.console, "item_type": NavItemType.primary, "position": 2},
]


async def seed_nav() -> None:
    for item in SEED_NAV:
        existing = await NavMenu.filter(slug=item["slug"]).first()
        if existing:
            print(f"[SKIP NAV]  {item['slug']} already exists")
        else:
            await NavMenu.create(**item)
            print(f"[NAV]       created {item['slug']}")


async def seed_articles() -> None:
    for data in SEED_ARTICLES:
        existing = await Article.filter(slug=data["slug"]).first()
        if existing:
            print(f"[SKIP ART]  {data['slug']} already exists")
        else:
            await Article.create(**data)
            print(f"[ARTICLE]   created '{data['title'][:60]}'")


async def main() -> None:
    await Tortoise.init(config=TORTOISE_ORM)
    await seed_nav()
    await seed_articles()
    await Tortoise.close_connections()
    print("\nArticle + nav seeding complete.")


if __name__ == "__main__":
    asyncio.run(main())
