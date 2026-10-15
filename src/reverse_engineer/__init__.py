"""Reverse Engineering and Binary Analysis Subsystem."""

from .binary_analyzer import BinaryAnalyzer, calculate_entropy, extract_strings, inspect_binary_file
from .javascript_analyzer import AsarArchive, JavaScriptAnalyzer
from .android_analyzer import AndroidAnalyzer
from .wasm_analyzer import WasmAnalyzer
from .go_analyzer import GoAnalyzer
from .mcp_bridge import ReaMcpBridge
from .agent import reverse_engineer_node, run_target_analysis
from .models import (
    ApkAnalysisResult,
    AsarAnalysisResult,
    BinaryAnalysisResult,
    GoBuildMetadata,
    WasmAnalysisResult,
)

__all__ = [
    "BinaryAnalyzer",
    "calculate_entropy",
    "extract_strings",
    "inspect_binary_file",
    "AsarArchive",
    "JavaScriptAnalyzer",
    "AndroidAnalyzer",
    "WasmAnalyzer",
    "GoAnalyzer",
    "ReaMcpBridge",
    "reverse_engineer_node",
    "run_target_analysis",
    "ApkAnalysisResult",
    "AsarAnalysisResult",
    "BinaryAnalysisResult",
    "GoBuildMetadata",
    "WasmAnalysisResult",
]
