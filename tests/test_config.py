"""Unit tests for configuration loading."""

from pathlib import Path

from src.config import Settings, get_settings


def test_default_settings():
    s = get_settings()
    assert s.llm_provider in ["ollama", "openai", "openrouter", "anthropic"]
    assert s.max_sub_questions >= 1
    assert s.max_review_cycles >= 1
    assert isinstance(s.rag_enabled, bool)
    assert isinstance(s.rag_persist_dir, Path)
    assert s.api_port == 8000


def test_custom_settings():
    custom = Settings(
        llm_provider="openai",
        llm_model="gpt-4o",
        temperature=0.7,
        max_sub_questions=3,
        max_review_cycles=1,
    )
    assert custom.llm_provider == "openai"
    assert custom.llm_model == "gpt-4o"
    assert custom.temperature == 0.7
    assert custom.max_sub_questions == 3
