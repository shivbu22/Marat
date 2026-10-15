"""Unit tests for Workspaces and Document Collector."""

from pathlib import Path

from src.workspaces.manager import WorkspaceManager
from src.workspaces.collector import DocumentCollector


def test_document_collector_code_extraction():
    collector = DocumentCollector(chunk_size=100, chunk_overlap=20)
    sample_code = "def hello():\n    print('world')\n" * 10
    text, file_type = collector.extract_text("sample.py", sample_code.encode("utf-8"))
    assert file_type == "code"
    chunks = collector.chunk_document(text, {"filename": "sample.py"})
    assert len(chunks) > 0
    assert chunks[0]["metadata"]["filename"] == "sample.py"


def test_workspace_crud(tmp_path: Path):
    db_file = tmp_path / "workspaces_test.db"
    mgr = WorkspaceManager(db_path=db_file)

    # 1. Create workspace
    ws = mgr.create_workspace(name="Security Audit", description="Vulnerability and binary analysis")
    assert ws.name == "Security Audit"
    assert ws.slug == "security-audit"

    # 2. List workspaces
    workspaces = mgr.list_workspaces()
    assert len(workspaces) >= 2  # default + new

    # 3. Add document
    doc, chunks = mgr.add_document(
        workspace_id=ws.id,
        filename="notes.md",
        content_bytes=b"# Security Notes\nBinary entry point at 0x140001000\n",
    )
    assert doc.filename == "notes.md"
    assert len(chunks) > 0

    docs = mgr.list_documents(ws.id)
    assert len(docs) == 1
    assert docs[0].filename == "notes.md"

    # 4. Delete workspace
    assert mgr.delete_workspace(ws.id) is True
    assert mgr.get_workspace(ws.id) is None
