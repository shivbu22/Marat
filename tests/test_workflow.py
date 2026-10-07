"""Unit tests for LangGraph workflow execution and routing."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from src.graph.workflow import _route_after_review, build_research_graph


def test_routing_after_review():
    state_done = {"status": "done"}
    assert _route_after_review(state_done) == "end"

    state_writing = {"status": "writing"}
    assert _route_after_review(state_writing) == "writer"

    state_other = {"status": "unknown"}
    assert _route_after_review(state_other) == "end"


@pytest.mark.asyncio
async def test_full_workflow_execution():
    graph = build_research_graph()

    mock_llm = MagicMock()
    # Provide canned responses for:
    # 1) planner, 2) researcher, 3) fact_checker, 4) writer, 5) reviewer
    mock_llm.ainvoke = AsyncMock(
        side_effect=[
            AIMessage(content='[{"id": "q1", "question": "What is Python?", "rationale": "Base"}]'),
            AIMessage(
                content='[{"claim": "Python is interpreted", "evidence": "docs", "sources": ["https://python.org"], "confidence": 0.9}]'
            ),
            AIMessage(
                content='[{"claim": "Python is interpreted", "status": "VERIFIED", "notes": "Standard", "supporting_sources": ["https://python.org"]}]'
            ),
            AIMessage(
                content="# Python Research\n\n## Executive Summary\nPython is a versatile programming language."
            ),
            AIMessage(content='{"approved": true, "score": 9, "feedback": "Good"}'),
        ]
    )

    initial = {
        "topic": "Python programming",
        "focus_mode": "broad",
        "sub_questions": [],
        "findings": [],
        "raw_search_notes": [],
        "fact_checks": [],
        "draft_report": "",
        "final_report": "",
        "review_count": 0,
        "review_feedback": "",
        "status": "planning",
        "error": "",
        "sources_used": [],
    }

    from src.tools.search import SearchResult

    mock_search = [
        SearchResult(
            title="Python docs",
            url="https://python.org",
            snippet="Python language docs",
            source="duckduckgo",
        )
    ]
    with (
        patch("src.agents.nodes.get_llm", return_value=mock_llm),
        patch("src.agents.nodes.web_search_async", new_callable=AsyncMock) as mock_search_fn,
        patch("src.agents.nodes.get_rag") as mock_rag,
    ):
        mock_search_fn.return_value = mock_search
        mock_rag.return_value.search.return_value = []
        mock_rag.return_value.add_texts.return_value = 1

        result = await graph.ainvoke(initial)
        assert result["status"] == "done"
        assert "Python Research" in result["final_report"]
        assert len(result["findings"]) >= 1
