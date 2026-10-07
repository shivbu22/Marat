"""Web search tools – DuckDuckGo (free) + optional Tavily."""

from __future__ import annotations

import asyncio

from langchain_core.tools import tool
from pydantic import BaseModel

from ..config import get_settings


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str
    source: str = "web"


def _ddg_search(query: str, max_results: int) -> list[SearchResult]:
    DDGS_cls = None
    try:
        from ddgs import DDGS as DDGS_cls
    except ImportError:
        try:
            from duckduckgo_search import DDGS as DDGS_cls
        except ImportError:
            return []

    if DDGS_cls is None:
        return []

    results = []
    try:
        with DDGS_cls() as ddgs:
            raw = list(ddgs.text(query, max_results=max_results))
            if not raw and hasattr(ddgs, "news"):
                raw = list(ddgs.news(query, max_results=max_results))
            for r in raw:
                results.append(
                    SearchResult(
                        title=r.get("title", ""),
                        url=r.get("href", r.get("link", r.get("url", ""))),
                        snippet=r.get("body", r.get("snippet", "")),
                        source="duckduckgo",
                    )
                )
    except Exception:
        return results
    return results


def _tavily_search(query: str, max_results: int, depth: str) -> list[SearchResult]:
    s = get_settings()
    if not s.tavily_api_key:
        return []
    try:
        from tavily import TavilyClient

        client = TavilyClient(api_key=s.tavily_api_key)
        resp = client.search(
            query=query,
            max_results=max_results,
            search_depth=depth,
            include_answer=False,
        )
        return [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("content", ""),
                source="tavily",
            )
            for r in resp.get("results", [])
        ]
    except Exception:
        return []


@tool
def web_search(query: str) -> str:
    """Search the web for current information. Returns titles, URLs and snippets."""
    s = get_settings()
    results: list[SearchResult] = []

    # Prefer Tavily when key is present
    if s.tavily_api_key:
        results = _tavily_search(query, s.search_max_results, s.search_depth)

    # Fallback / supplement with DuckDuckGo
    if len(results) < s.search_max_results:
        ddg = _ddg_search(query, s.search_max_results - len(results))
        results.extend(ddg)

    if not results:
        return "No search results found. Try rephrasing the query."

    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"[{i}] {r.title}\n    URL: {r.url}\n    {r.snippet}\n")
    return "\n".join(lines)


async def web_search_async(query: str) -> list[SearchResult]:
    """Async-friendly version used by researcher agents."""
    s = get_settings()
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.get_event_loop()
    if s.tavily_api_key:
        results = await loop.run_in_executor(
            None, lambda: _tavily_search(query, s.search_max_results, s.search_depth)
        )
        if results:
            return results
    return await loop.run_in_executor(None, lambda: _ddg_search(query, s.search_max_results))
