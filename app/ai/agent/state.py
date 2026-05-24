import operator
from typing import Annotated, Optional
from typing_extensions import TypedDict


class AgentState(TypedDict):
    # ── Input ────────────────────────────────────────────────────────────────
    title: str
    body: str
    highlighted_text: Optional[str]

    # ── Classification ───────────────────────────────────────────────────────
    story_type: str

    # ── Research loop ────────────────────────────────────────────────────────
    queries: list[str]
    notes: list[str]
    sources: list[dict]
    attempts: int                  # incremented each time desk_editor runs
    gaps: list[str]
    data_gaps: list[str]
    confidence: int
    sufficient: bool

    # ── Precedent layer ──────────────────────────────────────────────────────
    key_entities: list[str]        # extracted by precedent_analyst (first run only)
    precedents: list[dict]         # [{headline, date, outcome, summary, url}]

    # ── Draft loop ───────────────────────────────────────────────────────────
    angles: list[str]
    draft: str
    score: int
    rewrites: int                  # incremented each time reporter runs

    # ── Telemetry — Annotated with operator.add so parallel branches sum correctly
    total_input_tokens: Annotated[int, operator.add]
    total_output_tokens: Annotated[int, operator.add]
    tavily_searches: Annotated[int, operator.add]
    cache_hits: Annotated[int, operator.add]

    # ── Terminal state ───────────────────────────────────────────────────────
    warnings: list[str]
    error: Optional[str]


def initial_state(
    title: str,
    body: str,
    highlighted_text: Optional[str] = None,
) -> AgentState:
    return AgentState(
        title=title,
        body=body,
        highlighted_text=highlighted_text,
        story_type="general",
        queries=[],
        notes=[],
        sources=[],
        attempts=0,
        gaps=[],
        data_gaps=[],
        confidence=0,
        sufficient=False,
        key_entities=[],
        precedents=[],
        angles=[],
        draft="",
        score=0,
        rewrites=0,
        total_input_tokens=0,
        total_output_tokens=0,
        tavily_searches=0,
        cache_hits=0,
        warnings=[],
        error=None,
    )
