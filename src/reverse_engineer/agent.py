"""Reverse Engineer Agent Node for LangGraph.

Specialized agent responsible for:
- Detecting target artifact type (PE/ELF binary, Electron ASAR, Android APK, WebAssembly, JS bundle)
- Running deep static analysis and feature extraction
- Formulating structured evidence, decompilation insights, and architecture specs
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from langchain_core.messages import SystemMessage, HumanMessage

from ..llm import get_llm
from .binary_analyzer import inspect_binary_file
from .javascript_analyzer import JavaScriptAnalyzer
from .android_analyzer import AndroidAnalyzer
from .wasm_analyzer import WasmAnalyzer
from .go_analyzer import GoAnalyzer


REVERSE_ENGINEER_PROMPT = """You are Mara's Lead Reverse Engineering Specialist within the MARAT Multi-Agent Architecture.

You are examining static reverse engineering evidence extracted from a software target:
Target: {target_name} ({format_type})
Evidence ID: {evidence_id}

Extracted Telemetry & Metrics:
{extracted_summary}

Detailed Data:
{detailed_data}

Task:
Perform a comprehensive architectural decomposition and reverse-engineering assessment.
1. Architecture & Core Subsystems: Explain what this software does and how it is structured internally.
2. Exposed APIs, Protocols, & Communication: Detail discovered routes, endpoints, IPC channels, or exported functions.
3. Obfuscation & Security Profile: Assess entropy, packing, security mitigations, and potential vulnerabilities.
4. Feature Reconstruction Blueprint: Provide a concrete, step-by-step engineering specification for reconstructing or interfacing with this capability.

Keep your response factual, rigorous, and explicitly tied to the evidence provided. Do not hallucinate capabilities not supported by the extracted binary data."""


def run_target_analysis(target_path: str | Path) -> dict[str, Any]:
    """Inspect any file or folder and return normalized reverse engineering results."""
    path = Path(target_path).resolve()
    if not path.exists():
        return {"error": f"Path not found: {target_path}", "format": "UNKNOWN"}

    # Directory analysis
    if path.is_dir():
        js_analyzer = JavaScriptAnalyzer(path)
        data = js_analyzer.analyze_source_tree()
        return {
            "format": "SOURCE_TREE",
            "file_name": path.name,
            "evidence_id": "ev-dir-" + os.urandom(4).hex(),
            "summary": f"Source directory with {data['files_analyzed']} code files, {len(data['api_endpoints'])} endpoints",
            "data": data,
        }

    # File analysis based on extension and magic bytes
    name_lower = path.name.lower()
    raw_header = path.read_bytes()[:16]

    if name_lower.endswith(".asar") or raw_header.startswith(b"\x04\x00\x00\x00"):
        js_analyzer = JavaScriptAnalyzer(path)
        res = js_analyzer.analyze_asar()
        return {
            "format": "ASAR",
            "file_name": path.name,
            "evidence_id": res.evidence_id,
            "summary": res.summary,
            "data": res.model_dump(),
        }
    elif name_lower.endswith(".apk") or (raw_header.startswith(b"PK\x03\x04") and "apk" in name_lower):
        apk_analyzer = AndroidAnalyzer(path)
        res = apk_analyzer.analyze()
        return {
            "format": "APK",
            "file_name": path.name,
            "evidence_id": res.evidence_id,
            "summary": res.summary,
            "data": res.model_dump(),
        }
    elif name_lower.endswith(".wasm") or raw_header.startswith(b"\x00asm"):
        wasm_analyzer = WasmAnalyzer(path)
        res = wasm_analyzer.analyze()
        return {
            "format": "WASM",
            "file_name": path.name,
            "evidence_id": res.evidence_id,
            "summary": res.summary,
            "data": res.model_dump(),
        }
    else:
        # Binary (PE, ELF, Mach-O, or Go binary)
        bin_res = inspect_binary_file(path)
        go_data = {}
        try:
            go_res = GoAnalyzer(path).analyze()
            if go_res.go_version or go_res.module_path:
                go_data = go_res.model_dump()
        except Exception:
            pass

        data = bin_res.model_dump()
        if go_data:
            data["go_metadata"] = go_data

        return {
            "format": bin_res.format,
            "file_name": path.name,
            "evidence_id": bin_res.evidence_id,
            "summary": bin_res.summary,
            "data": data,
        }


def reverse_engineer_node(state: dict[str, Any]) -> dict[str, Any]:
    """LangGraph node for Reverse Engineering."""
    target_path = state.get("target_path", "")
    topic = state.get("topic", "")

    if not target_path:
        return {
            "status": "researching",
            "re_findings": [],
        }

    try:
        inspection = run_target_analysis(target_path)
        if "error" in inspection:
            return {
                "status": "researching",
                "re_findings": [{"claim": f"Reverse engineering analysis failed: {inspection['error']}", "confidence": 0.0}],
            }

        # Synthesize with LLM
        llm = get_llm(temperature=0.1)
        detailed_slice = str(inspection.get("data", {}))[:3000]
        prompt = REVERSE_ENGINEER_PROMPT.format(
            target_name=inspection.get("file_name", target_path),
            format_type=inspection.get("format", "UNKNOWN"),
            evidence_id=inspection.get("evidence_id", "ev-gen"),
            extracted_summary=inspection.get("summary", ""),
            detailed_data=detailed_slice,
        )

        response = llm.invoke([
            SystemMessage(content="You are Mara's technical reverse-engineering co-pilot. Output rigorous technical findings."),
            HumanMessage(content=prompt),
        ])

        analysis_text = getattr(response, "content", str(response))

        finding = {
            "sub_question_id": "sq_re_01",
            "claim": f"Reverse engineering specification for {inspection.get('file_name', target_path)}",
            "evidence": analysis_text,
            "sources": [f"file://{target_path}", f"evidence:{inspection.get('evidence_id', '')}"],
            "confidence": 0.95,
        }

        return {
            "re_findings": [inspection],
            "findings": [finding],
            "status": "fact_checking",
        }
    except Exception as e:
        return {
            "status": "researching",
            "re_findings": [{"error": str(e)}],
        }
