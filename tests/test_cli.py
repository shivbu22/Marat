"""Unit tests for CLI commands."""

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from src.cli import app

runner = CliRunner()


def test_cli_help():
    res = runner.invoke(app, ["--help"])
    assert res.exit_code == 0
    assert "research" in res.output
    assert "serve" in res.output


def test_cli_research_mock():
    async def fake_astream(*args, **kwargs):
        yield {"planner": {"status": "researching", "sub_questions": [{"id": "q1"}]}}
        yield {
            "reviewer": {
                "status": "done",
                "final_report": "# Generated Report\n\nBody of the report.",
            }
        }

    with patch("src.cli.get_graph") as mock_graph:
        instance = mock_graph.return_value
        instance.astream = fake_astream

        res = runner.invoke(app, ["research", "Test Topic", "--no-save"])
        assert res.exit_code == 0
        assert "Generated Report" in res.output


def test_cli_ingest_video():
    mock_lecture = MagicMock()
    mock_lecture.title = "Transformers Explained"
    mock_lecture.source_type = "youtube_captions"
    seg = MagicMock()
    seg.timestamp = "01:20"
    seg.text = "Self-attention matrix computation"
    mock_lecture.segments = [seg]

    with patch("src.tools.video.ingest_video", return_value=mock_lecture):
        with patch("src.tools.video.index_lecture_in_rag", return_value=5):
            res = runner.invoke(app, ["ingest-video", "https://youtube.com/watch?v=mock123"])
            assert res.exit_code == 0
            assert "Transformers Explained" in res.output
            assert "01:20" in res.output
            assert "5 blocks" in res.output
