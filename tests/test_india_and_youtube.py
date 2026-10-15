"""Unit tests for India News, YouTube Summaries, and General Answers features."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from starlette.testclient import TestClient

from src.api.main import app
from src.tools.search import _is_india_query, search_india_news
from src.tools.video import VideoLecture, extract_youtube_id, generate_fallback_summary

client = TestClient(app)


def test_is_india_query():
    assert _is_india_query("What is the latest news in India?") is True
    assert _is_india_query("ISRO Aditya-L1 solar mission status") is True
    assert _is_india_query("UPI international transactions in France and UAE") is True
    assert _is_india_query("Tata semiconductor plant in Dholera Gujarat") is True
    assert _is_india_query("Quantum computing at IBM and Google") is False


def test_extract_youtube_id():
    assert extract_youtube_id("https://www.youtube.com/watch?v=aircAruvnKk") == "aircAruvnKk"
    assert extract_youtube_id("https://youtu.be/aircAruvnKk") == "aircAruvnKk"
    assert extract_youtube_id("https://youtube.com/shorts/aircAruvnKk") == "aircAruvnKk"
    assert extract_youtube_id("not a youtube link") is None


def test_generate_fallback_summary():
    lec = VideoLecture(
        title="Sample Video Lecture",
        url="https://youtube.com/watch?v=mock123",
        duration_seconds=180.0,
        full_text="This is an introductory lecture explaining neural network weights, biases, and backpropagation.",
        source_type="youtube_captions",
    )
    summary = generate_fallback_summary(lec)
    assert "Sample Video Lecture" in summary
    assert "Executive Overview" in summary
    assert "Timestamped Chapters" in summary


def test_api_india_news_endpoint():
    mock_results = [
        MagicMock(model_dump=lambda: {"title": "India GDP Growth at 7.2%", "url": "https://pib.gov.in/1", "snippet": "Strong manufacturing growth."})
    ]
    with patch("src.tools.search.search_india_news", return_value=mock_results):
        resp = client.get("/api/news/india?q=economy")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert len(data["articles"]) == 1
        assert "India GDP Growth" in data["articles"][0]["title"]


def test_api_video_summarize_endpoint():
    mock_res = {
        "status": "success",
        "title": "Quantum Mechanics 101",
        "url": "https://youtube.com/watch?v=mock_qm",
        "duration_seconds": 600.0,
        "duration_formatted": "10:00",
        "source_type": "youtube_captions",
        "indexed_chunks": 5,
        "summary": "## Quantum Mechanics 101\nSummary of superposition and entanglement.",
    }
    with patch("src.tools.video.summarize_youtube_video", new=AsyncMock(return_value=mock_res)):
        resp = client.post("/api/video/summarize", json={"url": "https://youtube.com/watch?v=mock_qm"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["title"] == "Quantum Mechanics 101"
        assert "superposition" in data["summary"]
