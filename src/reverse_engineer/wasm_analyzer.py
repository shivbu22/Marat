"""WebAssembly (.wasm) Binary Reverse Engineering Engine.

Decodes:
- WASM binary magic (\x00asm) and version
- Section headers (Type, Import, Function, Table, Memory, Global, Export, Code, Data)
- Exported and imported symbols, memory limits, and function signatures
"""

from __future__ import annotations

import struct
import uuid
from pathlib import Path
from typing import Any

from .models import WasmAnalysisResult


class WasmAnalyzer:
    """Static parser for WebAssembly binaries."""

    SECTION_NAMES = {
        0: "Custom",
        1: "Type",
        2: "Import",
        3: "Function",
        4: "Table",
        5: "Memory",
        6: "Global",
        7: "Export",
        8: "Start",
        9: "Element",
        10: "Code",
        11: "Data",
        12: "DataCount",
    }

    def __init__(self, wasm_path: str | Path):
        self.path = Path(wasm_path).resolve()
        if not self.path.exists():
            raise FileNotFoundError(f"WASM file not found: {self.path}")
        self.data = self.path.read_bytes()

    def analyze(self) -> WasmAnalysisResult:
        if len(self.data) < 8 or not self.data.startswith(b"\x00asm"):
            raise ValueError("Not a valid WebAssembly binary module")

        version = struct.unpack_from("<I", self.data, 4)[0]
        offset = 8
        types_count = 0
        functions_count = 0
        tables_count = 0
        memories_count = 0
        globals_count = 0
        imports: list[dict[str, str]] = []
        exports: list[dict[str, str]] = []

        def _read_leb128_u(curr_off: int) -> tuple[int, int]:
            result = 0
            shift = 0
            while curr_off < len(self.data):
                byte = self.data[curr_off]
                curr_off += 1
                result |= (byte & 0x7F) << shift
                if not (byte & 0x80):
                    break
                shift += 7
            return result, curr_off

        def _read_string(curr_off: int) -> tuple[str, int]:
            s_len, curr_off = _read_leb128_u(curr_off)
            s_bytes = self.data[curr_off : curr_off + s_len]
            curr_off += s_len
            return s_bytes.decode("utf-8", errors="replace"), curr_off

        while offset < len(self.data):
            sec_id = self.data[offset]
            offset += 1
            sec_len, offset = _read_leb128_u(offset)
            sec_end = offset + sec_len

            if sec_id == 1:  # Type
                count, p = _read_leb128_u(offset)
                types_count = count
            elif sec_id == 2:  # Import
                try:
                    count, p = _read_leb128_u(offset)
                    for _ in range(min(count, 50)):
                        if p >= sec_end:
                            break
                        mod_name, p = _read_string(p)
                        field_name, p = _read_string(p)
                        kind = self.data[p] if p < sec_end else 0
                        p += 1
                        kind_str = {0: "func", 1: "table", 2: "memory", 3: "global"}.get(kind, "other")
                        imports.append({"module": mod_name, "field": field_name, "kind": kind_str})
                        p += 1  # skip type index / limits
                except Exception:
                    pass
            elif sec_id == 3:  # Function
                count, p = _read_leb128_u(offset)
                functions_count = count
            elif sec_id == 4:  # Table
                count, p = _read_leb128_u(offset)
                tables_count = count
            elif sec_id == 5:  # Memory
                count, p = _read_leb128_u(offset)
                memories_count = count
            elif sec_id == 6:  # Global
                count, p = _read_leb128_u(offset)
                globals_count = count
            elif sec_id == 7:  # Export
                try:
                    count, p = _read_leb128_u(offset)
                    for _ in range(min(count, 50)):
                        if p >= sec_end:
                            break
                        name, p = _read_string(p)
                        kind = self.data[p] if p < sec_end else 0
                        p += 1
                        _, p = _read_leb128_u(p)
                        kind_str = {0: "func", 1: "table", 2: "memory", 3: "global"}.get(kind, "other")
                        exports.append({"name": name, "kind": kind_str})
                except Exception:
                    pass

            offset = sec_end

        evidence_id = f"ev-wasm-{uuid.uuid4().hex[:8]}"
        summary = (
            f"WASM Module v{version} | Types: {types_count} | Functions: {functions_count} | "
            f"Imports: {len(imports)} | Exports: {len(exports)} | Memories: {memories_count}"
        )

        return WasmAnalysisResult(
            file_path=str(self.path),
            version=version,
            types_count=types_count,
            imports=imports,
            exports=exports,
            functions_count=functions_count,
            tables_count=tables_count,
            memories_count=memories_count,
            globals_count=globals_count,
            evidence_id=evidence_id,
            summary=summary,
        )
