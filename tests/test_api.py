"""Unit tests for FastAPI endpoints."""

from unittest.mock import AsyncMock, patch

from starlette.testclient import TestClient

from src.api.main import app

client = TestClient(app)


def test_health_endpoint():
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "provider" in data
    assert "model" in data


def test_research_endpoint():
    mock_result = {
        "status": "done",
        "final_report": "# Test Report\n\nContent here.",
        "draft_report": "# Test Report\n\nContent here.",
        "sub_questions": [{"id": "q1", "question": "Sub question?"}],
        "findings": [{"claim": "Test claim"}],
        "fact_checks": [{"claim": "Test claim", "status": "VERIFIED"}],
        "sources_used": ["https://test.com"],
        "review_count": 1,
    }

    with patch("src.api.main.get_graph") as mock_graph:
        instance = mock_graph.return_value
        instance.ainvoke = AsyncMock(return_value=mock_result)

        resp = client.post(
            "/research",
            json={"topic": "Quantum Encryption", "focus_mode": "broad"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["topic"] == "Quantum Encryption"
        assert data["status"] == "done"
        assert "# Test Report" in data["final_report"]
        assert data["findings_count"] == 1
        assert data["elapsed_seconds"] >= 0


def test_research_stream_endpoint():
    mock_events = [
        {"planner": {"status": "researching", "sub_questions": [{"id": "q1", "question": "Q1"}]}},
        {
            "reviewer": {
                "status": "done",
                "final_report": "# Streamed Report",
                "sources_used": ["https://s.com"],
            }
        },
    ]

    async def fake_astream(*args, **kwargs):
        for e in mock_events:
            yield e

    with patch("src.api.main.get_graph") as mock_graph:
        instance = mock_graph.return_value
        instance.astream = fake_astream

        resp = client.post(
            "/research/stream",
            json={"topic": "Streaming Test", "focus_mode": "broad"},
        )
        assert resp.status_code == 200
        text = resp.text
        assert "started" in text
        assert "node_update" in text
        assert "completed" in text
