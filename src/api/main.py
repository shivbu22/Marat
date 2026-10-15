"""FastAPI server for the upgraded MARAT Multi-Agent Intelligence & Reverse Engineering Platform."""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from ..config import get_settings
from ..graph.workflow import get_graph
from ..mcp.hypervisor import get_mcp_hypervisor
from ..reverse_engineer.agent import run_target_analysis
from ..workspaces.manager import get_workspace_manager
from ..rag.store import get_rag

app = FastAPI(
    title="MARAT — Multi-Agent Research Assistant Technology",
    description="Autonomous multi-agent research and reverse-engineering platform featuring Mara 🐾. Decomposes binaries, analyzes codebases, investigates web literature, fact-checks claims, and orchestrates MCP tools.",
    version="2.0.0",
)

s = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=s.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request & Response Schemas
# ---------------------------------------------------------------------------
class ResearchRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=1000)
    focus_mode: str = Field(default="broad", pattern="^(broad|deep|verify|reverse_engineer)$")
    video_url: str = Field(default="", description="Optional lecture video URL or audio recording path")
    target_path: str = Field(default="", description="Optional binary, ASAR, APK, WASM, or code path to reverse-engineer")
    workspace_id: str = Field(default="default", description="Workspace ID for isolated memory")
    stream: bool = False


class VideoIngestRequest(BaseModel):
    source: str = Field(..., description="YouTube URL or local audio/video file path")
    title: str = Field(default="", description="Optional title for lecture")


class VideoIngestResponse(BaseModel):
    title: str
    url: str
    source_type: str
    segments_count: int
    indexed_chunks: int


class ResearchResponse(BaseModel):
    topic: str
    status: str
    final_report: str
    sub_questions: list
    findings_count: int
    re_findings_count: int = 0
    fact_checks: list
    sources: list
    review_count: int
    elapsed_seconds: float


class ReverseEngineerRequest(BaseModel):
    target_path: str = Field(..., description="Path to binary, ASAR, APK, WASM, or source code directory")
    workspace_id: str = Field(default="default")


class WorkspaceCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    slug: str | None = None
    description: str = ""
    system_prompt: str = ""
    temperature: float = 0.2


class McpServerRegisterRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)


class McpToolCallRequest(BaseModel):
    server_name: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


STATIC_INDEX = Path(__file__).parent / "static" / "index.html"


# ---------------------------------------------------------------------------
# Core UI & Status
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the MARAT web dashboard."""
    if STATIC_INDEX.exists():
        return HTMLResponse(content=STATIC_INDEX.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>MARAT API is running</h1><p>Visit <a href='/docs'>/docs</a> for Swagger UI.</p>")


@app.get("/health")
async def health():
    return {"status": "ok", "provider": s.llm_provider, "model": s.llm_model, "version": "2.0.0"}


@app.get("/system/status")
async def system_status():
    rag = get_rag()
    ws_mgr = get_workspace_manager()
    mcp_hyp = get_mcp_hypervisor()
    return {
        "status": "ok",
        "provider": s.llm_provider,
        "model": s.llm_model,
        "rag_enabled": s.rag_enabled,
        "vault_documents": rag.count(),
        "workspaces_count": len(ws_mgr.list_workspaces()),
        "mcp_servers_count": len(mcp_hyp.list_servers()),
        "capabilities": [
            "deep_research",
            "video_rag_whisper",
            "reverse_engineer_anything",
            "asar_electron_unpack",
            "pe_elf_binary_analysis",
            "apk_analysis",
            "wasm_decoding",
            "workspaces_vault",
            "mcp_hypervisor",
        ],
    }


@app.get("/rag/query")
async def query_rag(q: str = ""):
    rag = get_rag()
    results = rag.search(q, k=5)
    return {"query": q, "count": len(results), "results": results}


# ---------------------------------------------------------------------------
# Workspaces Endpoints (AnythingLLM Feature)
# ---------------------------------------------------------------------------
@app.get("/api/workspaces")
async def list_workspaces():
    mgr = get_workspace_manager()
    return mgr.list_workspaces()


@app.post("/api/workspaces")
async def create_workspace(req: WorkspaceCreateRequest):
    mgr = get_workspace_manager()
    ws = mgr.create_workspace(
        name=req.name,
        slug=req.slug,
        description=req.description,
        system_prompt=req.system_prompt,
        temperature=req.temperature,
    )
    return ws


@app.get("/api/workspaces/{workspace_id}")
async def get_workspace(workspace_id: str):
    mgr = get_workspace_manager()
    ws = mgr.get_workspace(workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws


@app.delete("/api/workspaces/{workspace_id}")
async def delete_workspace(workspace_id: str):
    mgr = get_workspace_manager()
    success = mgr.delete_workspace(workspace_id)
    if not success:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return {"status": "deleted", "id": workspace_id}


@app.get("/api/workspaces/{workspace_id}/documents")
async def list_workspace_documents(workspace_id: str):
    mgr = get_workspace_manager()
    return mgr.list_documents(workspace_id)


@app.post("/api/workspaces/{workspace_id}/upload")
async def upload_document(workspace_id: str, file: UploadFile = File(...)):
    mgr = get_workspace_manager()
    rag = get_rag()
    ws = mgr.get_workspace(workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    content = await file.read()
    doc, chunks = mgr.add_document(workspace_id, file.filename, content)
    # Ingest chunks into workspace vector collection
    rag.add_chunks(chunks, collection_name=ws.vector_collection)

    return {
        "status": "success",
        "document": doc,
        "indexed_chunks": len(chunks),
    }


# ---------------------------------------------------------------------------
# Reverse Engineering Workbench (/reverse-engineer-anything)
# ---------------------------------------------------------------------------
@app.post("/api/reverse-engineer/analyze")
async def analyze_target(req: ReverseEngineerRequest):
    """Run full reverse-engineering analysis on a local path or uploaded artifact."""
    result = run_target_analysis(req.target_path)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    # Automatically store summary in workspace RAG if requested
    if req.workspace_id:
        try:
            mgr = get_workspace_manager()
            rag = get_rag()
            ws = mgr.get_workspace(req.workspace_id)
            if ws:
                summary_text = (
                    f"Reverse Engineering Dossier for {result.get('file_name', req.target_path)}:\n"
                    f"Format: {result.get('format')}\n"
                    f"Summary: {result.get('summary')}\n"
                    f"Evidence: {json.dumps(result.get('data', {}))[:2000]}"
                )
                doc, chunks = mgr.add_document(
                    req.workspace_id,
                    f"RE_{Path(req.target_path).name}.txt",
                    summary_text.encode("utf-8"),
                    extra_metadata={"type": "reverse_engineering_artifact"},
                )
                rag.add_chunks(chunks, collection_name=ws.vector_collection)
        except Exception:
            pass

    return result


@app.post("/api/reverse-engineer/upload")
async def upload_and_analyze(file: UploadFile = File(...), workspace_id: str = "default"):
    """Upload a binary, ASAR, APK, WASM, or script directly for reverse engineering."""
    upload_dir = Path("./data/uploads")
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest_path = upload_dir / file.filename

    content = await file.read()
    dest_path.write_bytes(content)

    return await analyze_target(ReverseEngineerRequest(target_path=str(dest_path), workspace_id=workspace_id))


# ---------------------------------------------------------------------------
# MCP Hypervisor Endpoints (AnythingLLM Feature)
# ---------------------------------------------------------------------------
@app.get("/api/mcp/servers")
async def list_mcp_servers():
    hyp = get_mcp_hypervisor()
    return hyp.list_servers()


@app.post("/api/mcp/servers")
async def register_mcp_server(req: McpServerRegisterRequest):
    hyp = get_mcp_hypervisor()
    server = hyp.register_server(
        name=req.name,
        command=req.command,
        args=req.args,
        env=req.env,
    )
    return server


@app.delete("/api/mcp/servers/{name}")
async def remove_mcp_server(name: str):
    hyp = get_mcp_hypervisor()
    if hyp.remove_server(name):
        return {"status": "removed", "name": name}
    raise HTTPException(status_code=404, detail="Server not found")


@app.post("/api/mcp/servers/{name}/test")
async def test_mcp_server(name: str):
    hyp = get_mcp_hypervisor()
    return hyp.test_server(name)


@app.get("/api/mcp/tools")
async def list_mcp_tools():
    hyp = get_mcp_hypervisor()
    return hyp.list_all_tools()


@app.post("/api/mcp/call")
async def call_mcp_tool(req: McpToolCallRequest):
    hyp = get_mcp_hypervisor()
    return await hyp.call_tool_async(req.server_name, req.tool_name, req.arguments)


# ---------------------------------------------------------------------------
# Multimodal Video Ingestion (Both routes supported)
# ---------------------------------------------------------------------------
@app.post("/ingest/video", response_model=VideoIngestResponse)
@app.post("/api/video/ingest", response_model=VideoIngestResponse)
async def ingest_video_endpoint(req: VideoIngestRequest):
    from ..tools.video import index_lecture_in_rag, ingest_video

    lecture = ingest_video(req.source, whisper_model=s.whisper_model)
    if not lecture:
        raise HTTPException(status_code=400, detail="Could not extract speech or captions from source")

    try:
        chunks_indexed = index_lecture_in_rag(lecture)
        return VideoIngestResponse(
            title=lecture.title,
            url=lecture.url,
            source_type=lecture.source_type,
            segments_count=len(lecture.segments),
            indexed_chunks=chunks_indexed,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Video indexing failed: {e}")


# ---------------------------------------------------------------------------
# Multi-Agent Research & Reverse Engineering Orchestration
# ---------------------------------------------------------------------------
@app.post("/research", response_model=ResearchResponse)
@app.post("/api/research", response_model=ResearchResponse)
async def run_research(req: ResearchRequest):
    graph = get_graph()
    t0 = time.time()

    initial_state = {
        "topic": req.topic,
        "focus_mode": req.focus_mode,
        "video_url": req.video_url,
        "target_path": req.target_path,
        "workspace_id": req.workspace_id,
        "sub_questions": [],
        "findings": [],
        "re_findings": [],
        "mcp_tools_used": [],
        "raw_search_notes": [],
        "fact_checks": [],
        "draft_report": "",
        "final_report": "",
        "review_count": 0,
        "review_feedback": "",
        "status": "planning",
        "error": "",
        "sources_used": [],
    }

    try:
        final = await graph.ainvoke(initial_state)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Research graph execution failed: {e}")

    elapsed = round(time.time() - t0, 2)
    return ResearchResponse(
        topic=final.get("topic", req.topic),
        status=final.get("status", "done"),
        final_report=final.get("final_report", ""),
        sub_questions=final.get("sub_questions", []),
        findings_count=len(final.get("findings", [])),
        re_findings_count=len(final.get("re_findings", [])),
        fact_checks=final.get("fact_checks", []),
        sources=list(set(final.get("sources_used", []))),
        review_count=final.get("review_count", 0),
        elapsed_seconds=elapsed,
    )


async def _research_event_generator(req: ResearchRequest) -> AsyncIterator[str]:
    graph = get_graph()
    t0 = time.time()

    initial_state = {
        "topic": req.topic,
        "focus_mode": req.focus_mode,
        "video_url": req.video_url,
        "target_path": req.target_path,
        "workspace_id": req.workspace_id,
        "sub_questions": [],
        "findings": [],
        "re_findings": [],
        "mcp_tools_used": [],
        "raw_search_notes": [],
        "fact_checks": [],
        "draft_report": "",
        "final_report": "",
        "review_count": 0,
        "review_feedback": "",
        "status": "planning",
        "error": "",
        "sources_used": [],
    }

    yield f"data: {json.dumps({'event': 'started', 'topic': req.topic, 'mode': req.focus_mode, 'target': req.target_path})}\n\n"

    try:
        async for chunk in graph.astream(initial_state):
            for node_name, node_output in chunk.items():
                if not isinstance(node_output, dict):
                    continue

                event_data = {
                    "event": "node_update",
                    "node": node_name,
                    "status": node_output.get("status", ""),
                    "sub_questions": node_output.get("sub_questions"),
                    "findings_count": len(node_output.get("findings", [])),
                    "re_findings_count": len(node_output.get("re_findings", [])),
                    "fact_checks": node_output.get("fact_checks"),
                    "has_draft": bool(node_output.get("draft_report")),
                    "has_final": bool(node_output.get("final_report")),
                    "review_feedback": node_output.get("review_feedback"),
                }
                yield f"data: {json.dumps(event_data)}\n\n"

        elapsed = round(time.time() - t0, 2)
        yield f"data: {json.dumps({'event': 'completed', 'elapsed_seconds': elapsed})}\n\n"

    except Exception as e:
        yield f"data: {json.dumps({'event': 'error', 'error': str(e)})}\n\n"


@app.post("/research/stream")
@app.post("/api/research/stream")
async def stream_research(req: ResearchRequest):
    return StreamingResponse(
        _research_event_generator(req),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
