"""Unit tests for search tools."""

from unittest.mock import MagicMock, patch

import pytest

from src.tools.search import SearchResult, _ddg_search, web_search, web_search_async


def test_search_result_model():
    res = SearchResult(
        title="Test Title",
        url="https://example.com",
        snippet="Sample snippet content",
        source="duckduckgo",
    )
    assert res.title == "Test Title"
    assert res.url == "https://example.com"
    assert res.snippet == "Sample snippet content"
    assert res.source == "duckduckgo"


@patch("ddgs.DDGS")
def test_ddg_search_mock(mock_ddgs_cls):
    mock_instance = MagicMock()
    mock_instance.__enter__.return_value = mock_instance
    mock_instance.text.return_value = [
        {"title": "Result 1", "href": "https://r1.com", "body": "Snippet 1"},
        {"title": "Result 2", "link": "https://r2.com", "snippet": "Snippet 2"},
    ]
    mock_ddgs_cls.return_value = mock_instance

    results = _ddg_search("AI agents", max_results=2)
    assert len(results) == 2
    assert results[0].title == "Result 1"
    assert results[0].url == "https://r1.com"
    assert results[1].title == "Result 2"
    assert results[1].url == "https://r2.com"


@patch("src.tools.search._ddg_search")
def test_web_search_fallback(mock_ddg):
    mock_ddg.return_value = [
        SearchResult(
            title="LangGraph Overview",
            url="https://langchain.com",
            snippet="LangGraph is a library for building stateful agents.",
            source="duckduckgo",
        )
    ]
    formatted = web_search.invoke("What is LangGraph?")
    assert "LangGraph Overview" in formatted
    assert "https://langchain.com" in formatted


@pytest.mark.asyncio
@patch("src.tools.search._ddg_search")
async def test_web_search_async_mock(mock_ddg):
    mock_ddg.return_value = [
        SearchResult(
            title="Async Search Result",
            url="https://test.com",
            snippet="Testing async web search wrapper",
            source="duckduckgo",
        )
    ]
    results = await web_search_async("Async test query")
    assert len(results) == 1
    assert results[0].title == "Async Search Result"
