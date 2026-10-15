"""Data models for Model Context Protocol (MCP) Hypervisor."""

from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class McpServerConfig(BaseModel):
    name: str
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    status: Literal["connected", "offline", "error", "untested"] = "untested"
    error_message: str = ""


class McpToolDefinition(BaseModel):
    server_name: str
    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
