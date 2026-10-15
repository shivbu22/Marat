"""LangGraph workflow definition for the MARAT multi-agent intelligence platform.

Features:
- Cyclic state machine with autonomous revision loop
- Dual routing: Literature/Topic Research and Reverse Engineering targets
- Fact-checking verification with source ground-truth
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from ..agents.nodes import (
    fact_checker_node,
    planner_node,
    researcher_node,
    reviewer_node,
    writer_node,
)
from ..reverse_engineer.agent import reverse_engineer_node
from .state import ResearchState


def _route_after_planner(state: ResearchState) -> str:
    """Route to Reverse Engineer agent if a target artifact or RE mode is active."""
    target = (state.get("target_path") or "").strip()
    focus = (state.get("focus_mode") or "").strip()
    if target or focus == "reverse_engineer":
        return "reverse_engineer"
    return "researcher"


def _route_after_re(state: ResearchState) -> str:
    """After reverse engineering, route to fact checker, or researcher if topic requires web corroboration."""
    topic = state.get("topic") or ""
    target = state.get("target_path") or ""
    # If the user also wants broader comparative research
    if topic and topic != target and len(topic) > 10:
        return "researcher"
    return "fact_checker"


def _route_after_review(state: ResearchState) -> str:
    status = state.get("status", "")
    if status == "done":
        return "end"
    if status == "writing":
        return "writer"
    return "end"


def build_research_graph():
    """Compile the full multi-agent research and reverse engineering graph."""
    g = StateGraph(ResearchState)

    g.add_node("planner", planner_node)
    g.add_node("reverse_engineer", reverse_engineer_node)
    g.add_node("researcher", researcher_node)
    g.add_node("fact_checker", fact_checker_node)
    g.add_node("writer", writer_node)
    g.add_node("reviewer", reviewer_node)

    g.set_entry_point("planner")

    g.add_conditional_edges(
        "planner",
        _route_after_planner,
        {
            "reverse_engineer": "reverse_engineer",
            "researcher": "researcher",
        },
    )

    g.add_conditional_edges(
        "reverse_engineer",
        _route_after_re,
        {
            "researcher": "researcher",
            "fact_checker": "fact_checker",
        },
    )

    g.add_edge("researcher", "fact_checker")
    g.add_edge("fact_checker", "writer")
    g.add_edge("writer", "reviewer")

    g.add_conditional_edges(
        "reviewer",
        _route_after_review,
        {
            "writer": "writer",
            "end": END,
        },
    )

    return g.compile()


# Convenience singleton
_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_research_graph()
    return _graph
