"""Persistent Chat Memory Engine for MARAT.

Maintains data/memory/chat_history.json and embeds conversation turns into
the ChromaDB vector vault so that chatting on the same topic continuously refines
and improves institutional memory.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .models import ChatMemoryRecord
from ..rag.store import get_rag


class PersistentChatMemory:
    """Manages persistent chat memory in JSON file + vector index."""

    def __init__(self, memory_dir: str | Path = "./data/memory"):
        self.memory_dir = Path(memory_dir).resolve()
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.json_file = self.memory_dir / "chat_history.json"
        self._records: list[ChatMemoryRecord] = []
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        if self.json_file.exists():
            try:
                raw = json.loads(self.json_file.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    self._records = [ChatMemoryRecord(**r) for r in raw]
            except Exception:
                self._records = []
        else:
            self._save_to_disk()

    def _save_to_disk(self) -> None:
        try:
            data = [r.model_dump() for r in self._records]
            self.json_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def append_turn(
        self,
        workspace_id: str,
        thread_id: str,
        user_message: str,
        assistant_message: str,
        thread_name: str = "",
        mode: str = "chat",
        sources: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ChatMemoryRecord:
        """Record a conversation turn to disk and vector index."""
        record = ChatMemoryRecord(
            workspace_id=workspace_id,
            thread_id=thread_id,
            thread_name=thread_name,
            timestamp=time.time(),
            topic=user_message[:100],
            user_message=user_message,
            assistant_message=assistant_message,
            mode=mode,
            sources=sources or [],
            metadata=metadata or {},
        )
        self._records.append(record)
        self._save_to_disk()

        # Embed turn into vector collection for semantic topic recall
        try:
            rag = get_rag()
            memory_text = (
                f"Topic: {record.topic}\n"
                f"User asked: {user_message}\n"
                f"Assistant conclusion: {assistant_message[:1500]}\n"
                f"Sources: {', '.join(record.sources)}"
            )
            rag.add_texts(
                texts=[memory_text],
                metadatas=[
                    {
                        "type": "chat_memory",
                        "memory_id": record.id,
                        "workspace_id": workspace_id,
                        "thread_id": thread_id,
                        "timestamp": record.timestamp,
                    }
                ],
                collection_name="chat_memory",
            )
        except Exception:
            pass

        return record

    def recall_topic_memory(
        self, query: str, workspace_id: str | None = None, k: int = 3
    ) -> list[dict[str, Any]]:
        """Recall relevant previous chats and findings on this topic."""
        memories: list[dict[str, Any]] = []
        seen_texts: set[str] = set()

        # 1. Vector similarity search from 'chat_memory' collection
        try:
            rag = get_rag()
            hits = rag.search(query, k=k, collection_name="chat_memory")
            for h in hits:
                txt = h.get("text", "").strip()
                if txt and txt not in seen_texts:
                    seen_texts.add(txt)
                    memories.append(
                        {
                            "text": txt,
                            "metadata": h.get("metadata", {}),
                            "similarity": h.get("similarity", 0.0),
                            "source": "vector_memory",
                        }
                    )
        except Exception:
            pass

        # 2. Textual recency fallback if few vector hits
        if len(memories) < k:
            q_lower = query.lower()
            keywords = [w for w in q_lower.split() if len(w) > 3]
            for rec in reversed(self._records):
                if workspace_id and rec.workspace_id != workspace_id:
                    continue
                match = any(kw in rec.user_message.lower() or kw in rec.assistant_message.lower() for kw in keywords)
                if match:
                    snippet = f"User asked: {rec.user_message}\nPrior answer: {rec.assistant_message[:800]}"
                    if snippet not in seen_texts:
                        seen_texts.add(snippet)
                        memories.append(
                            {
                                "text": snippet,
                                "metadata": {
                                    "memory_id": rec.id,
                                    "timestamp": rec.timestamp,
                                    "thread_name": rec.thread_name,
                                },
                                "source": "history_file",
                            }
                        )
                if len(memories) >= k:
                    break

        return memories

    def get_all_records(self) -> list[ChatMemoryRecord]:
        return list(self._records)

    def get_file_path(self) -> Path:
        return self.json_file

    def import_records(self, json_content: str) -> int:
        """Import conversation turns from external JSON and re-index."""
        raw = json.loads(json_content)
        if not isinstance(raw, list):
            raise ValueError("Expected a JSON list of records")

        imported = 0
        for item in raw:
            try:
                rec = ChatMemoryRecord(**item)
                if not any(r.id == rec.id for r in self._records):
                    self._records.append(rec)
                    imported += 1
            except Exception:
                continue

        self._save_to_disk()

        # Re-index newly imported records into vector collection
        try:
            rag = get_rag()
            for r in self._records[-imported:]:
                rag.add_texts(
                    texts=[f"Topic: {r.topic}\nUser: {r.user_message}\nAssistant: {r.assistant_message[:1500]}"],
                    metadatas=[{"type": "chat_memory", "memory_id": r.id, "timestamp": r.timestamp}],
                    collection_name="chat_memory",
                )
        except Exception:
            pass

        return imported


_chat_memory: PersistentChatMemory | None = None


def get_chat_memory() -> PersistentChatMemory:
    global _chat_memory
    if _chat_memory is None:
        _chat_memory = PersistentChatMemory()
    return _chat_memory
