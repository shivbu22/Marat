"""Unit tests for Persistent Chat Memory and memory recall."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from starlette.testclient import TestClient

from src.api.main import app
from src.workspaces.memory import PersistentChatMemory

client = TestClient(app)


def test_persistent_chat_memory_crud(tmp_path: Path):
    mem_dir = tmp_path / "memory"
    mem = PersistentChatMemory(memory_dir=mem_dir)

    # Initially empty
    assert len(mem.get_all_records()) == 0
    assert mem.get_file_path().exists()

    # Append turn
    record = mem.append_turn(
        workspace_id="ws_default",
        thread_id="th_1",
        thread_name="Quantum Computing",
        user_message="Explain quantum supremacy and Willow chip",
        assistant_message="Google Willow chip achieved quantum error reduction exponentially below threshold.",
        sources=["https://google.com/willow"],
    )

    assert record.user_message == "Explain quantum supremacy and Willow chip"
    assert len(mem.get_all_records()) == 1

    # Check persistence on disk in JSON format
    json_path = mem.get_file_path()
    assert json_path.exists()
    disk_data = json.loads(json_path.read_text(encoding="utf-8"))
    assert len(disk_data) == 1
    assert disk_data[0]["user_message"] == "Explain quantum supremacy and Willow chip"

    # Reload into new instance
    mem2 = PersistentChatMemory(memory_dir=mem_dir)
    assert len(mem2.get_all_records()) == 1
    assert mem2.get_all_records()[0].id == record.id


def test_topic_memory_recall(tmp_path: Path):
    mem = PersistentChatMemory(memory_dir=tmp_path / "memory")

    mem.append_turn(
        workspace_id="ws_default",
        thread_id="th_1",
        user_message="What happened with SpaceX Mechazilla catching the booster?",
        assistant_message="SpaceX caught the Super Heavy booster mid-air using Mechazilla tower chopstick arms on Flight 5.",
    )

    mem.append_turn(
        workspace_id="ws_default",
        thread_id="th_2",
        user_message="Tell me about DeepSeek R1 open-weights reasoning model",
        assistant_message="DeepSeek released R1, an open-weights reasoning model trained with reinforcement learning.",
    )

    # Query with keyword matching the first turn
    results = mem.recall_topic_memory("SpaceX Mechazilla rocket")
    assert len(results) > 0
    assert any("Mechazilla" in r["text"] for r in results)


def test_memory_import_export(tmp_path: Path):
    mem = PersistentChatMemory(memory_dir=tmp_path / "memory")
    sample_data = [
        {
            "id": "mem_import_1",
            "workspace_id": "ws_test",
            "thread_id": "th_import",
            "thread_name": "AI Safety",
            "timestamp": 1700000000.0,
            "topic": "Alignment",
            "user_message": "What is constitutional AI?",
            "assistant_message": "Constitutional AI uses self-critique based on predefined principles.",
            "mode": "chat",
            "sources": [],
            "metadata": {},
        }
    ]

    imported_count = mem.import_records(json.dumps(sample_data))
    assert imported_count == 1
    assert len(mem.get_all_records()) == 1
    assert mem.get_all_records()[0].id == "mem_import_1"


def test_api_memory_endpoints():
    # 1. Status
    resp = client.get("/api/memory")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "file_path" in data
    assert "total_turns" in data

    # 2. Recall endpoint
    resp_recall = client.get("/api/memory/recall?q=deepseek")
    assert resp_recall.status_code == 200
    assert "recalled_memories" in resp_recall.json()

    # 3. Export endpoint
    resp_export = client.get("/api/memory/export")
    assert resp_export.status_code == 200
    assert resp_export.headers.get("content-type") == "application/json"
