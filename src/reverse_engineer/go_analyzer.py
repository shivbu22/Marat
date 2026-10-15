"""Go Binary Reverse Engineering Engine.

Extracts embedded Go runtime build info:
- Go compiler version (e.g. go1.22.4)
- Main module path
- Direct and indirect module dependencies with exact versions
- Build tags and compiler flags
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

from .models import GoBuildMetadata


class GoAnalyzer:
    """Extractor for Go compiler and build metadata."""

    def __init__(self, binary_path: str | Path):
        self.path = Path(binary_path).resolve()
        if not self.path.exists():
            raise FileNotFoundError(f"Binary file not found: {self.path}")
        self.data = self.path.read_bytes()

    def analyze(self) -> GoBuildMetadata:
        go_version = ""
        module_path = ""
        dependencies: list[dict[str, str]] = []
        flags: list[str] = []

        # 1. Search for Go version string (e.g. "go1.21.3", "go1.22.0")
        ver_match = re.search(rb"go1\.[0-9]+(?:\.[0-9]+)?", self.data)
        if ver_match:
            go_version = ver_match.group(0).decode("ascii", errors="ignore")

        # 2. Search for buildinfo/modinfo signature
        # Go buildinfo starts with \xff Go buildinf:
        mod_sig = b"\xff Go buildinf:"
        sig_idx = self.data.find(mod_sig)
        if sig_idx != -1:
            # Module info is stored in nearby data
            chunk = self.data[sig_idx : min(sig_idx + 8192, len(self.data))]
            lines = chunk.split(b"\n")
            for line in lines:
                s = line.decode("utf-8", errors="ignore").strip()
                if s.startswith("path\t"):
                    module_path = s.split("\t", 1)[1]
                elif s.startswith("mod\t") or s.startswith("dep\t"):
                    parts = s.split("\t")
                    if len(parts) >= 3:
                        dependencies.append({"path": parts[1], "version": parts[2]})
                elif s.startswith("build\t"):
                    flags.append(s.split("\t", 1)[1])

        evidence_id = f"ev-go-{uuid.uuid4().hex[:8]}"
        summary = (
            f"Go Binary: Compiler {go_version or 'unknown'} | "
            f"Module: {module_path or 'unknown'} | "
            f"Dependencies: {len(dependencies)} | Build settings: {len(flags)}"
        )

        return GoBuildMetadata(
            file_path=str(self.path),
            go_version=go_version,
            module_path=module_path,
            dependencies=dependencies,
            compiler_flags=flags,
            evidence_id=evidence_id,
            summary=summary,
        )
