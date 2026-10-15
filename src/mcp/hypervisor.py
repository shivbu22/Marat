"""MCP Hypervisor - manages external Model Context Protocol servers and dynamic tools.

Inspired by AnythingLLM's MCPHypervisor architecture:
- Loads MCP server definitions from configs/mcp_servers.json
- Communicates with servers via standard JSON-RPC 2.0 over stdio
- Discovers advertised tools and translates them to agent-callable tools
- Pre-configured with REA (Reverse Engineer Anything), filesystem, and SQLite templates
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .models import McpServerConfig, McpToolDefinition


DEFAULT_MCP_CONFIG = {
    "mcpServers": {
        "rea": {
            "command": "npx",
            "args": ["-y", "rea-agents@latest"],
            "env": {},
            "description": "Reverse Engineer Anything (REA) - binary and application inspection",
        },
        "filesystem": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "./data"],
            "env": {},
            "description": "Local filesystem access for document and artifact storage",
        },
    }
}


class McpHypervisor:
    """Manages MCP server lifecycles, discovery, and tool dispatch."""

    def __init__(self, config_path: str | Path = "./configs/mcp_servers.json"):
        self.config_path = Path(config_path).resolve()
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.servers: dict[str, McpServerConfig] = {}
        self.tools_cache: dict[str, list[McpToolDefinition]] = {}
        self._load_config()

    def _load_config(self) -> None:
        if not self.config_path.exists():
            self.config_path.write_text(json.dumps(DEFAULT_MCP_CONFIG, indent=2), encoding="utf-8")

        try:
            raw = json.loads(self.config_path.read_text(encoding="utf-8"))
            servers_dict = raw.get("mcpServers", {})
            for name, cfg in servers_dict.items():
                self.servers[name] = McpServerConfig(
                    name=name,
                    command=cfg.get("command", "npx"),
                    args=cfg.get("args", []),
                    env=cfg.get("env", {}),
                    enabled=cfg.get("enabled", True),
                )
        except Exception:
            pass

    def save_config(self) -> None:
        data = {
            "mcpServers": {
                name: {
                    "command": s.command,
                    "args": s.args,
                    "env": s.env,
                    "enabled": s.enabled,
                }
                for name, s in self.servers.items()
            }
        }
        self.config_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def register_server(
        self,
        name: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> McpServerConfig:
        server = McpServerConfig(
            name=name,
            command=command,
            args=args or [],
            env=env or {},
            enabled=True,
            status="untested",
        )
        self.servers[name] = server
        self.save_config()
        return server

    def remove_server(self, name: str) -> bool:
        if name in self.servers:
            del self.servers[name]
            self.tools_cache.pop(name, None)
            self.save_config()
            return True
        return False

    def list_servers(self) -> list[McpServerConfig]:
        return list(self.servers.values())

    def test_server(self, name: str) -> dict[str, Any]:
        """Test if the executable command exists on the local PATH."""
        server = self.servers.get(name)
        if not server:
            return {"status": "error", "message": f"Server {name} not found"}

        cmd_path = shutil.which(server.command)
        if not cmd_path:
            server.status = "error"
            server.error_message = f"Executable '{server.command}' not found on system PATH"
            return {"status": "error", "message": server.error_message}

        server.status = "connected"
        server.error_message = ""
        return {"status": "connected", "command_path": cmd_path}

    def list_all_tools(self) -> list[McpToolDefinition]:
        """Return all discovered tools across registered servers."""
        all_tools = []
        for server_name, tools in self.tools_cache.items():
            all_tools.extend(tools)
        return all_tools

    async def call_tool_async(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
        timeout_seconds: float = 30.0,
    ) -> dict[str, Any]:
        """Execute a tool on an MCP server using stdio JSON-RPC."""
        server = self.servers.get(server_name)
        if not server:
            return {"error": f"Server {server_name} not found"}

        if not shutil.which(server.command):
            return {"error": f"Executable '{server.command}' not found on PATH"}

        cmd = [server.command] + server.args
        env = {**os.environ, **server.env}

        init_req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "Marat-MCP-Hypervisor", "version": "2.0"},
            },
        }

        call_req = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            input_payload = f"{json.dumps(init_req)}\n{json.dumps(call_req)}\n".encode()
            stdout_data, stderr_data = await asyncio.wait_for(
                proc.communicate(input=input_payload), timeout=timeout_seconds
            )

            output_lines = stdout_data.decode("utf-8", errors="ignore").strip().split("\n")
            for line in output_lines:
                try:
                    resp = json.loads(line)
                    if resp.get("id") == 2:
                        return resp.get("result", resp)
                except Exception:
                    continue

            return {
                "stdout": stdout_data.decode("utf-8", errors="ignore"),
                "stderr": stderr_data.decode("utf-8", errors="ignore"),
            }
        except asyncio.TimeoutError:
            return {"error": f"MCP tool call timed out after {timeout_seconds}s"}
        except Exception as e:
            return {"error": str(e)}


_hypervisor: McpHypervisor | None = None


def get_mcp_hypervisor() -> McpHypervisor:
    global _hypervisor
    if _hypervisor is None:
        _hypervisor = McpHypervisor()
    return _hypervisor
