"""LLM factory – supports Ollama, OpenAI, OpenRouter, Anthropic via OpenAI-compatible client."""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from .config import get_settings


def _resolve_ollama_model(base_url: str, requested: str) -> str:
    """Resolve model name against locally installed Ollama tags (e.g. llama3.2 -> llama3.2:3b)."""
    if ":" in requested:
        return requested
    try:
        import httpx

        root_url = base_url.replace("/v1", "").rstrip("/")
        resp = httpx.get(f"{root_url}/api/tags", timeout=1.5)
        if resp.status_code == 200:
            models = [m.get("name", "") for m in resp.json().get("models", [])]
            if requested in models:
                return requested
            for m in models:
                if m.startswith(f"{requested}:"):
                    return m
    except Exception:
        pass
    return requested


def get_llm(temperature: float | None = None, model: str | None = None) -> BaseChatModel:
    s = get_settings()
    temp = temperature if temperature is not None else s.temperature
    model_name = model or s.llm_model

    # All providers go through OpenAI-compatible endpoint where possible
    if s.llm_provider == "ollama":
        resolved_model = _resolve_ollama_model(s.llm_base_url, model_name)
        return ChatOpenAI(
            model=resolved_model,
            base_url=s.llm_base_url,
            api_key=s.llm_api_key or "ollama",
            temperature=temp,
            max_tokens=s.max_tokens,
        )
    if s.llm_provider == "openrouter":
        return ChatOpenAI(
            model=model_name,
            base_url="https://openrouter.ai/api/v1",
            api_key=s.llm_api_key,
            temperature=temp,
            max_tokens=s.max_tokens,
            default_headers={
                "HTTP-Referer": "https://github.com/local-jarvis/research-assistant",
                "X-Title": "Multi-Agent Research Assistant",
            },
        )
    # openai / anthropic (via compatible proxy or native openai client)
    return ChatOpenAI(
        model=model_name,
        api_key=s.llm_api_key,
        temperature=temp,
        max_tokens=s.max_tokens,
        base_url=s.llm_base_url if s.llm_base_url != "http://localhost:11434/v1" else None,
    )
