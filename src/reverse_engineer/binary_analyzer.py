"""Binary analyzer for PE, ELF, and Mach-O executables and libraries.

Provides static reverse engineering metrics:
- Format identification (PE32/PE32+, ELF32/ELF64, Mach-O)
- Architecture and endianness
- Section headers, virtual sizing, and Shannon entropy
- Import/Export tables and dynamic symbol extraction
- String harvesting (ASCII, UTF-16LE, URLs, IPs, API endpoints)
- Cryptographic digests (MD5, SHA1, SHA256)
- Packing and obfuscation heuristics
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import struct
import uuid
from pathlib import Path
from typing import Any

from .models import BinaryAnalysisResult, ExportEntry, ImportEntry, SectionInfo, StringMatch


def calculate_entropy(data: bytes) -> float:
    """Calculate Shannon entropy of a byte stream (0.0 to 8.0)."""
    if not data:
        return 0.0
    entropy = 0.0
    length = len(data)
    counts = [0] * 256
    for b in data:
        counts[b] += 1
    for count in counts:
        if count > 0:
            p = count / length
            entropy -= p * math.log2(p)
    return round(entropy, 4)


def extract_strings(data: bytes, min_len: int = 4, max_strings: int = 300) -> list[StringMatch]:
    """Harvest ASCII and UTF-16LE strings and classify interesting indicators."""
    matches: list[StringMatch] = []
    seen = set()

    # Regex patterns for interesting strings
    url_pattern = re.compile(r"https?://[^\s\"'<>]+")
    ip_pattern = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
    endpoint_pattern = re.compile(r"^/[a-zA-Z0-9_\-\./]{3,}$")
    path_pattern = re.compile(r"^[a-zA-Z]:\\[^\s\"'<>]+|/[a-zA-Z0-9_\-]+/[a-zA-Z0-9_\-/]+")

    # 1. ASCII strings
    ascii_re = re.compile(rb"[\x20-\x7E]{" + str(min_len).encode() + rb",}")
    for m in ascii_re.finditer(data):
        raw = m.group(0).decode("ascii", errors="ignore")
        if raw in seen or len(raw) > 300:
            continue
        seen.add(raw)

        kind = "ascii"
        if url_pattern.match(raw):
            kind = "url"
        elif ip_pattern.match(raw):
            kind = "ip"
        elif endpoint_pattern.match(raw):
            kind = "endpoint"
        elif path_pattern.match(raw):
            kind = "path"

        matches.append(StringMatch(offset=m.start(), value=raw, kind=kind))
        if len(matches) >= max_strings:
            return matches

    # 2. UTF-16LE strings
    utf16_re = re.compile(rb"(?:[\x20-\x7E]\x00){" + str(min_len).encode() + rb",}")
    for m in utf16_re.finditer(data):
        try:
            raw = m.group(0).decode("utf-16le", errors="ignore")
            if raw in seen or len(raw) > 300:
                continue
            seen.add(raw)
            kind = "utf16"
            if url_pattern.match(raw):
                kind = "url"
            elif endpoint_pattern.match(raw):
                kind = "endpoint"
            matches.append(StringMatch(offset=m.start(), value=raw, kind=kind))
            if len(matches) >= max_strings:
                return matches
        except Exception:
            continue

    return matches


class BinaryAnalyzer:
    """Multi-format static binary analysis engine."""

    def __init__(self, file_path: str | Path):
        self.path = Path(file_path).resolve()
        if not self.path.exists():
            raise FileNotFoundError(f"Binary target not found: {self.path}")
        self.raw_data = self.path.read_bytes()
        self.size = len(self.raw_data)

    def compute_hashes(self) -> tuple[str, str, str]:
        md5 = hashlib.md5(self.raw_data).hexdigest()
        sha1 = hashlib.sha1(self.raw_data).hexdigest()
        sha256 = hashlib.sha256(self.raw_data).hexdigest()
        return md5, sha1, sha256

    def analyze(self) -> BinaryAnalysisResult:
        md5, sha1, sha256 = self.compute_hashes()
        avg_entropy = calculate_entropy(self.raw_data)

        # Detect format by magic bytes
        if self.raw_data.startswith(b"MZ"):
            result = self._analyze_pe()
        elif self.raw_data.startswith(b"\x7fELF"):
            result = self._analyze_elf()
        elif self.raw_data.startswith((b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe")):
            result = self._analyze_macho()
        elif self.raw_data.startswith(b"\x00asm"):
            result = self._analyze_wasm_raw()
        else:
            result = BinaryAnalysisResult(
                file_path=str(self.path),
                file_name=self.path.name,
                file_size=self.size,
                format="UNKNOWN",
                average_entropy=avg_entropy,
                md5=md5,
                sha1=sha1,
                sha256=sha256,
            )

        # Set hashes and global metrics
        result.md5 = md5
        result.sha1 = sha1
        result.sha256 = sha256
        result.average_entropy = avg_entropy
        result.is_packed_or_encrypted = avg_entropy > 7.1

        # Extract strings
        result.interesting_strings = extract_strings(self.raw_data, min_len=5, max_strings=150)
        result.evidence_id = f"ev-bin-{uuid.uuid4().hex[:8]}"

        # Generate summary
        sections_desc = f"{len(result.sections)} sections" if result.sections else "no section table"
        packing_desc = "POTENTIALLY PACKED/ENCRYPTED" if result.is_packed_or_encrypted else "standard entropy"
        result.summary = (
            f"{result.format} {result.architecture} ({result.bitness}-bit) | "
            f"Size: {result.file_size:,} bytes | Entropy: {result.average_entropy:.2f} ({packing_desc}) | "
            f"{sections_desc} | {len(result.imports)} import libs | {len(result.exports)} exports."
        )
        return result

    def _analyze_pe(self) -> BinaryAnalysisResult:
        """Parse PE header, Optional header, sections, and imports."""
        data = self.raw_data
        sections: list[SectionInfo] = []
        imports: list[ImportEntry] = []
        exports: list[ExportEntry] = []
        arch = "x86"
        bitness = 32
        entry_point = None

        try:
            e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
            if e_lfanew + 4 < len(data) and data[e_lfanew : e_lfanew + 4] == b"PE\x00\x00":
                machine = struct.unpack_from("<H", data, e_lfanew + 4)[0]
                num_sections = struct.unpack_from("<H", data, e_lfanew + 6)[0]
                opt_header_size = struct.unpack_from("<H", data, e_lfanew + 20)[0]

                if machine == 0x8664:
                    arch = "x86_64 (AMD64)"
                    bitness = 64
                elif machine == 0x14C:
                    arch = "i386 (x86)"
                    bitness = 32
                elif machine == 0xAA64:
                    arch = "ARM64"
                    bitness = 64

                # Optional header magic
                opt_offset = e_lfanew + 24
                if opt_offset + 2 <= len(data):
                    opt_magic = struct.unpack_from("<H", data, opt_offset)[0]
                    if opt_magic == 0x20B:  # PE32+ (64-bit)
                        bitness = 64
                    entry_point = struct.unpack_from("<I", data, opt_offset + 16)[0]

                # Section headers
                sec_offset = opt_offset + opt_header_size
                for i in range(min(num_sections, 64)):
                    off = sec_offset + (i * 40)
                    if off + 40 > len(data):
                        break
                    sec_name_bytes = data[off : off + 8].split(b"\x00")[0]
                    sec_name = sec_name_bytes.decode("ascii", errors="replace").strip()
                    vsize = struct.unpack_from("<I", data, off + 8)[0]
                    vaddr = struct.unpack_from("<I", data, off + 12)[0]
                    rsize = struct.unpack_from("<I", data, off + 16)[0]
                    roff = struct.unpack_from("<I", data, off + 20)[0]
                    chars = struct.unpack_from("<I", data, off + 36)[0]

                    # Slice raw section data for entropy
                    sec_data = data[roff : roff + rsize] if roff + rsize <= len(data) else b""
                    sec_entropy = calculate_entropy(sec_data)

                    char_flags = []
                    if chars & 0x20000000:
                        char_flags.append("EXEC")
                    if chars & 0x40000000:
                        char_flags.append("READ")
                    if chars & 0x80000000:
                        char_flags.append("WRITE")

                    suspicious = sec_entropy > 7.2 or sec_name in [".upx0", ".upx1", ".themida", ".vmp"]
                    sections.append(
                        SectionInfo(
                            name=sec_name,
                            virtual_address=vaddr,
                            virtual_size=vsize,
                            raw_size=rsize,
                            entropy=sec_entropy,
                            characteristics=char_flags,
                            is_suspicious=suspicious,
                        )
                    )

                # Search for imported DLL names via simple ASCII string scanning
                dll_re = re.compile(rb"([a-zA-Z0-9_\-\.]+\.(?:dll|DLL))")
                found_dlls = set()
                for m in dll_re.finditer(data):
                    dll_name = m.group(1).decode("ascii", errors="ignore")
                    if dll_name not in found_dlls and len(dll_name) < 40:
                        found_dlls.add(dll_name)
                        imports.append(ImportEntry(library=dll_name, symbols=[]))
        except Exception:
            pass

        return BinaryAnalysisResult(
            file_path=str(self.path),
            file_name=self.path.name,
            file_size=self.size,
            format="PE",
            architecture=arch,
            bitness=bitness,
            entry_point=entry_point,
            sections=sections,
            imports=imports[:30],
            exports=exports,
        )

    def _analyze_elf(self) -> BinaryAnalysisResult:
        """Parse ELF header and sections."""
        data = self.raw_data
        sections: list[SectionInfo] = []
        imports: list[ImportEntry] = []
        arch = "unknown"
        bitness = 64 if data[4] == 2 else 32
        endian = "little" if data[5] == 1 else "big"
        fmt = "<" if endian == "little" else ">"
        entry_point = None

        try:
            machine_code = struct.unpack_from(f"{fmt}H", data, 0x12)[0]
            arch_map = {0x03: "x86 (i386)", 0x3E: "x86_64 (AMD64)", 0x28: "ARM", 0xB7: "AArch64 (ARM64)", 0xF3: "RISC-V"}
            arch = arch_map.get(machine_code, f"Machine 0x{machine_code:X}")

            if bitness == 64:
                entry_point = struct.unpack_from(f"{fmt}Q", data, 0x18)[0]
                shoff = struct.unpack_from(f"{fmt}Q", data, 0x28)[0]
                shentsize = struct.unpack_from(f"{fmt}H", data, 0x3A)[0]
                shnum = struct.unpack_from(f"{fmt}H", data, 0x3C)[0]
                shstrndx = struct.unpack_from(f"{fmt}H", data, 0x3E)[0]
            else:
                entry_point = struct.unpack_from(f"{fmt}I", data, 0x18)[0]
                shoff = struct.unpack_from(f"{fmt}I", data, 0x20)[0]
                shentsize = struct.unpack_from(f"{fmt}H", data, 0x2E)[0]
                shnum = struct.unpack_from(f"{fmt}H", data, 0x30)[0]
                shstrndx = struct.unpack_from(f"{fmt}H", data, 0x32)[0]

            # Read section headers if available
            if shoff > 0 and shnum > 0 and shoff + (shnum * shentsize) <= len(data):
                # String table section
                strtab_off = shoff + (shstrndx * shentsize)
                if bitness == 64:
                    strtab_offset = struct.unpack_from(f"{fmt}Q", data, strtab_off + 24)[0]
                    strtab_size = struct.unpack_from(f"{fmt}Q", data, strtab_off + 32)[0]
                else:
                    strtab_offset = struct.unpack_from(f"{fmt}I", data, strtab_off + 16)[0]
                    strtab_size = struct.unpack_from(f"{fmt}I", data, strtab_off + 20)[0]
                strtab_data = data[strtab_offset : strtab_offset + strtab_size]

                for i in range(min(shnum, 64)):
                    entry_off = shoff + (i * shentsize)
                    name_idx = struct.unpack_from(f"{fmt}I", data, entry_off)[0]
                    sec_name = "unknown"
                    if name_idx < len(strtab_data):
                        sec_name = strtab_data[name_idx:].split(b"\x00")[0].decode("ascii", errors="replace")

                    if bitness == 64:
                        vaddr = struct.unpack_from(f"{fmt}Q", data, entry_off + 16)[0]
                        offset = struct.unpack_from(f"{fmt}Q", data, entry_off + 24)[0]
                        size = struct.unpack_from(f"{fmt}Q", data, entry_off + 32)[0]
                    else:
                        vaddr = struct.unpack_from(f"{fmt}I", data, entry_off + 12)[0]
                        offset = struct.unpack_from(f"{fmt}I", data, entry_off + 16)[0]
                        size = struct.unpack_from(f"{fmt}I", data, entry_off + 20)[0]

                    sec_bytes = data[offset : offset + size] if offset + size <= len(data) else b""
                    sec_entropy = calculate_entropy(sec_bytes)
                    sections.append(
                        SectionInfo(
                            name=sec_name,
                            virtual_address=vaddr,
                            virtual_size=size,
                            raw_size=size,
                            entropy=sec_entropy,
                        )
                    )

            # Discover referenced shared objects (.so)
            so_re = re.compile(rb"([a-zA-Z0-9_\-\.]+\.so(?:\.[0-9]+)*)")
            found_so = set()
            for m in so_re.finditer(data):
                so_name = m.group(1).decode("ascii", errors="ignore")
                if so_name not in found_so and len(so_name) < 40:
                    found_so.add(so_name)
                    imports.append(ImportEntry(library=so_name, symbols=[]))
        except Exception:
            pass

        return BinaryAnalysisResult(
            file_path=str(self.path),
            file_name=self.path.name,
            file_size=self.size,
            format="ELF",
            architecture=arch,
            bitness=bitness,
            endianness=endian,
            entry_point=entry_point,
            sections=sections,
            imports=imports[:30],
        )

    def _analyze_macho(self) -> BinaryAnalysisResult:
        """Parse Mach-O header."""
        data = self.raw_data
        magic = data[:4]
        bitness = 64 if magic in (b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe") else 32
        arch = "ARM64 / x86_64" if bitness == 64 else "x86 / ARM"
        return BinaryAnalysisResult(
            file_path=str(self.path),
            file_name=self.path.name,
            file_size=self.size,
            format="MACHO",
            architecture=arch,
            bitness=bitness,
        )

    def _analyze_wasm_raw(self) -> BinaryAnalysisResult:
        return BinaryAnalysisResult(
            file_path=str(self.path),
            file_name=self.path.name,
            file_size=self.size,
            format="WASM",
            architecture="WebAssembly",
            bitness=32,
        )


def inspect_binary_file(file_path: str | Path) -> BinaryAnalysisResult:
    """Convenience helper to inspect any binary file."""
    analyzer = BinaryAnalyzer(file_path)
    return analyzer.analyze()
