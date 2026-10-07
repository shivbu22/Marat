"""Unit tests for CLI commands."""

from unittest.mock import patch

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
