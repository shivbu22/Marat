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
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from ..config import get_settings
from ..graph.workflow import get_graph
from ..llm import get_llm
from ..mcp.hypervisor import get_mcp_hypervisor
from ..reverse_engineer.agent import run_target_analysis
from ..workspaces.manager import get_workspace_manager
from ..workspaces.memory import get_chat_memory
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


class ThreadCreateRequest(BaseModel):
    name: str = Field(default="New Thread", min_length=1, max_length=100)


class ThreadUpdateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)


class SettingsUpdateRequest(BaseModel):
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    temperature: float | None = None


class WorkspaceSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    k: int = 5


class ChatMessageRequest(BaseModel):
    workspace_id: str = "default"
    thread_id: str | None = None
    message: str = Field(..., min_length=1)
    mode: str = Field(default="chat")  # "chat" | "agent" | "research" | "reverse_engineer"
    target_path: str = ""
    tools: list[str] = Field(default_factory=list)


class YouTubeSummarizeRequest(BaseModel):
    url: str = Field(..., description="YouTube video URL or video ID")
    focus: str = Field(default="", description="Optional custom focus area or prompt")
    workspace_id: str = Field(default="default")


def _resolve_static_index() -> Path:
    candidates = [
        Path(__file__).parent / "static" / "index.html",
        Path(__file__).resolve().parent / "static" / "index.html",
    ]
    import sys
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        meipass = Path(sys._MEIPASS)
        candidates.insert(0, meipass / "src" / "api" / "static" / "index.html")
        candidates.insert(1, meipass / "static" / "index.html")
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


STATIC_INDEX = _resolve_static_index()


# ---------------------------------------------------------------------------
# Core UI & Status
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the MARAT web dashboard."""
    p = _resolve_static_index()
    if p.exists():
        return HTMLResponse(content=p.read_text(encoding="utf-8"))
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


@app.delete("/api/workspaces/{workspace_id}/documents/{document_id}")
async def delete_workspace_document(workspace_id: str, document_id: str):
    mgr = get_workspace_manager()
    rag = get_rag()
    ws = mgr.get_workspace(workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    success, _, filename = mgr.delete_document(document_id)
    if not success:
        raise HTTPException(status_code=404, detail="Document not found")

    if filename and ws.vector_collection:
        rag.delete_document_chunks(filename, collection_name=ws.vector_collection)

    return {"status": "deleted", "document_id": document_id, "filename": filename}


@app.post("/api/workspaces/{workspace_id}/search")
async def search_workspace_documents(workspace_id: str, req: WorkspaceSearchRequest):
    mgr = get_workspace_manager()
    rag = get_rag()
    ws = mgr.get_workspace(workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    results = rag.search(req.query, k=req.k, collection_name=ws.vector_collection)
    return {
        "status": "ok",
        "workspace_id": workspace_id,
        "query": req.query,
        "count": len(results),
        "results": results,
    }



# ---------------------------------------------------------------------------
# Threads & Chat Endpoints (AnythingLLM Feature)
# ---------------------------------------------------------------------------
@app.get("/api/workspaces/{workspace_id}/threads")
async def list_workspace_threads(workspace_id: str):
    mgr = get_workspace_manager()
    threads = mgr.list_threads(workspace_id)
    if not threads:
        initial = mgr.create_thread(workspace_id, name="Hey")
        threads = [initial]
    return threads


@app.post("/api/workspaces/{workspace_id}/threads")
async def create_workspace_thread(workspace_id: str, req: ThreadCreateRequest):
    mgr = get_workspace_manager()
    ws = mgr.get_workspace(workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return mgr.create_thread(workspace_id, name=req.name)


@app.get("/api/threads/{thread_id}/messages")
async def get_thread_messages(thread_id: str):
    mgr = get_workspace_manager()
    return mgr.list_messages(thread_id)


@app.delete("/api/threads/{thread_id}")
async def delete_thread(thread_id: str):
    mgr = get_workspace_manager()
    success = mgr.delete_thread(thread_id)
    if not success:
        raise HTTPException(status_code=404, detail="Thread not found")
    return {"status": "deleted", "id": thread_id}


@app.patch("/api/threads/{thread_id}")
async def rename_thread(thread_id: str, req: ThreadUpdateRequest):
    mgr = get_workspace_manager()
    th = mgr.update_thread(thread_id, req.name)
    if not th:
        raise HTTPException(status_code=404, detail="Thread not found")
    return th


@app.get("/api/threads/{thread_id}/export")
async def export_thread(thread_id: str, format: str = "markdown"):
    mgr = get_workspace_manager()
    thread = mgr.get_thread(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    messages = mgr.list_messages(thread_id, limit=500)

    if format.lower() == "json":
        return JSONResponse(
            content={
                "thread_id": thread.id,
                "thread_name": thread.name,
                "workspace_id": thread.workspace_id,
                "messages": [m.model_dump() for m in messages],
            },
            headers={"Content-Disposition": f'attachment; filename="marat_{thread.name.replace(" ", "_")}.json"'},
        )

    lines = [
        f"# MARAT Intelligence Dossier: {thread.name}",
        f"*Generated on {time.strftime('%Y-%m-%d %H:%M:%S')}*",
        "",
        "---",
        "",
    ]
    for m in messages:
        sender = "👤 **User**" if m.role == "user" else "🐾 **Mara (MARAT Intelligence)**"
        lines.append(f"### {sender}")
        lines.append(m.content)
        if m.metadata and m.metadata.get("sources"):
            lines.append("")
            lines.append("**Sources Consulted:**")
            for src in m.metadata["sources"]:
                lines.append(f"- {src}")
        lines.append("")
        lines.append("---")
        lines.append("")

    md_content = "\n".join(lines)
    return HTMLResponse(
        content=md_content,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="marat_{thread.name.replace(" ", "_")}.md"'},
    )



@app.post("/api/chat")
async def send_chat_message(req: ChatMessageRequest):
    mgr = get_workspace_manager()
    rag = get_rag()
    ws = mgr.get_workspace(req.workspace_id)
    if not ws:
        ws = mgr.get_workspace_by_slug("default")
        if not ws:
            raise HTTPException(status_code=404, detail="Workspace not found")
        req.workspace_id = ws.id

    # Ensure thread exists
    thread_id = req.thread_id
    if not thread_id:
        threads = mgr.list_threads(req.workspace_id)
        if threads:
            thread_id = threads[0].id
        else:
            new_th = mgr.create_thread(req.workspace_id, name="Hey")
            thread_id = new_th.id

    # Record user message
    user_msg = mgr.add_message(thread_id, req.workspace_id, "user", req.message)

    clean_msg = req.message.strip()
    is_agent = clean_msg.startswith("@agent") or clean_msg.startswith("/research") or req.mode in ("agent", "research")
    is_re = clean_msg.startswith("/re") or req.mode == "reverse_engineer" or bool(req.target_path)

    # Retrieve thread name if present
    thread = mgr.get_thread(thread_id)
    thread_name = thread.name if thread else "Chat"

    # Recall past conversation memory on this topic
    chat_memory = get_chat_memory()
    recalled_memories = chat_memory.recall_topic_memory(clean_msg, workspace_id=ws.id, k=3)
    memory_context = ""
    if recalled_memories:
        memory_context = "\n\n--- Prior Conversation Memory on this Topic ---\n" + "\n---\n".join(
            m["text"] for m in recalled_memories
        ) + "\n(Note: The user is continuing or refining a discussion on this topic. Build directly upon these prior conclusions to improve continuous memory.)"

    # 1. Reverse Engineering Mode
    if is_re:
        target = req.target_path
        if not target and clean_msg.startswith("/re"):
            parts = clean_msg.split(maxsplit=1)
            target = parts[1].strip() if len(parts) > 1 else "./src"
        if not target:
            target = "./src"

        re_res = run_target_analysis(target)
        summary = re_res.get("summary", "Analysis completed.")
        content = f"### 🔬 Reverse Engineering Findings for `{re_res.get('file_name', target)}`\n\n**Format:** {re_res.get('format')}\n\n**Summary:** {summary}\n\n"
        data = re_res.get("data", {})
        if data.get("sections"):
            content += f"**Sections ({len(data['sections'])}):** " + ", ".join(f"`{s['name']}` (entropy: {s.get('entropy', 0):.2f})" for s in data["sections"][:5]) + "\n\n"
        if data.get("ipc_channels"):
            content += f"**Electron IPC Channels ({len(data['ipc_channels'])}):**\n"
            for ch in data["ipc_channels"][:8]:
                content += f"- `{ch.get('channel')}` ({ch.get('type')})\n"
            content += "\n"
        if data.get("api_endpoints"):
            content += f"**Discovered API Endpoints ({len(data['api_endpoints'])}):**\n"
            for ep in data["api_endpoints"][:8]:
                content += f"- `{ep}`\n"

        asst_msg = mgr.add_message(
            thread_id,
            req.workspace_id,
            "assistant",
            content,
            metadata={"type": "reverse_engineering", "data": re_res},
        )
        chat_memory.append_turn(
            workspace_id=ws.id,
            thread_id=thread_id,
            user_message=clean_msg,
            assistant_message=content,
            thread_name=thread_name,
            mode="reverse_engineer",
            metadata={"re_format": re_res.get("format")},
        )
        return {
            "thread_id": thread_id,
            "user_message": user_msg,
            "assistant_message": asst_msg,
            "mode": "reverse_engineer",
            "recalled_memories_count": len(recalled_memories),
        }

    # 2. Built-in YouTube Video Summarization
    from ..tools.video import extract_youtube_id, summarize_youtube_video
    yt_id = extract_youtube_id(clean_msg)
    if yt_id and ("youtube.com" in clean_msg.lower() or "youtu.be" in clean_msg.lower() or clean_msg.lower().startswith("/yt") or "summarize" in clean_msg.lower()):
        video_url = f"https://www.youtube.com/watch?v={yt_id}"
        sum_res = await summarize_youtube_video(video_url, workspace_id=ws.id)
        if sum_res.get("status") == "success":
            content = sum_res["summary"]
            yt_sources = [f"YouTube: {sum_res.get('title', 'Video')}"]
            asst_msg = mgr.add_message(
                thread_id,
                req.workspace_id,
                "assistant",
                content,
                metadata={
                    "type": "youtube_summary",
                    "sources": yt_sources,
                    "duration": sum_res.get("duration_formatted"),
                    "title": sum_res.get("title"),
                    "indexed_chunks": sum_res.get("indexed_chunks", 0),
                },
            )
            chat_memory.append_turn(
                workspace_id=ws.id,
                thread_id=thread_id,
                user_message=clean_msg,
                assistant_message=content,
                thread_name=thread_name,
                mode="youtube_summary",
                sources=yt_sources,
            )
            return {
                "thread_id": thread_id,
                "user_message": user_msg,
                "assistant_message": asst_msg,
                "mode": "youtube_summary",
                "recalled_memories_count": 0,
            }

    # 3. Multi-Agent Autonomous Research Mode
    if is_agent:
        topic = clean_msg.replace("@agent", "").replace("/research", "").strip() or clean_msg
        graph = get_graph()
        initial_state = {
            "topic": topic,
            "focus_mode": "broad",
            "video_url": "",
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
        res = await graph.ainvoke(initial_state)
        report = res.get("final_report") or res.get("draft_report") or "No report synthesized."
        asst_msg = mgr.add_message(
            thread_id,
            req.workspace_id,
            "assistant",
            report,
            metadata={
                "type": "agent_research",
                "sub_questions": res.get("sub_questions", []),
                "fact_checks": res.get("fact_checks", []),
                "sources": res.get("sources_used", []),
                "review_count": res.get("review_count", 0),
            },
        )
        chat_memory.append_turn(
            workspace_id=ws.id,
            thread_id=thread_id,
            user_message=clean_msg,
            assistant_message=report,
            thread_name=thread_name,
            mode="agent_research",
            sources=res.get("sources_used", []),
        )
        return {
            "thread_id": thread_id,
            "user_message": user_msg,
            "assistant_message": asst_msg,
            "mode": "agent",
            "recalled_memories_count": len(recalled_memories),
        }

    # 4. Direct Workspace RAG & Live Knowledge Search Chat
    rag_context = ""
    sources = []
    if ws.vector_collection:
        try:
            chunks = rag.search(clean_msg, k=4, collection_name=ws.vector_collection)
            if chunks:
                rag_context = "\n\nRelevant Workspace Documents:\n" + "\n---\n".join(
                    c.get("text", "") for c in chunks
                )
                sources = [c.get("metadata", {}).get("filename", "Doc") for c in chunks if c.get("metadata")]
        except Exception:
            pass

    # Live India / Recent News Integration
    live_news_context = ""
    from ..tools.search import _is_india_query, _is_recent_query, web_search_async
    if _is_india_query(clean_msg) or _is_recent_query(clean_msg) or clean_msg.lower().startswith("/news") or clean_msg.lower().startswith("/india"):
        try:
            search_query = clean_msg.replace("/news", "").replace("/india", "").strip() or "India top news today"
            search_hits = await web_search_async(search_query, timelimit="w")
            if search_hits:
                snippets = []
                for h in search_hits[:4]:
                    snippets.append(f"- **{h.title}**: {h.snippet} ({h.url})")
                    sources.append(h.url)
                live_news_context = "\n\nLive Search & Current News Headlines:\n" + "\n".join(snippets)
        except Exception:
            pass

    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        llm = get_llm(temperature=ws.temperature)
        system_content = (
            f"{ws.system_prompt}\n\n"
            f"You are Marat, an elite intelligence assistant with comprehensive built-in awareness of Indian national news, "
            f"governance, space missions (ISRO), digital public infrastructure (UPI/DPI), economy, technology (IndiaAI, semiconductors), "
            f"multimedia summaries, and general questions across science, code, history, and reasoning. "
            f"Provide insightful, well-structured, authoritative answers with markdown formatting and citations."
        )
        if memory_context:
            system_content += memory_context
        if rag_context:
            system_content += f"\n{rag_context}"
        if live_news_context:
            system_content += f"\n{live_news_context}"
        response = await llm.ainvoke([SystemMessage(content=system_content), HumanMessage(content=clean_msg)])
        answer = response.content if hasattr(response, "content") else str(response)
    except Exception as e:
        answer = f"Mara (companion): I received your message '{clean_msg}'. (Note: Local model response: {e}. You can connect Ollama or configure an API key in Settings!)"

    recalled_info = [m["text"][:100] for m in recalled_memories] if recalled_memories else []
    asst_msg = mgr.add_message(
        thread_id,
        req.workspace_id,
        "assistant",
        answer,
        metadata={"sources": list(set(sources)), "recalled_memory": recalled_info},
    )
    chat_memory.append_turn(
        workspace_id=ws.id,
        thread_id=thread_id,
        user_message=clean_msg,
        assistant_message=answer,
        thread_name=thread_name,
        mode="chat",
        sources=list(set(sources)),
    )
    return {
        "thread_id": thread_id,
        "user_message": user_msg,
        "assistant_message": asst_msg,
        "mode": "chat",
        "recalled_memories_count": len(recalled_memories),
    }


# ---------------------------------------------------------------------------
# Persistent Chat Memory Endpoints
# ---------------------------------------------------------------------------
@app.get("/api/memory")
async def get_memory_status():
    mem = get_chat_memory()
    records = mem.get_all_records()
    return {
        "status": "ok",
        "file_path": str(mem.get_file_path()),
        "total_turns": len(records),
        "recent_turns": [r.model_dump() for r in records[-20:]],
    }


@app.get("/api/memory/export")
async def export_chat_memory():
    mem = get_chat_memory()
    file_path = mem.get_file_path()
    if not file_path.exists():
        file_path.write_text("[]", encoding="utf-8")
    return FileResponse(
        str(file_path),
        media_type="application/json",
        filename="marat_chat_history.json",
    )


@app.post("/api/memory/import")
async def import_chat_memory(file: UploadFile = File(...)):
    mem = get_chat_memory()
    content = await file.read()
    try:
        count = mem.import_records(content.decode("utf-8"))
        return {"status": "success", "imported_records": count, "total_records": len(mem.get_all_records())}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to import chat memory: {e}")


@app.get("/api/memory/recall")
async def test_memory_recall(q: str = ""):
    mem = get_chat_memory()
    hits = mem.recall_topic_memory(q, k=5)
    return {"query": q, "count": len(hits), "recalled_memories": hits}


# ---------------------------------------------------------------------------
# YouTube Summaries & Live India News Endpoints
# ---------------------------------------------------------------------------
@app.post("/api/video/summarize")
async def summarize_video_endpoint(req: YouTubeSummarizeRequest):
    """Summarize any YouTube video, index it, and return structured markdown."""
    from ..tools.video import summarize_youtube_video

    res = await summarize_youtube_video(req.url, focus=req.focus, workspace_id=req.workspace_id)
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message", "Video summarization failed"))
    return res


@app.get("/api/news/india")
async def get_india_news_endpoint(q: str = "India top news today", limit: int = 8):
    """Retrieve live breaking national, economic, and technological headlines from India."""
    from ..tools.search import search_india_news

    loop = asyncio.get_running_loop()
    results = await loop.run_in_executor(None, lambda: search_india_news(q, max_results=limit))
    return {
        "status": "ok",
        "query": q,
        "count": len(results),
        "articles": [r.model_dump() for r in results],
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


# ---------------------------------------------------------------------------
# Global Settings & Curated Knowledge Digest
# ---------------------------------------------------------------------------
@app.get("/api/settings")
async def get_settings_endpoint():
    cur_s = get_settings()
    masked_key = ""
    if cur_s.llm_api_key and cur_s.llm_api_key != "ollama":
        k = cur_s.llm_api_key
        masked_key = k[:3] + "..." + k[-3:] if len(k) > 6 else "***"
    return {
        "status": "ok",
        "llm_provider": cur_s.llm_provider,
        "llm_model": cur_s.llm_model,
        "llm_base_url": cur_s.llm_base_url,
        "llm_api_key_set": bool(cur_s.llm_api_key and cur_s.llm_api_key != "ollama"),
        "llm_api_key_masked": masked_key,
        "temperature": cur_s.temperature,
        "rag_enabled": cur_s.rag_enabled,
    }


@app.post("/api/settings")
async def update_settings_endpoint(req: SettingsUpdateRequest):
    from ..config import update_settings

    updates = req.model_dump(exclude_unset=True)
    updated = update_settings(updates)
    return {
        "status": "success",
        "llm_provider": updated.llm_provider,
        "llm_model": updated.llm_model,
        "llm_base_url": updated.llm_base_url,
        "temperature": updated.temperature,
    }


@app.get("/api/knowledge/digest")
async def get_knowledge_digest():
    """Returns curated intelligence cards across domains (India, World 6M, RE)."""
    return {
        "status": "ok",
        "cards": [
            {
                "domain": "🇮🇳 India Technology & Space",
                "tag": "ISRO / DPI / AI",
                "summary": "Chandrayaan-3 and Gaganyaan human spaceflight preparations, Aditya-L1 solar observation, IndiaAI mission allocating 10,000 GPUs, national semiconductor fab buildout in Gujarat & Assam, and global expansion of UPI digital public rails.",
            },
            {
                "domain": "🌐 Global 6-Month AI Horizon",
                "tag": "Reasoning & Frontier Labs",
                "summary": "Emergence of deep reasoning test-time compute scaling (o1/o3 architectures), multimodal open-weights proliferation (Llama 3.3, DeepSeek-V3), quantum error correction milestones at Quantinuum & Google, and autonomous agent hypervisors.",
            },
            {
                "domain": "🔬 Reverse Engineering Arsenal",
                "tag": "Binary & APK Inspection",
                "summary": "Automated unpacking of Electron ASAR bundles, PE/ELF section entropy & suspicious import detection, Android APK manifest/permission auditing, WebAssembly binary opcode decompilation, and MCP tool orchestration.",
            },
        ],
    }

