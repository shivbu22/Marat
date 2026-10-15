"""Lightweight local RAG store using Chroma + local embeddings with multi-workspace support."""

from __future__ import annotations

import hashlib
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..config import get_settings


class ResearchRAG:
    """Persistent RAG vault for research notes, past reports, and isolated workspaces."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = None
        self._collection = None
        self._collections: dict[str, Any] = {}
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
            self._collections[self.settings.rag_collection] = self._collection

            self._embeddings = None
            if self.settings.embedding_model != "fallback":
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
                        from chromadb.utils import embedding_functions

                        self._embeddings = embedding_functions.DefaultEmbeddingFunction()
                    except Exception:
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

    def _get_target_collection(self, collection_name: str | None = None) -> Any:
        if not self._ensure():
            return None
        col_name = collection_name or self.settings.rag_collection
        if col_name not in self._collections and self._client is not None:
            self._collections[col_name] = self._client.get_or_create_collection(
                name=col_name,
                metadata={"hnsw:space": "cosine"},
            )
        return self._collections.get(col_name, self._collection)

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if self._embeddings is not None:
            try:
                if hasattr(self._embeddings, "embed_documents"):
                    return self._embeddings.embed_documents(texts)
                if hasattr(self._embeddings, "encode"):
                    return self._embeddings.encode(texts).tolist()
                if callable(self._embeddings):
                    res = self._embeddings(texts)
                    return [list(map(float, vec)) for vec in res]
            except Exception:
                pass
        # Deterministic 384-dim fallback embedding
        return [
            [((hashlib.md5((t + str(i) + str(j)).encode()).digest()[j % 16]) / 255.0) for j in range(384)]
            for i, t in enumerate(texts)
        ]

    def add_texts(
        self,
        texts: list[str],
        metadatas: list[dict[str, Any]] | None = None,
        collection_name: str | None = None,
    ) -> int:
        if not self._ensure() or not texts:
            return 0
        col = self._get_target_collection(collection_name)
        if col is None:
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

        ids = [hashlib.sha256(f"{d.page_content}_{idx}".encode()).hexdigest()[:16] for idx, d in enumerate(docs)]
        embeddings = self._embed([d.page_content for d in docs])
        metadatas_to_upsert = []
        for idx, d in enumerate(docs):
            meta_dict = dict(d.metadata) if d.metadata else {}
            if not meta_dict:
                meta_dict = {"source": "rag", "chunk": idx}
            metadatas_to_upsert.append(meta_dict)

        col.upsert(
            ids=ids,
            documents=[d.page_content for d in docs],
            embeddings=embeddings,
            metadatas=metadatas_to_upsert,
        )
        return len(docs)

    def add_chunks(
        self,
        chunks: list[dict[str, Any]],
        collection_name: str | None = None,
    ) -> int:
        """Add pre-chunked documents directly into target collection."""
        if not self._ensure() or not chunks:
            return 0
        col = self._get_target_collection(collection_name)
        if col is None:
            return 0

        texts = [c["text"] for c in chunks]
        metadatas = [c.get("metadata", {}) for c in chunks]
        ids = [hashlib.sha256(f"{t}_{i}".encode()).hexdigest()[:16] for i, t in enumerate(texts)]
        embeddings = self._embed(texts)

        col.upsert(
            ids=ids,
            documents=texts,
            embeddings=embeddings,
            metadatas=metadatas,
        )
        return len(chunks)

    def count(self, collection_name: str | None = None) -> int:
        col = self._get_target_collection(collection_name)
        if col is None:
            return 0
        try:
            return col.count()
        except Exception:
            return 0

    def search(
        self,
        query: str,
        k: int = 5,
        collection_name: str | None = None,
    ) -> list[dict[str, Any]]:
        col = self._get_target_collection(collection_name)
        if col is None:
            return []
        try:
            total = col.count()
            if total == 0:
                return []
            actual_k = min(k, total)
            emb = self._embed([query])[0]
            res = col.query(query_embeddings=[emb], n_results=actual_k)
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
