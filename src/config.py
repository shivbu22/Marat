"""Central configuration loaded from environment / .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM
    llm_provider: Literal["ollama", "openai", "openrouter", "anthropic"] = "ollama"
    llm_model: str = "llama3.2"
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = "ollama"
    temperature: float = 0.2
    max_tokens: int = 4096
    max_tool_turns: int = 12

    # Search
    tavily_api_key: str = ""
    search_max_results: int = 6
    search_depth: str = "basic"

    # RAG
    rag_enabled: bool = True
    rag_persist_dir: Path = Path("./data/chroma")
    rag_collection: str = "research_vault"
    embedding_model: str = "nomic-embed-text"
    chunk_size: int = 800
    chunk_overlap: int = 120

    # Agents
    max_sub_questions: int = 5
    max_review_cycles: int = 2
    parallel_researchers: bool = True
    require_sources: bool = True

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "*"

    # Observability
    log_level: str = "INFO"
    save_reports_dir: Path = Path("./reports")


@lru_cache
def get_settings() -> Settings:
    return Settings()
