"""MARAT Document Collector engine.

Parses diverse data formats:
- Plain text & Markdown (.txt, .md, .rst)
- Code files (.py, .js, .ts, .html, .css, .json, .yaml, .c, .cpp, .go, .rs, .sql)
- PDF documents (built-in extraction)
- CSV / TSV tabular files
- Live Web URLs (Trafilatura / BeautifulSoup)
- Reverse engineering artifact summaries
"""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import Any

from langchain_text_splitters import RecursiveCharacterTextSplitter


class DocumentCollector:
    """Multi-format document parsing and chunking engine."""

    def __init__(self, chunk_size: int = 800, chunk_overlap: int = 120):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", " ", ""],
        )

    def extract_text(self, file_path: str | Path, content_bytes: bytes | None = None) -> tuple[str, str]:
        """Extract plain text and determine file type."""
        path = Path(file_path)
        ext = path.suffix.lower().lstrip(".")
        data = content_bytes if content_bytes is not None else path.read_bytes()

        if ext in ["txt", "md", "markdown", "rst"]:
            return data.decode("utf-8", errors="replace"), ext
        elif ext in ["py", "js", "ts", "tsx", "jsx", "html", "css", "json", "yaml", "yml", "c", "cpp", "h", "go", "rs", "sql"]:
            return data.decode("utf-8", errors="replace"), "code"
        elif ext == "csv":
            return self._parse_csv(data), "csv"
        elif ext == "pdf":
            return self._parse_pdf(data), "pdf"
        else:
            # Fallback text decoding
            try:
                text = data.decode("utf-8")
                return text, "text"
            except Exception:
                return data.decode("latin-1", errors="replace"), "binary_text"

    def _parse_csv(self, data: bytes) -> str:
        """Convert CSV rows to readable narrative blocks."""
        text = data.decode("utf-8", errors="replace")
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        if not rows:
            return ""
        header = rows[0]
        output = [f"Table with columns: {', '.join(header)}"]
        for row in rows[1:500]:
            items = [f"{header[i]}: {val}" for i, val in enumerate(row) if i < len(header)]
            output.append(" | ".join(items))
        return "\n".join(output)

    def _parse_pdf(self, data: bytes) -> str:
        """Extract text from PDF using basic stream parsing."""
        text_parts = []
        # Extract text within BT ... ET blocks or FlateDecode streams
        stream_re = re.compile(rb"stream[\r\n]+(.*?)[\r\n]+endstream", re.DOTALL)
        for match in stream_re.finditer(data):
            stream_data = match.group(1)
            # Try decompressing with zlib
            decompressed = None
            try:
                import zlib
                decompressed = zlib.decompress(stream_data)
            except Exception:
                pass

            target = decompressed or stream_data
            # Extract parenthesized strings: (Hello World) Tj
            strings = re.findall(rb"\((.*?)\)\s*T[jJ]", target)
            for s in strings:
                try:
                    text_parts.append(s.decode("utf-8", errors="ignore"))
                except Exception:
                    pass

        extracted = " ".join(text_parts).strip()
        if extracted:
            return extracted
        # Fallback raw ASCII
        clean_ascii = re.sub(rb"[^\x20-\x7E\n]", rb" ", data)
        return clean_ascii.decode("ascii", errors="ignore")[:50000]

    def chunk_document(self, text: str, metadata: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Split extracted text into semantic chunks ready for vector storage."""
        if not text.strip():
            return []
        chunks = self.splitter.split_text(text)
        base_meta = metadata or {}
        return [
            {
                "text": chunk,
                "metadata": {**base_meta, "chunk_index": idx, "chunk_total": len(chunks)},
            }
            for idx, chunk in enumerate(chunks)
        ]
