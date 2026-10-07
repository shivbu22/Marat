"""Basic unit tests that do not require an LLM."""

from src.graph.state import ResearchState
from src.graph.workflow import build_research_graph


def test_graph_compiles():
    graph = build_research_graph()
    assert graph is not None


def test_state_keys():
    # Ensure TypedDict has expected keys
    keys = ResearchState.__annotations__.keys()
    assert "topic" in keys
    assert "sub_questions" in keys
    assert "findings" in keys
    assert "final_report" in keys
    assert "status" in keys
