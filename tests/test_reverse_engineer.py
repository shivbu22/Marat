"""Unit tests for the Reverse Engineering Subsystem (REA)."""

import struct
from pathlib import Path

from src.reverse_engineer.binary_analyzer import calculate_entropy, extract_strings, inspect_binary_file
from src.reverse_engineer.javascript_analyzer import AsarArchive
from src.reverse_engineer.wasm_analyzer import WasmAnalyzer
from src.reverse_engineer.go_analyzer import GoAnalyzer
from src.reverse_engineer.agent import run_target_analysis


def test_calculate_entropy():
    # Constant data has 0 entropy
    assert calculate_entropy(b"\x00" * 100) == 0.0
    # Random-like or uniform bytes have high entropy (up to 8.0)
    uniform = bytes(range(256))
    assert calculate_entropy(uniform) == 8.0


def test_extract_strings():
    sample = b"SomeHeader\x00https://api.example.com/v1\x00192.168.1.1\x00short\x00"
    matches = extract_strings(sample, min_len=4)
    values = [m.value for m in matches]
    assert "https://api.example.com/v1" in values
    assert "192.168.1.1" in values
    assert "SomeHeader" in values


def test_synthetic_pe_analysis(tmp_path: Path):
    # Construct a minimal valid PE header
    pe_file = tmp_path / "test.exe"
    data = bytearray(1024)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)  # e_lfanew = 0x80
    data[0x80:0x84] = b"PE\x00\x00"
    struct.pack_into("<H", data, 0x84, 0x8664)  # machine = x86_64
    struct.pack_into("<H", data, 0x86, 1)  # 1 section
    struct.pack_into("<H", data, 0x94, 240)  # opt header size

    # Optional header magic
    struct.pack_into("<H", data, 0x80 + 24, 0x20B)  # PE32+ (64-bit)

    # Section header (.text)
    sec_offset = 0x80 + 24 + 240
    data[sec_offset : sec_offset + 5] = b".text"
    struct.pack_into("<I", data, sec_offset + 8, 100)  # vsize
    struct.pack_into("<I", data, sec_offset + 12, 0x1000)  # vaddr
    struct.pack_into("<I", data, sec_offset + 16, 100)  # rsize
    struct.pack_into("<I", data, sec_offset + 20, 500)  # roff
    struct.pack_into("<I", data, sec_offset + 36, 0x60000020)  # chars

    # Add dummy import string
    data[600:614] = b"KERNEL32.dll\x00\x00"
    pe_file.write_bytes(bytes(data))

    res = inspect_binary_file(pe_file)
    assert res.format == "PE"
    assert res.bitness == 64
    assert len(res.sections) == 1
    assert res.sections[0].name == ".text"
    assert any(imp.library.lower() == "kernel32.dll" for imp in res.imports)


def test_synthetic_wasm_analysis(tmp_path: Path):
    wasm_file = tmp_path / "test.wasm"
    # WASM header: \x00asm \x01\x00\x00\x00
    data = bytearray(b"\x00asm\x01\x00\x00\x00")
    # Section 1: Type section (id=1, len=4, count=1, func type)
    data.extend([1, 4, 1, 0x60, 0, 0])
    wasm_file.write_bytes(bytes(data))

    analyzer = WasmAnalyzer(wasm_file)
    res = analyzer.analyze()
    assert res.version == 1
    assert res.types_count == 1


def test_run_target_analysis_on_directory(tmp_path: Path):
    # Test directory inspection
    src_dir = tmp_path / "app"
    src_dir.mkdir()
    (src_dir / "api.js").write_text("fetch('/api/v2/users'); localStorage.setItem('token', 'xyz');", encoding="utf-8")

    res = run_target_analysis(src_dir)
    assert res["format"] == "SOURCE_TREE"
    assert "/api/v2/users" in res["data"]["api_endpoints"]
    assert "token" in res["data"]["storage_keys"]
