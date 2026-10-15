"""Workspaces and Document Collector Subsystem."""

from .models import Workspace, WorkspaceDocument
from .collector import DocumentCollector
from .manager import WorkspaceManager, get_workspace_manager

__all__ = [
    "Workspace",
    "WorkspaceDocument",
    "DocumentCollector",
    "WorkspaceManager",
    "get_workspace_manager",
]
