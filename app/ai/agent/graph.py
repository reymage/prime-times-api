"""
LangGraph StateGraph for the PTD newsroom agent.

Two compiled graphs:
  suggest_graph  — desk → researcher → precedent_analyst → qc_editor (one-shot, <4s target)
  generate_graph — full graph: research loop + parallel analysis + rewrite loop
"""
import logging
from typing import Literal

from langgraph.graph import END, StateGraph

from app.ai.agent.nodes import (
    data_analyst_node,
    desk_editor_node,
    editor_in_chief_node,
    precedent_analyst_node,
    qc_editor_node,
    reporter_node,
    researcher_node,
    sub_editor_node,
)
from app.ai.agent.state import AgentState

logger = logging.getLogger(__name__)

# ── Routing functions (must be synchronous) ────────────────────────────────────

def _route_after_qc(
    state: AgentState,
) -> Literal["reporter", "desk_editor", "__end__"]:
    """
    After QC:
    - sufficient AND confidence>=70  → reporter
    - attempts >= 3                  → END (insufficient_research)
    - else                           → desk_editor (retry with gaps)
    """
    if state.get("sufficient") and state.get("confidence", 0) >= 70:
        return "reporter"
    if state.get("attempts", 0) >= 3:
        return END  # type: ignore[return-value]
    return "desk_editor"


def _route_after_chief(
    state: AgentState,
) -> Literal["reporter", "__end__"]:
    """
    After editor-in-chief:
    - score >= 85     → END (approved for human review)
    - rewrites >= 2   → END (forced with warning)
    - else            → reporter (rewrite)
    """
    if state.get("score", 0) >= 85:
        return END  # type: ignore[return-value]
    if state.get("rewrites", 0) >= 2:
        return END  # type: ignore[return-value]
    return "reporter"


# ── Terminal-state injectors ───────────────────────────────────────────────────

async def _insufficient_research_terminal(state: AgentState) -> dict:
    """Reached when research loops exhausted without sufficient material."""
    return {
        "error": "insufficient_research",
        "warnings": (state.get("warnings") or [])
        + [
            f"Research exhausted after {state.get('attempts', 0)} attempts. "
            "Story requires more source material."
        ],
    }


async def _forced_end_terminal(state: AgentState) -> dict:
    """Reached when rewrite limit hit without reaching score threshold."""
    return {
        "warnings": (state.get("warnings") or [])
        + [
            f"Draft did not reach publish threshold (score={state.get('score', 0)}) "
            "after maximum rewrites. Human editor review required."
        ],
    }


# ── Routing with terminal injection ───────────────────────────────────────────

def _route_after_qc_with_terminal(
    state: AgentState,
) -> Literal["reporter", "desk_editor", "insufficient_research_terminal"]:
    raw = _route_after_qc(state)
    if raw == END:
        return "insufficient_research_terminal"
    return raw  # type: ignore[return-value]


def _route_after_chief_full(
    state: AgentState,
) -> Literal["reporter", "forced_end_terminal", "__end__"]:
    if state.get("score", 0) >= 85:
        return END  # type: ignore[return-value]
    if state.get("rewrites", 0) >= 2:
        return "forced_end_terminal"
    return "reporter"


# ── Suggest graph (4 nodes, one-shot) ────────────────────────────────────────

def build_suggest_graph():
    wf = StateGraph(AgentState)

    wf.add_node("desk_editor", desk_editor_node)
    wf.add_node("researcher", researcher_node)
    wf.add_node("precedent_analyst", precedent_analyst_node)
    wf.add_node("qc_editor", qc_editor_node)

    wf.set_entry_point("desk_editor")
    wf.add_edge("desk_editor", "researcher")
    wf.add_edge("researcher", "precedent_analyst")
    wf.add_edge("precedent_analyst", "qc_editor")
    wf.add_edge("qc_editor", END)

    return wf.compile()


# ── Generate graph (full graph with parallel analysis + loops) ────────────────

def build_generate_graph():
    wf = StateGraph(AgentState)

    wf.add_node("desk_editor", desk_editor_node)
    wf.add_node("researcher", researcher_node)
    wf.add_node("data_analyst", data_analyst_node)
    wf.add_node("precedent_analyst", precedent_analyst_node)
    wf.add_node("qc_editor", qc_editor_node)
    wf.add_node("reporter", reporter_node)
    wf.add_node("sub_editor", sub_editor_node)
    wf.add_node("editor_in_chief", editor_in_chief_node)
    wf.add_node("insufficient_research_terminal", _insufficient_research_terminal)
    wf.add_node("forced_end_terminal", _forced_end_terminal)

    wf.set_entry_point("desk_editor")

    # Research pipeline — fan-out to parallel analysis, fan-in to qc_editor
    wf.add_edge("desk_editor", "researcher")
    wf.add_edge("researcher", "data_analyst")
    wf.add_edge("researcher", "precedent_analyst")
    wf.add_edge("data_analyst", "qc_editor")
    wf.add_edge("precedent_analyst", "qc_editor")

    # QC decision: retry or proceed or abort
    wf.add_conditional_edges(
        "qc_editor",
        _route_after_qc_with_terminal,
        {
            "reporter": "reporter",
            "desk_editor": "desk_editor",
            "insufficient_research_terminal": "insufficient_research_terminal",
        },
    )
    wf.add_edge("insufficient_research_terminal", END)

    # Draft pipeline
    wf.add_edge("reporter", "sub_editor")
    wf.add_edge("sub_editor", "editor_in_chief")

    # EIC decision: approve or rewrite or force-end
    wf.add_conditional_edges(
        "editor_in_chief",
        _route_after_chief_full,
        {
            "reporter": "reporter",
            "forced_end_terminal": "forced_end_terminal",
            END: END,
        },
    )
    wf.add_edge("forced_end_terminal", END)

    return wf.compile()


# ── Singletons (compiled once at import time) ─────────────────────────────────

suggest_graph = build_suggest_graph()
generate_graph = build_generate_graph()
