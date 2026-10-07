"""LangGraph workflow definition for the multi-agent research assistant."""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from ..agents.nodes import (
    fact_checker_node,
    planner_node,
    researcher_node,
    reviewer_node,
    writer_node,
)
from .state import ResearchState


def _route_after_review(state: ResearchState) -> str:
    status = state.get("status", "")
    if status == "done":
        return "end"
    if status == "writing":
        return "writer"
    return "end"


def build_research_graph():
    """Compile the full multi-agent research graph."""
    g = StateGraph(ResearchState)

    g.add_node("planner", planner_node)
    g.add_node("researcher", researcher_node)
    g.add_node("fact_checker", fact_checker_node)
    g.add_node("writer", writer_node)
    g.add_node("reviewer", reviewer_node)

    g.set_entry_point("planner")

    g.add_edge("planner", "researcher")
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
