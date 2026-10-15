import pytest
from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app)


def test_settings_endpoints():
    res = client.get("/api/settings")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "llm_provider" in data
    assert "llm_model" in data

    update_res = client.post(
        "/api/settings",
        json={"temperature": 0.35, "llm_model": "llama3.2:1b"},
    )
    assert update_res.status_code == 200
    up_data = update_res.json()
    assert up_data["status"] == "success"
    assert up_data["temperature"] == 0.35


def test_thread_rename_and_export():
    ws_res = client.get("/api/workspaces")
    assert ws_res.status_code == 200
    workspaces = ws_res.json()
    assert len(workspaces) > 0
    ws_id = workspaces[0]["id"]

    # Create thread
    th_res = client.post(f"/api/workspaces/{ws_id}/threads", json={"name": "Initial Name"})
    assert th_res.status_code == 200
    thread = th_res.json()
    th_id = thread["id"]

    # Rename thread
    patch_res = client.patch(f"/api/threads/{th_id}", json={"name": "Renamed Intelligence Stream"})
    assert patch_res.status_code == 200
    assert patch_res.json()["name"] == "Renamed Intelligence Stream"

    # Export markdown
    export_md = client.get(f"/api/threads/{th_id}/export?format=markdown")
    assert export_md.status_code == 200
    assert "Renamed Intelligence Stream" in export_md.text

    # Export json
    export_json = client.get(f"/api/threads/{th_id}/export?format=json")
    assert export_json.status_code == 200
    assert export_json.json()["thread_name"] == "Renamed Intelligence Stream"


def test_workspace_search_and_document_delete():
    ws_res = client.get("/api/workspaces")
    ws_id = ws_res.json()[0]["id"]

    # Upload document
    files = {"file": ("test_quantum.txt", b"Quantum computing qubits state entanglement.", "text/plain")}
    up_res = client.post(f"/api/workspaces/{ws_id}/upload", files=files)
    assert up_res.status_code == 200
    doc_id = up_res.json()["document"]["id"]

    # Search in workspace
    search_res = client.post(f"/api/workspaces/{ws_id}/search", json={"query": "qubits", "k": 3})
    assert search_res.status_code == 200
    s_data = search_res.json()
    assert s_data["status"] == "ok"

    # Delete document
    del_res = client.delete(f"/api/workspaces/{ws_id}/documents/{doc_id}")
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "deleted"


def test_knowledge_digest():
    res = client.get("/api/knowledge/digest")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert len(data["cards"]) >= 3
