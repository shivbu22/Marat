"""Unit tests for agent nodes and JSON parsing."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from src.agents.nodes import (
    _parse_json_block,
    fact_checker_node,
    planner_node,
    researcher_node,
    reviewer_node,
    writer_node,
)
from src.tools.search import SearchResult


def test_parse_json_block_fenced():
    raw = 'Here is the plan:\n```json\n[{"id": "q1", "question": "Test?"}]\n```\nDone.'
    parsed = _parse_json_block(raw)
    assert isinstance(parsed, list)
    assert parsed[0]["id"] == "q1"


def test_parse_json_block_raw_object():
    raw = 'Sure, here is the result: {"approved": true, "score": 9} Hope it helps!'
    parsed = _parse_json_block(raw)
    assert isinstance(parsed, dict)
    assert parsed["approved"] is True
    assert parsed["score"] == 9


def test_parse_json_block_invalid():
    assert _parse_json_block("No JSON at all here") is None
    assert _parse_json_block(None) is None


@pytest.mark.asyncio
async def test_planner_node_success():
    state = {"topic": "Quantum Computing", "focus_mode": "broad"}
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(
        return_value=AIMessage(
            content='[{"id": "q1", "question": "What is quantum computing?", "rationale": "Basics"}]'
        )
    )

    with patch("src.agents.nodes.get_llm", return_value=mock_llm):
        out = await planner_node(state)
        assert out["status"] == "researching"
        assert len(out["sub_questions"]) == 1
        assert out["sub_questions"][0]["id"] == "q1"


@pytest.mark.asyncio
async def test_planner_node_fallback():
    state = {"topic": "Autonomous AI", "focus_mode": "broad"}
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(side_effect=Exception("Connection error"))

    with patch("src.agents.nodes.get_llm", return_value=mock_llm):
        out = await planner_node(state)
        assert out["status"] == "researching"
        assert len(out["sub_questions"]) == 1
        assert out["sub_questions"][0]["id"] == "q1"
        assert out["sub_questions"][0]["question"] == "Autonomous AI"


@pytest.mark.asyncio
async def test_researcher_node():
    state = {
        "sub_questions": [{"id": "q1", "question": "What is WebAssembly?"}],
    }
    mock_search = [
        SearchResult(
            title="Wasm intro",
            url="https://wasm.org",
            snippet="WebAssembly is a binary instruction format for a stack-based virtual machine.",
            source="duckduckgo",
        )
    ]
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(
        return_value=AIMessage(
            content=json.dumps(
                [
                    {
                        "claim": "Wasm is a binary instruction format",
                        "evidence": "WebAssembly is a binary instruction format",
                        "sources": ["https://wasm.org"],
                        "confidence": 0.9,
                    }
                ]
            )
        )
    )

    with (
        patch("src.agents.nodes.web_search_async", new_callable=AsyncMock) as mock_search_fn,
        patch("src.agents.nodes.get_llm", return_value=mock_llm),
        patch("src.agents.nodes.get_rag") as mock_rag,
    ):
        mock_search_fn.return_value = mock_search
        mock_rag.return_value.search.return_value = []
        out = await researcher_node(state)
        assert out["status"] == "fact_checking"
        assert len(out["findings"]) == 1
        assert out["findings"][0]["claim"] == "Wasm is a binary instruction format"
        assert "https://wasm.org" in out["sources_used"]


@pytest.mark.asyncio
async def test_fact_checker_node():
    state = {
        "topic": "WebAssembly",
        "findings": [
            {
                "claim": "Wasm runs in browsers",
                "evidence": "Supported by modern browsers",
                "sources": ["https://wasm.org"],
            }
        ],
    }
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(
        return_value=AIMessage(
            content=json.dumps(
                [
                    {
                        "claim": "Wasm runs in browsers",
                        "status": "VERIFIED",
                        "notes": "Standard feature in all browsers",
                        "supporting_sources": ["https://wasm.org"],
                    }
                ]
            )
        )
    )

    with patch("src.agents.nodes.get_llm", return_value=mock_llm):
        out = await fact_checker_node(state)
        assert out["status"] == "writing"
        assert len(out["fact_checks"]) == 1
        assert out["fact_checks"][0]["status"] == "VERIFIED"


@pytest.mark.asyncio
async def test_writer_and_reviewer_nodes():
    state = {
        "topic": "AI Testing",
        "findings": [
            {
                "claim": "AI helps write unit tests",
                "evidence": "docs",
                "sources": ["https://ai.org"],
            }
        ],
        "fact_checks": [{"claim": "AI helps write unit tests", "status": "VERIFIED"}],
        "sources_used": ["https://ai.org"],
        "review_feedback": "",
    }
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(
        return_value=AIMessage(
            content="# AI Testing\n\n## Executive Summary\nAI accelerates unit testing."
        )
    )

    with (
        patch("src.agents.nodes.get_llm", return_value=mock_llm),
        patch("src.agents.nodes.get_rag") as mock_rag,
    ):
        mock_rag.return_value.add_texts.return_value = 1
        writer_out = await writer_node(state)
        assert writer_out["status"] == "reviewing"
        assert "AI Testing" in writer_out["draft_report"]

    state["draft_report"] = writer_out["draft_report"]
    state["review_count"] = 0

    mock_llm.ainvoke = AsyncMock(
        return_value=AIMessage(
            content=json.dumps({"approved": True, "score": 9, "feedback": "Well structured"})
        )
    )

    with patch("src.agents.nodes.get_llm", return_value=mock_llm):
        rev_out = await reviewer_node(state)
        assert rev_out["status"] == "done"
        assert rev_out["final_report"] == writer_out["draft_report"]
        assert rev_out["review_count"] == 1
