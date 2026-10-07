"""FastAPI server for the Multi-Agent Research Assistant."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..config import get_settings
from ..graph.workflow import get_graph

app = FastAPI(
    title="MARAT — Multi-Agent Research Assistant Technology",
    description="MARAT: Autonomous multi-agent research pipeline featuring Mara 🐾. Decomposes topics, investigates the web, fact-checks claims, queries ChromaDB RAG, and produces peer-reviewed Markdown reports.",
    version="1.0.0",
)

s = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=s.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ResearchRequest(BaseModel):
    topic: str = Field(..., min_length=3, max_length=500)
    focus_mode: str = Field(default="broad", pattern="^(broad|deep|verify)$")
    stream: bool = False


class ResearchResponse(BaseModel):
    topic: str
    status: str
    final_report: str
    sub_questions: list
    findings_count: int
    fact_checks: list
    sources: list
    review_count: int
    elapsed_seconds: float


@app.get("/health")
async def health():
    return {"status": "ok", "provider": s.llm_provider, "model": s.llm_model}


@app.post("/research", response_model=ResearchResponse)
async def research(req: ResearchRequest):
    """Run the full multi-agent research pipeline (non-streaming)."""
    graph = get_graph()
    start = time.time()

    initial: dict = {
        "topic": req.topic,
        "focus_mode": req.focus_mode,
        "sub_questions": [],
        "findings": [],
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
        result = await graph.ainvoke(initial)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    elapsed = time.time() - start

    # Persist report
    reports_dir = s.save_reports_dir
    reports_dir.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in req.topic)[:60]
    path = reports_dir / f"{int(time.time())}_{safe_name}.md"
    path.write_text(
        result.get("final_report") or result.get("draft_report") or "", encoding="utf-8"
    )

    return ResearchResponse(
        topic=req.topic,
        status=result.get("status", "unknown"),
        final_report=result.get("final_report") or result.get("draft_report") or "",
        sub_questions=result.get("sub_questions") or [],
        findings_count=len(result.get("findings") or []),
        fact_checks=result.get("fact_checks") or [],
        sources=result.get("sources_used") or [],
        review_count=result.get("review_count", 0),
        elapsed_seconds=round(elapsed, 2),
    )


@app.post("/research/stream")
async def research_stream(req: ResearchRequest):
    """Stream progress events + final report (SSE)."""
    graph = get_graph()

    initial: dict = {
        "topic": req.topic,
        "focus_mode": req.focus_mode,
        "sub_questions": [],
        "findings": [],
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

    async def event_generator() -> AsyncIterator[str]:
        yield f"data: {json.dumps({'event': 'started', 'topic': req.topic})}\n\n"
        final_state = dict(initial)
        try:
            async for event in graph.astream(initial, stream_mode="updates"):
                # event is {node_name: state_update}
                for node, update in event.items():
                    for k, v in update.items():
                        if k in ("findings", "raw_search_notes", "sources_used") and isinstance(
                            v, list
                        ):
                            final_state[k] = final_state.get(k, []) + v
                        else:
                            final_state[k] = v

                    payload = {
                        "event": "node_update",
                        "node": node,
                        "status": update.get("status"),
                        "sub_questions": update.get("sub_questions"),
                        "findings_added": len(update.get("findings") or []),
                        "review_count": update.get("review_count"),
                    }
                    yield f"data: {json.dumps(payload, default=str)}\n\n"
                    await asyncio.sleep(0.01)

            yield f"data: {json.dumps({'event': 'completed', 'report': final_state.get('final_report') or final_state.get('draft_report'), 'sources': final_state.get('sources_used')})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'event': 'error', 'detail': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.api.main:app",
        host=s.api_host,
        port=s.api_port,
        reload=False,
    )
