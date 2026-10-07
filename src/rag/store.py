"""Lightweight local RAG store using Chroma + local embeddings."""

from __future__ import annotations

import hashlib
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..config import get_settings


class ResearchRAG:
    """Simple persistent RAG vault for research notes and past reports."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = None
        self._collection = None
        self._embeddings = None
        self._ready = False

    def _ensure(self) -> bool:
        if self._ready:
            return True
        if not self.settings.rag_enabled:
            return False
        try:
            import chromadb
            from chromadb.config import Settings as ChromaSettings

            self.settings.rag_persist_dir.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(
                path=str(self.settings.rag_persist_dir),
                settings=ChromaSettings(anonymized_telemetry=False),
            )
            self._collection = self._client.get_or_create_collection(
                name=self.settings.rag_collection,
                metadata={"hnsw:space": "cosine"},
            )
            # Embedding initialization priority:
            # 1. Ollama embeddings if provider is ollama or base_url specified
            # 2. sentence-transformers if available
            # 3. Deterministic hash fallback
            self._embeddings = None
            if self.settings.llm_provider == "ollama" or "localhost" in self.settings.llm_base_url:
                try:
                    from langchain_ollama import OllamaEmbeddings

                    emb_model = self.settings.embedding_model or "nomic-embed-text"
                    base_url = self.settings.llm_base_url.removesuffix("/v1")
                    self._embeddings = OllamaEmbeddings(
                        model=emb_model,
                        base_url=base_url,
                    )
                except Exception:
                    self._embeddings = None

            if self._embeddings is None:
                try:
                    from sentence_transformers import SentenceTransformer

                    self._embeddings = SentenceTransformer("all-MiniLM-L6-v2")
                except Exception:
                    self._embeddings = None
            self._ready = True
            return True
        except Exception as e:
            print(f"[RAG] Disabled – could not init: {e}")
            return False

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if self._embeddings is not None:
            try:
                if hasattr(self._embeddings, "embed_documents"):
                    return self._embeddings.embed_documents(texts)
                if hasattr(self._embeddings, "encode"):
                    return self._embeddings.encode(texts).tolist()
            except Exception:
                pass
        # Deterministic fallback embedding (not semantic, but keeps system running)
        return [
            [((hashlib.md5((t + str(i)).encode()).digest()[j % 16]) / 255.0) for j in range(32)]
            for i, t in enumerate(texts)
        ]

    def add_texts(self, texts: list[str], metadatas: list[dict[str, Any]] | None = None) -> int:
        if not self._ensure() or not texts:
            return 0
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.settings.chunk_size,
            chunk_overlap=self.settings.chunk_overlap,
        )
        docs: list[Document] = []
        for i, text in enumerate(texts):
            meta = (metadatas[i] if metadatas else {}) or {}
            chunks = splitter.create_documents([text], metadatas=[meta])
            docs.extend(chunks)

        if not docs:
            return 0

        ids = [hashlib.sha256(d.page_content.encode()).hexdigest()[:16] for d in docs]
        embeddings = self._embed([d.page_content for d in docs])
        metadatas_to_upsert = []
        for idx, d in enumerate(docs):
            meta_dict = dict(d.metadata) if d.metadata else {}
            if not meta_dict:
                meta_dict = {"source": "rag", "chunk": idx}
            metadatas_to_upsert.append(meta_dict)
        self._collection.upsert(
            ids=ids,
            documents=[d.page_content for d in docs],
            embeddings=embeddings,
            metadatas=metadatas_to_upsert,
        )
        return len(docs)

    def search(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        if not self._ensure() or self._collection is None:
            return []
        try:
            total = self._collection.count()
            if total == 0:
                return []
            actual_k = min(k, total)
            emb = self._embed([query])[0]
            res = self._collection.query(query_embeddings=[emb], n_results=actual_k)
            out = []
            if res and res.get("ids") and len(res["ids"]) > 0:
                for i in range(len(res["ids"][0])):
                    out.append(
                        {
                            "id": res["ids"][0][i],
                            "text": res["documents"][0][i] if res.get("documents") else "",
                            "metadata": res["metadatas"][0][i] if res.get("metadatas") else {},
                            "distance": res["distances"][0][i] if res.get("distances") else None,
                        }
                    )
            return out
        except Exception:
            return []


# Singleton
_rag: ResearchRAG | None = None


def get_rag() -> ResearchRAG:
    global _rag
    if _rag is None:
        _rag = ResearchRAG()
    return _rag
