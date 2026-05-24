"""
All newsroom role nodes for the PTD AI agent.

Node temperatures:
  desk_editor       0.1
  researcher        N/A (no LLM)
  precedent_analyst 0.0
  data_analyst      0.0
  qc_editor         0.0
  reporter          0.2
  sub_editor        0.0
  editor_in_chief   0.1

Telemetry fields (total_input_tokens, total_output_tokens, tavily_searches, cache_hits)
use operator.add reducers in AgentState — nodes return DELTA values, not cumulative sums.
"""
import json
import logging
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.ai.cache import (
    _precedent_cache_key,
    cache_get,
    cache_set,
    cached_llm_invoke,
    cached_tavily_search,
)
from app.ai.llm import get_llm
from app.ai.prompts import get_newsroom_context, get_prompt
from app.ai.agent.state import AgentState

logger = logging.getLogger(__name__)

_FINANCIAL_STORY_TYPES = {"budget", "corporate", "business", "economy"}

_VALID_PRECEDENT_OUTCOMES = {
    "succeeded", "failed", "ongoing", "abandoned", "court_blocked", "reversed"
}


# ── JSON parsing helper ────────────────────────────────────────────────────────

def _parse_json(text: str, fallback: dict) -> dict:
    """Extract the first JSON object from an LLM response."""
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    logger.warning("JSON parse failed; using fallback. Raw: %.200s", text)
    return fallback


def _token_delta(response: Any) -> tuple[int, int]:
    """Extract (input_tokens, output_tokens) from an LLM response if available."""
    meta = getattr(response, "usage_metadata", None)
    if meta:
        return meta.get("input_tokens", 0), meta.get("output_tokens", 0)
    return 0, 0


def _build_messages(system: str, user: str) -> list:
    return [
        SystemMessage(content=system),
        HumanMessage(content=user),
    ]


def _format_precedents(precedents: list[dict]) -> str:
    if not precedents:
        return "None found."
    lines = []
    for p in precedents:
        lines.append(
            f"- {p.get('headline', '')} ({p.get('date', '')}) "
            f"— outcome: {p.get('outcome', '')}. {p.get('summary', '')}"
        )
    return "\n".join(lines)


# ── Node 1: Desk Editor ────────────────────────────────────────────────────────

async def desk_editor_node(state: AgentState) -> dict:
    """Classify story_type, generate 5 research queries + 3 angles."""
    llm = get_llm(temperature=0.1)
    p = get_prompt("desk_editor", state.get("story_type", "general"))

    user = p["user"].format(
        title=state["title"],
        body=state["body"],
        attempts=state.get("attempts", 0),
        gaps="\n".join(state.get("gaps", [])) or "None",
    )

    messages = _build_messages(p["system"], user)
    response, hit = await cached_llm_invoke(llm, messages, temperature=0.1)
    in_t, out_t = _token_delta(response)

    result = _parse_json(
        response.content,
        fallback={
            "story_type": "general",
            "queries": [state["title"]],
            "angles": [],
            "must_have_facts": "",
        },
    )

    return {
        "story_type": result.get("story_type", "general"),
        "queries": result.get("queries", [state["title"]])[:5],
        "angles": result.get("angles", []),
        "attempts": state.get("attempts", 0) + 1,
        "total_input_tokens": in_t,
        "total_output_tokens": out_t,
        "cache_hits": 1 if hit else 0,
    }


# ── Node 2: Researcher ─────────────────────────────────────────────────────────

async def researcher_node(state: AgentState) -> dict:
    """Run Tavily search for each query. Seeds notes with original body on first pass."""
    queries = state.get("queries", [])[:5]
    # On the first pass, treat the original body as a primary-source note so QC
    # can verify facts the reporter already established (court records, EFCC filings, etc.)
    existing_notes = state.get("notes") or []
    new_notes: list[str] = []
    if not existing_notes and state.get("body", "").strip():
        new_notes.append(f"[Original report — primary source]\n{state['body']}")
    new_sources: list[dict] = []
    search_count = 0
    cache_hits = 0

    for query in queries:
        try:
            result, hit = await cached_tavily_search(query, search_depth="advanced")
        except Exception as exc:
            logger.warning("Tavily search failed for query '%s': %s", query, exc)
            continue

        search_count += 1
        if hit:
            cache_hits += 1

        answer = result.get("answer") or ""
        if answer:
            new_notes.append(f"[{query}]\n{answer}")

        for r in result.get("results", [])[:3]:
            new_sources.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", "")[:500],
                "score": r.get("score", 0),
            })

    return {
        "notes": (state.get("notes") or []) + new_notes,
        "sources": (state.get("sources") or []) + new_sources,
        "tavily_searches": search_count,
        "cache_hits": cache_hits,
    }


# ── Node 3: Precedent Analyst ──────────────────────────────────────────────────

async def precedent_analyst_node(state: AgentState) -> dict:
    """Extract key entities and find historical precedents. Runs once per story."""
    # Short-circuit on research loops — precedents are stable once found
    if state.get("key_entities"):
        return {}

    in_tokens = 0
    out_tokens = 0
    search_count = 0
    hits = 0

    llm = get_llm(temperature=0.0)
    p = get_prompt("precedent_analyst", state.get("story_type", "general"))

    # Phase 1: Extract key entities
    user_entity = p["entity_user"].format(
        title=state["title"],
        body=state["body"],
    )
    msgs = _build_messages(p["entity_system"], user_entity)
    response, hit = await cached_llm_invoke(llm, msgs, temperature=0.0)
    in_t, out_t = _token_delta(response)
    in_tokens += in_t
    out_tokens += out_t
    hits += 1 if hit else 0

    entity_result = _parse_json(response.content, fallback={"key_entities": [state["title"]]})
    key_entities: list[str] = entity_result.get("key_entities", [state["title"]])[:8]
    if not key_entities:
        key_entities = [state["title"]]

    # Phase 2: Check precedent cache (24h TTL)
    cache_key = _precedent_cache_key(key_entities, state.get("story_type", "general"))
    cached = await cache_get(cache_key)
    if cached is not None:
        return {
            "precedents": cached,
            "key_entities": key_entities,
            "total_input_tokens": in_tokens,
            "total_output_tokens": out_tokens,
            "cache_hits": hits + 1,  # +1 for precedent cache hit
        }

    # Phase 3: Search for precedents — internal archive first, then general
    entities_str = " ".join(key_entities[:5])
    search_queries = [
        f"site:primetimesdaily.ng {entities_str}",
        f"{entities_str} Nigeria 2019..2024",
    ]
    raw_results: list[str] = []
    for query in search_queries:
        try:
            result, hit = await cached_tavily_search(query, search_depth="basic")
            search_count += 1
            if hit:
                hits += 1
            answer = result.get("answer") or ""
            if answer:
                raw_results.append(f"[{query}]\n{answer}")
            for r in result.get("results", [])[:3]:
                raw_results.append(
                    f"Title: {r.get('title', '')}\nURL: {r.get('url', '')}\n"
                    f"Content: {r.get('content', '')[:300]}"
                )
        except Exception as exc:
            logger.warning("Precedent search failed for '%s': %s", query, exc)

    if not raw_results:
        await cache_set(cache_key, [], ttl=86400)
        return {
            "precedents": [],
            "key_entities": key_entities,
            "total_input_tokens": in_tokens,
            "total_output_tokens": out_tokens,
            "tavily_searches": search_count,
            "cache_hits": hits,
        }

    # Phase 4: Classify outcomes from search results
    user_classify = p["classify_user"].format(
        entities=", ".join(key_entities),
        results="\n\n".join(raw_results[:6]),
    )
    msgs = _build_messages(p["classify_system"], user_classify)
    response, hit = await cached_llm_invoke(llm, msgs, temperature=0.0)
    in_t, out_t = _token_delta(response)
    in_tokens += in_t
    out_tokens += out_t
    hits += 1 if hit else 0

    classify_result = _parse_json(response.content, fallback={"precedents": []})
    raw_precedents = classify_result.get("precedents", [])[:3]

    cleaned: list[dict] = []
    for prec in raw_precedents:
        if isinstance(prec, dict):
            outcome = prec.get("outcome", "ongoing")
            cleaned.append({
                "headline": str(prec.get("headline", ""))[:200],
                "date": str(prec.get("date", ""))[:20],
                "outcome": outcome if outcome in _VALID_PRECEDENT_OUTCOMES else "ongoing",
                "summary": str(prec.get("summary", ""))[:300],
                "url": str(prec.get("url", ""))[:500],
            })

    await cache_set(cache_key, cleaned, ttl=86400)

    return {
        "precedents": cleaned,
        "key_entities": key_entities,
        "total_input_tokens": in_tokens,
        "total_output_tokens": out_tokens,
        "tavily_searches": search_count,
        "cache_hits": hits,
    }


# ── Node 4: Data Analyst ───────────────────────────────────────────────────────

async def data_analyst_node(state: AgentState) -> dict:
    """Verify official Nigerian data sources for financial stories."""
    if state.get("story_type", "general") not in _FINANCIAL_STORY_TYPES:
        return {}

    llm = get_llm(temperature=0.0)
    p = get_prompt("data_analyst", state.get("story_type", "general"))

    sources_summary = "\n".join(
        f"- {s.get('title', '')} | {s.get('url', '')}"
        for s in (state.get("sources") or [])[:15]
    )
    notes_text = "\n\n".join((state.get("notes") or [])[:10])

    user = p["user"].format(
        story_type=state.get("story_type", ""),
        notes=notes_text or "No notes yet.",
        sources=sources_summary or "No sources yet.",
    )

    messages = _build_messages(p["system"], user)
    response, hit = await cached_llm_invoke(llm, messages, temperature=0.0)
    in_t, out_t = _token_delta(response)

    result = _parse_json(
        response.content,
        fallback={"data_verified": False, "official_sources_found": [], "data_gaps": []},
    )

    return {
        "data_gaps": result.get("data_gaps", []),
        "total_input_tokens": in_t,
        "total_output_tokens": out_t,
        "cache_hits": 1 if hit else 0,
    }


# ── Node 5: QC Editor ─────────────────────────────────────────────────────────

async def qc_editor_node(state: AgentState) -> dict:
    """Assess research completeness. Outputs sufficient, confidence, gaps."""
    llm = get_llm(temperature=0.0)
    p = get_prompt("qc_editor", state.get("story_type", "general"))

    sources_summary = "\n".join(
        f"- [{s.get('title', '')}]({s.get('url', '')})"
        for s in (state.get("sources") or [])[:15]
    )
    notes_text = "\n\n".join((state.get("notes") or [])[:15])
    data_gaps = state.get("data_gaps") or []
    if data_gaps:
        notes_text += "\n\nDATA ANALYST GAPS:\n" + "\n".join(f"- {g}" for g in data_gaps)

    precedents_text = _format_precedents(state.get("precedents") or [])

    user = p["user"].format(
        story_type=state.get("story_type", "general"),
        title=state["title"],
        notes=notes_text or "No research yet.",
        sources=sources_summary or "No sources yet.",
        precedents=precedents_text,
        attempts=state.get("attempts", 0),
    )

    messages = _build_messages(p["system"], user)
    response, hit = await cached_llm_invoke(llm, messages, temperature=0.0)
    in_t, out_t = _token_delta(response)

    result = _parse_json(
        response.content,
        fallback={"sufficient": False, "confidence": 0, "gaps": ["No research completed"]},
    )

    return {
        "sufficient": bool(result.get("sufficient", False)),
        "confidence": int(result.get("confidence", 0)),
        "gaps": result.get("gaps", []),
        "total_input_tokens": in_t,
        "total_output_tokens": out_t,
        "cache_hits": 1 if hit else 0,
    }


# ── Node 6: Reporter ──────────────────────────────────────────────────────────

async def reporter_node(state: AgentState) -> dict:
    """Write a 400-600 word adversarial PTD draft."""
    llm = get_llm(temperature=0.2)
    p = get_prompt("reporter", state.get("story_type", "general"))

    notes_text = "\n\n".join((state.get("notes") or [])[:20])
    precedents_text = _format_precedents(state.get("precedents") or [])

    highlighted = state.get("highlighted_text")
    highlighted_section = (
        f"HIGHLIGHTED TEXT TO ENHANCE:\n{highlighted}\n\nSpecifically expand and improve this section."
        if highlighted
        else ""
    )

    user = p["user"].format(
        title=state["title"],
        story_type=state.get("story_type", "general"),
        notes=notes_text or "No research notes available.",
        precedents=precedents_text,
        highlighted_section=highlighted_section,
    )

    messages = _build_messages(p["system"], user)
    response, hit = await cached_llm_invoke(llm, messages, temperature=0.2)
    in_t, out_t = _token_delta(response)

    draft = response.content.strip()
    is_rewrite = bool(state.get("draft", "").strip())

    return {
        "draft": draft,
        "rewrites": state.get("rewrites", 0) + (1 if is_rewrite else 0),
        "total_input_tokens": in_t,
        "total_output_tokens": out_t,
        "cache_hits": 1 if hit else 0,
    }


# ── Node 7: Sub-Editor ────────────────────────────────────────────────────────

async def sub_editor_node(state: AgentState) -> dict:
    """Remove AI-isms and insert [FACT CHECK: unverified] markers."""
    llm = get_llm(temperature=0.0)
    p = get_prompt("sub_editor", state.get("story_type", "general"))

    notes_text = "\n\n".join((state.get("notes") or [])[:20])

    user = p["user"].format(
        notes=notes_text or "No research notes.",
        draft=state.get("draft", ""),
    )

    messages = _build_messages(p["system"], user)
    response, hit = await cached_llm_invoke(llm, messages, temperature=0.0)
    in_t, out_t = _token_delta(response)

    return {
        "draft": response.content.strip(),
        "total_input_tokens": in_t,
        "total_output_tokens": out_t,
        "cache_hits": 1 if hit else 0,
    }


# ── Node 8: Editor-in-Chief ───────────────────────────────────────────────────

async def editor_in_chief_node(state: AgentState) -> dict:
    """Score 0-100 and produce verdict."""
    llm = get_llm(temperature=0.1)
    p = get_prompt("editor_in_chief", state.get("story_type", "general"))

    user = p["user"].format(
        title=state["title"],
        story_type=state.get("story_type", "general"),
        draft=state.get("draft", ""),
    )

    messages = _build_messages(p["system"], user)
    response, hit = await cached_llm_invoke(llm, messages, temperature=0.1)
    in_t, out_t = _token_delta(response)

    result = _parse_json(
        response.content,
        fallback={"score": 0, "verdict": "NEEDS_WORK", "feedback": "Unable to score draft."},
    )

    score = int(result.get("score", 0))
    feedback = result.get("feedback", "")

    warnings = list(state.get("warnings") or [])
    if feedback:
        warnings.append(f"Editor feedback: {feedback}")

    return {
        "score": score,
        "warnings": warnings,
        "total_input_tokens": in_t,
        "total_output_tokens": out_t,
        "cache_hits": 1 if hit else 0,
    }
