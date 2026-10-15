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


def _is_recent_query(query: str) -> bool:
    """Check if the query is seeking current, breaking, or recent 6 months info."""
    lowered = query.lower()
    recent_keywords = [
        "recent", "latest", "last", "months", "what happen", "news", "today",
        "breaking", "current", "update", "2024", "2025", "2026", "new", "released", "announced"
    ]
    return any(k in lowered for k in recent_keywords)


def _is_india_query(query: str) -> bool:
    """Check if the query is related to India, its national news, institutions, or affairs."""
    lowered = query.lower()
    india_keywords = [
        "india", "indian", "delhi", "mumbai", "bengaluru", "bangalore", "hyderabad",
        "chennai", "kolkata", "modi", "isro", "upi", "rbi", "nifty", "sensex",
        "lok sabha", "rajya sabha", "pib", "vande bharat", "gaganyaan", "aditya-l1",
        "bharat", "drdo", "brics", "rupee", "ayodhya", "kerala", "tamil nadu",
        "maharashtra", "uttar pradesh", "gujarat", "punjab", "karnataka"
    ]
    return any(k in lowered for k in india_keywords)


def _ddg_search(
    query: str, max_results: int, timelimit: str | None = None, region: str | None = None
) -> list[SearchResult]:
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

    results: list[SearchResult] = []
    seen_urls: set[str] = set()

    is_india = _is_india_query(query)
    effective_region = region or ("in-en" if is_india else None)
    should_fetch_news = timelimit is not None or _is_recent_query(query) or is_india

    try:
        with DDGS_cls() as ddgs:
            # 1. Fetch live news if recent context is requested
            if should_fetch_news and hasattr(ddgs, "news"):
                try:
                    news_kwargs = {"max_results": max_results}
                    if effective_region:
                        news_kwargs["region"] = effective_region
                    news_raw = list(ddgs.news(query, **news_kwargs))
                    for r in news_raw:
                        u = r.get("href", r.get("link", r.get("url", "")))
                        if u and u not in seen_urls:
                            seen_urls.add(u)
                            date_str = f" [{r.get('date', '')}]" if r.get("date") else ""
                            results.append(
                                SearchResult(
                                    title=f"{r.get('title', '')}{date_str}",
                                    url=u,
                                    snippet=r.get("body", r.get("snippet", "")),
                                    source="duckduckgo_news",
                                )
                            )
                except Exception:
                    pass

            # 2. Fetch general web results (with timelimit if requested)
            needed = max_results - len(results)
            if needed > 0:
                tl = timelimit or ("m" if _is_recent_query(query) else None)
                kwargs = {"max_results": needed + 2}
                if tl:
                    kwargs["timelimit"] = tl
                if effective_region:
                    kwargs["region"] = effective_region
                try:
                    text_raw = list(ddgs.text(query, **kwargs))
                except Exception:
                    text_raw = list(ddgs.text(query, max_results=needed))

                for r in text_raw:
                    u = r.get("href", r.get("link", r.get("url", "")))
                    if u and u not in seen_urls:
                        seen_urls.add(u)
                        results.append(
                            SearchResult(
                                title=r.get("title", ""),
                                url=u,
                                snippet=r.get("body", r.get("snippet", "")),
                                source="duckduckgo",
                            )
                        )
    except Exception:
        return results

    return results[:max_results]


def search_india_news(query: str = "India top news today", max_results: int = 6) -> list[SearchResult]:
    """Fetch live breaking and national headlines from India."""
    return _ddg_search(query, max_results=max_results, timelimit="d", region="in-en")



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


async def web_search_async(query: str, timelimit: str | None = None) -> list[SearchResult]:
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
    return await loop.run_in_executor(
        None, lambda: _ddg_search(query, s.search_max_results, timelimit=timelimit)
    )

