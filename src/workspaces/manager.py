"""Workspace Manager - creates, persists, and orchestrates isolated workspaces."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from .models import Workspace, WorkspaceDocument
from .collector import DocumentCollector


class WorkspaceManager:
    """Manages isolated workspaces and their documents."""

    def __init__(self, db_path: str | Path = "./data/workspaces.db"):
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.collector = DocumentCollector()
        self._init_db()
        self._ensure_default_workspace()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS workspaces (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    slug TEXT UNIQUE NOT NULL,
                    description TEXT,
                    system_prompt TEXT,
                    temperature REAL,
                    vector_collection TEXT,
                    documents_count INTEGER DEFAULT 0,
                    created_at REAL,
                    updated_at REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS workspace_documents (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    file_size INTEGER DEFAULT 0,
                    chunks_count INTEGER DEFAULT 0,
                    created_at REAL,
                    metadata_json TEXT,
                    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
                )
            """)
            conn.commit()

    def _ensure_default_workspace(self) -> None:
        """Create the default research & engineering workspace if none exists."""
        if not self.get_workspace_by_slug("default"):
            self.create_workspace(
                name="Default Workspace",
                slug="default",
                description="Default multi-agent research, document vault, and reverse engineering workbench.",
                system_prompt="You are Mara, a studious and clever red panda research companion. Guide the user with accuracy, depth, and evidence.",
            )

    def create_workspace(
        self,
        name: str,
        slug: str | None = None,
        description: str = "",
        system_prompt: str = "",
        temperature: float = 0.2,
    ) -> Workspace:
        clean_slug = slug or name.lower().replace(" ", "-")
        clean_slug = "".join(c for c in clean_slug if c.isalnum() or c in "-_")
        collection_name = f"ws_{clean_slug}"

        ws = Workspace(
            name=name,
            slug=clean_slug,
            description=description,
            system_prompt=system_prompt or "You are Mara, a studious red panda companion.",
            temperature=temperature,
            vector_collection=collection_name,
        )

        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO workspaces 
                (id, name, slug, description, system_prompt, temperature, vector_collection, documents_count, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ws.id,
                    ws.name,
                    ws.slug,
                    ws.description,
                    ws.system_prompt,
                    ws.temperature,
                    ws.vector_collection,
                    ws.documents_count,
                    ws.created_at,
                    ws.updated_at,
                ),
            )
            conn.commit()
        return ws

    def get_workspace(self, workspace_id: str) -> Workspace | None:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM workspaces WHERE id = ?", (workspace_id,)).fetchone()
            if row:
                return Workspace(**dict(row))
        return None

    def get_workspace_by_slug(self, slug: str) -> Workspace | None:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM workspaces WHERE slug = ?", (slug,)).fetchone()
            if row:
                return Workspace(**dict(row))
        return None

    def list_workspaces(self) -> list[Workspace]:
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM workspaces ORDER BY created_at DESC").fetchall()
            return [Workspace(**dict(r)) for r in rows]

    def update_workspace(self, workspace_id: str, **kwargs: Any) -> Workspace | None:
        ws = self.get_workspace(workspace_id)
        if not ws:
            return None

        update_data = ws.model_dump()
        for k, v in kwargs.items():
            if k in update_data and v is not None:
                update_data[k] = v
        update_data["updated_at"] = time.time()
        updated_ws = Workspace(**update_data)

        with self._get_conn() as conn:
            conn.execute(
                """
                UPDATE workspaces 
                SET name = ?, description = ?, system_prompt = ?, temperature = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    updated_ws.name,
                    updated_ws.description,
                    updated_ws.system_prompt,
                    updated_ws.temperature,
                    updated_ws.updated_at,
                    workspace_id,
                ),
            )
            conn.commit()
        return updated_ws

    def delete_workspace(self, workspace_id: str) -> bool:
        with self._get_conn() as conn:
            conn.execute("DELETE FROM workspace_documents WHERE workspace_id = ?", (workspace_id,))
            res = conn.execute("DELETE FROM workspaces WHERE id = ?", (workspace_id,))
            conn.commit()
            return res.rowcount > 0

    def add_document(
        self,
        workspace_id: str,
        filename: str,
        content_bytes: bytes,
        extra_metadata: dict[str, Any] | None = None,
    ) -> tuple[WorkspaceDocument, list[dict[str, Any]]]:
        """Collect and chunk a document, return the document model and prepared chunks."""
        ws = self.get_workspace(workspace_id)
        if not ws:
            raise ValueError(f"Workspace {workspace_id} not found")

        text, file_type = self.collector.extract_text(filename, content_bytes)
        metadata = {
            "workspace_id": workspace_id,
            "filename": filename,
            "file_type": file_type,
            **(extra_metadata or {}),
        }
        chunks = self.collector.chunk_document(text, metadata)

        doc = WorkspaceDocument(
            workspace_id=workspace_id,
            filename=filename,
            file_type=file_type,
            file_size=len(content_bytes),
            chunks_count=len(chunks),
            metadata=metadata,
        )

        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO workspace_documents 
                (id, workspace_id, filename, file_type, file_size, chunks_count, created_at, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc.id,
                    doc.workspace_id,
                    doc.filename,
                    doc.file_type,
                    doc.file_size,
                    doc.chunks_count,
                    doc.created_at,
                    json.dumps(doc.metadata),
                ),
            )
            conn.execute(
                "UPDATE workspaces SET documents_count = documents_count + 1, updated_at = ? WHERE id = ?",
                (time.time(), workspace_id),
            )
            conn.commit()

        return doc, chunks

    def list_documents(self, workspace_id: str) -> list[WorkspaceDocument]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM workspace_documents WHERE workspace_id = ? ORDER BY created_at DESC",
                (workspace_id,),
            ).fetchall()
            docs = []
            for r in rows:
                d = dict(r)
                meta_json = d.pop("metadata_json", "{}")
                d["metadata"] = json.loads(meta_json or "{}")
                docs.append(WorkspaceDocument(**d))
            return docs


_ws_manager: WorkspaceManager | None = None


def get_workspace_manager() -> WorkspaceManager:
    global _ws_manager
    if _ws_manager is None:
        _ws_manager = WorkspaceManager()
    return _ws_manager
