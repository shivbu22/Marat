"""Data models for the Reverse Engineering Subsystem (REA)."""

from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class StringMatch(BaseModel):
    offset: int
    value: str
    kind: Literal["ascii", "utf16", "url", "ip", "path", "api_key", "endpoint"] = "ascii"


class SectionInfo(BaseModel):
    name: str
    virtual_address: int
    virtual_size: int
    raw_size: int
    entropy: float = 0.0
    characteristics: list[str] = Field(default_factory=list)
    is_suspicious: bool = False


class ImportEntry(BaseModel):
    library: str
    symbols: list[str] = Field(default_factory=list)


class ExportEntry(BaseModel):
    name: str
    ordinal: int | None = None
    address: int | None = None


class BinaryAnalysisResult(BaseModel):
    file_path: str
    file_name: str
    file_size: int
    format: Literal["PE", "ELF", "MACHO", "ASAR", "APK", "WASM", "GO", "ARCHIVE", "UNKNOWN"]
    architecture: str = "unknown"
    bitness: int = 64
    endianness: str = "little"
    entry_point: int | None = None
    is_packed_or_encrypted: bool = False
    average_entropy: float = 0.0
    md5: str = ""
    sha1: str = ""
    sha256: str = ""
    sections: list[SectionInfo] = Field(default_factory=list)
    imports: list[ImportEntry] = Field(default_factory=list)
    exports: list[ExportEntry] = Field(default_factory=list)
    interesting_strings: list[StringMatch] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    evidence_id: str = ""
    summary: str = ""


class AsarFileEntry(BaseModel):
    path: str
    size: int
    offset: int
    unpacked: bool = False
    is_executable: bool = False


class AsarAnalysisResult(BaseModel):
    archive_path: str
    total_files: int
    total_size: int
    package_json: dict[str, Any] = Field(default_factory=dict)
    entrypoints: list[str] = Field(default_factory=list)
    files: list[AsarFileEntry] = Field(default_factory=list)
    ipc_channels: list[dict[str, Any]] = Field(default_factory=list)
    api_endpoints: list[str] = Field(default_factory=list)
    evidence_id: str = ""
    summary: str = ""


class ApkAnalysisResult(BaseModel):
    package_path: str
    package_name: str = ""
    version_name: str = ""
    version_code: str = ""
    permissions: list[str] = Field(default_factory=list)
    activities: list[str] = Field(default_factory=list)
    services: list[str] = Field(default_factory=list)
    receivers: list[str] = Field(default_factory=list)
    native_libraries: list[str] = Field(default_factory=list)
    dex_classes_count: int = 0
    dex_methods_count: int = 0
    evidence_id: str = ""
    summary: str = ""


class WasmAnalysisResult(BaseModel):
    file_path: str
    version: int = 1
    types_count: int = 0
    imports: list[dict[str, str]] = Field(default_factory=list)
    exports: list[dict[str, str]] = Field(default_factory=list)
    functions_count: int = 0
    tables_count: int = 0
    memories_count: int = 0
    globals_count: int = 0
    evidence_id: str = ""
    summary: str = ""


class GoBuildMetadata(BaseModel):
    file_path: str
    go_version: str = ""
    module_path: str = ""
    dependencies: list[dict[str, str]] = Field(default_factory=list)
    compiler_flags: list[str] = Field(default_factory=list)
    evidence_id: str = ""
    summary: str = ""
