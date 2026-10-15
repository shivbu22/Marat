"""Data models for Workspaces & Document Collector."""

from __future__ import annotations

import time
import uuid
from typing import Any
from pydantic import BaseModel, Field


class Workspace(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    slug: str
    description: str = ""
    system_prompt: str = "You are Mara, a studious and clever red panda research companion. Guide the user with accuracy, depth, and evidence."
    temperature: float = 0.2
    vector_collection: str = ""
    documents_count: int = 0
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


class WorkspaceDocument(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workspace_id: str
    filename: str
    file_type: str
    file_size: int = 0
    chunks_count: int = 0
    created_at: float = Field(default_factory=time.time)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkspaceThread(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workspace_id: str
    name: str = "New Thread"
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


class ThreadMessage(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    thread_id: str
    workspace_id: str
    role: str  # "user" | "assistant" | "system"
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)


class ChatMemoryRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workspace_id: str
    thread_id: str
    thread_name: str = ""
    timestamp: float = Field(default_factory=time.time)
    topic: str = ""
    user_message: str
    assistant_message: str
    mode: str = "chat"
    sources: list[str] = Field(default_factory=list)
    key_facts: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


