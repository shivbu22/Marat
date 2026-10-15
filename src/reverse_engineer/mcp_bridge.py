"""Bridge to REA (Reverse Engineer Anything) MCP Server & CLI.

Enables invocation of upstream `rea-agents` or `morluto/rea` tools
via standard Model Context Protocol (stdio transport) or direct CLI.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


class ReaMcpBridge:
    """Bridge for connecting to upstream `rea-agents` MCP server."""

    def __init__(self, command: str = "npx", args: list[str] | None = None):
        self.command = command
        self.args = args or ["-y", "rea-agents@latest"]
        self.is_available = shutil.which(self.command) is not None

    def execute_rea_cli(self, subcmd: str, target: str, extra_args: list[str] | None = None) -> dict[str, Any]:
        """Execute a one-shot rea-agents CLI command with JSON output."""
        if not self.is_available:
            return {"error": "Node.js / npx not installed on system PATH"}

        cmd = [self.command] + self.args + [subcmd, target, "--json"]
        if extra_args:
            cmd.extend(extra_args)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            stdout = result.stdout.strip()
            if stdout:
                try:
                    return json.loads(stdout)
                except Exception:
                    return {"stdout": stdout, "stderr": result.stderr}
            return {"stderr": result.stderr, "exit_code": result.returncode}
        except Exception as e:
            return {"error": str(e)}

    async def execute_rea_cli_async(self, subcmd: str, target: str) -> dict[str, Any]:
        """Async variant of REA CLI execution."""
        return await asyncio.to_thread(self.execute_rea_cli, subcmd, target)
