"""Unit tests for ResearchRAG vector store."""

import tempfile
from pathlib import Path
from unittest.mock import patch

from src.config import Settings
from src.rag.store import ResearchRAG


def test_rag_empty_search():
    with patch("sentence_transformers.SentenceTransformer", side_effect=Exception("Offline test")):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            rag = ResearchRAG()
            rag.settings = Settings(
                rag_enabled=True,
                rag_persist_dir=Path(tmpdir),
                rag_collection="test_empty",
            )
            results = rag.search("anything", k=3)
            assert results == []


def test_rag_add_and_search():
    with patch("sentence_transformers.SentenceTransformer", side_effect=Exception("Offline test")):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            rag = ResearchRAG()
            rag.settings = Settings(
                rag_enabled=True,
                rag_persist_dir=Path(tmpdir),
                rag_collection="test_vault",
                chunk_size=200,
                chunk_overlap=20,
            )
            doc1 = "LangGraph is designed for cyclic agent workflows and state machines."
            doc2 = "FastAPI provides high performance asynchronous web APIs in Python."

            added = rag.add_texts([doc1, doc2], metadatas=[{"topic": "ai"}, {"topic": "web"}])
            assert added >= 2

            results = rag.search("LangGraph workflows", k=2)
            assert len(results) <= 2
            assert len(results) > 0
            assert "text" in results[0]
            assert "metadata" in results[0]


def test_rag_disabled():
    rag = ResearchRAG()
    rag.settings = Settings(rag_enabled=False)
    assert rag.add_texts(["some text"]) == 0
    assert rag.search("query") == []
