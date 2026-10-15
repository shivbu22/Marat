"""Unit tests for the MCP Hypervisor."""

from pathlib import Path

from src.mcp.hypervisor import McpHypervisor


def test_mcp_hypervisor_lifecycle(tmp_path: Path):
    cfg_file = tmp_path / "mcp_servers.json"
    hyp = McpHypervisor(config_path=cfg_file)

    # Initially has default config
    servers = hyp.list_servers()
    assert len(servers) >= 2
    assert any(s.name == "rea" for s in servers)

    # Register custom server
    custom = hyp.register_server(
        name="custom_sqlite",
        command="python",
        args=["-m", "sqlite3"],
    )
    assert custom.name == "custom_sqlite"
    assert hyp.test_server("custom_sqlite")["status"] == "connected"

    # Remove server
    assert hyp.remove_server("custom_sqlite") is True
    assert hyp.remove_server("nonexistent") is False
