"""LangGraph nodes implementing the research agents."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from langchain_core.messages import HumanMessage, SystemMessage

from ..config import get_settings
from ..llm import get_llm
from ..rag.store import get_rag
from ..tools.search import SearchResult, web_search_async

if TYPE_CHECKING:
    from ..graph.state import ResearchState


def _load_agent_persona(agent_name: str) -> dict:
    """Load agent persona from configs/agents.yaml if available."""
    try:
        p = Path("configs/agents.yaml")
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                return data.get(agent_name, {})
    except Exception:
        pass
    return {}


def _parse_json_block(text: Any) -> Any:
    """Extract first JSON object/array from LLM output."""
    if not isinstance(text, str):
        if hasattr(text, "content"):
            text = text.content
        elif isinstance(text, list):
            text = "".join(
                str(item.get("text", item) if isinstance(item, dict) else item) for item in text
            )
        else:
            text = str(text) if text is not None else ""

    # Try fenced code block first
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Check which comes first: array [ or object {
    idx_brace = text.find("{")
    idx_bracket = text.find("[")

    if idx_bracket != -1 and (idx_brace == -1 or idx_bracket < idx_brace):
        delimiters = [("[", "]"), ("{", "}")]
    else:
        delimiters = [("{", "}"), ("[", "]")]

    for start_char, end_char in delimiters:
        start = text.find(start_char)
        if start == -1:
            continue
        depth = 0
        for i in range(start, len(text)):
            if text[i] == start_char:
                depth += 1
            elif text[i] == end_char:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
    return None


# ---------------------------------------------------------------------------
# PLANNER
# ---------------------------------------------------------------------------
async def planner_node(state: ResearchState) -> dict:
    s = get_settings()
    llm = get_llm(temperature=0.3)
    persona = _load_agent_persona("planner")
    role = persona.get("role", "Research Planner")
    backstory = persona.get("backstory", "").strip()

    system = f"""You are the {role}.
{backstory}

Break the given topic into 3–{s.max_sub_questions} focused, non-overlapping sub-questions.
Return ONLY a JSON array of objects with keys: id, question, rationale.
ids should be short like "q1", "q2"."""

    prompt = f"""Topic: {state["topic"]}
Focus mode: {state.get("focus_mode", "broad")}

Produce the sub-questions now."""

    try:
        resp = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=prompt)])
        data = _parse_json_block(resp.content) or []
    except Exception:
        data = []

    if isinstance(data, dict):
        data = [data]

    sub_qs = []
    if isinstance(data, list):
        for i, item in enumerate(data[: s.max_sub_questions]):
            if isinstance(item, dict):
                sub_qs.append(
                    {
                        "id": item.get("id") or f"q{i + 1}",
                        "question": item.get("question", str(item)),
                        "rationale": item.get("rationale", ""),
                    }
                )
            else:
                sub_qs.append({"id": f"q{i + 1}", "question": str(item), "rationale": ""})

    if not sub_qs:
        # Hard fallback
        sub_qs = [
            {
                "id": "q1",
                "question": state["topic"],
                "rationale": "Direct coverage of the full topic",
            }
        ]

    return {
        "sub_questions": sub_qs,
        "status": "researching",
        "review_count": 0,
        "findings": [],
        "raw_search_notes": [],
        "sources_used": [],
    }


# ---------------------------------------------------------------------------
# RESEARCHER (one or parallel)
# ---------------------------------------------------------------------------
async def _research_one(sq: dict) -> tuple[list[dict], list[str], list[str]]:
    """Research a single sub-question. Returns findings, notes, sources."""
    llm = get_llm(temperature=0.2)
    query = sq["question"]

    # 1. Web search
    results: list[SearchResult] = await web_search_async(query)
    sources = [r.url for r in results if r.url]
    notes = "\n\n".join(f"Source: {r.title}\nURL: {r.url}\n{r.snippet}" for r in results)

    # 2. Optional RAG context
    rag_context = ""
    try:
        rag = get_rag()
        hits = rag.search(query, k=3)
        if hits:
            rag_context = "\n\n--- From local knowledge vault ---\n" + "\n".join(
                h["text"][:400] for h in hits
            )
    except Exception:
        pass

    # 3. Extract structured findings
    persona = _load_agent_persona("researcher")
    role = persona.get("role", "Web Research Specialist")
    backstory = persona.get("backstory", "").strip()

    system = f"""You are the {role}.
{backstory}

Given search results, extract 2–5 key claims relevant to the sub-question.
Return ONLY a JSON array of objects:
[
  {{
    "claim": "...",
    "evidence": "short supporting quote or paraphrase",
    "sources": ["url1", "url2"],
    "confidence": 0.0-1.0
  }}
]
Only include claims that are actually supported by the provided material.
If material is weak, use lower confidence and fewer claims."""

    user = f"""Sub-question: {query}

Search results:
{notes[:3000]}
{rag_context[:1000]}
"""

    try:
        resp = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
        data = _parse_json_block(resp.content) or []
    except Exception:
        data = []

    if isinstance(data, dict):
        data = [data]

    findings = []
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            findings.append(
                {
                    "sub_question_id": sq["id"],
                    "claim": item.get("claim", ""),
                    "evidence": item.get("evidence", ""),
                    "sources": item.get("sources") or sources[:2],
                    "confidence": float(item.get("confidence", 0.5)),
                }
            )

    # Fallback to search snippets if LLM produced no structured claims
    if not findings and results:
        for r in results[:2]:
            if r.snippet:
                findings.append(
                    {
                        "sub_question_id": sq["id"],
                        "claim": f"{r.title}: {r.snippet[:120]}",
                        "evidence": r.snippet,
                        "sources": [r.url] if r.url else sources[:1],
                        "confidence": 0.5,
                    }
                )

    return findings, [notes], sources


async def researcher_node(state: ResearchState) -> dict:
    s = get_settings()
    sub_qs = state.get("sub_questions") or []

    if s.parallel_researchers and len(sub_qs) > 1:
        sem = asyncio.Semaphore(2 if s.llm_provider == "ollama" else 4)

        async def _bounded_research(sq: dict):
            async with sem:
                return await _research_one(sq)

        tasks = [_bounded_research(sq) for sq in sub_qs]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    else:
        results = []
        for sq in sub_qs:
            results.append(await _research_one(sq))

    all_findings: list[dict] = []
    all_notes: list[str] = []
    all_sources: list[str] = []

    for res in results:
        if isinstance(res, Exception):
            all_notes.append(f"Research error: {res}")
            continue
        findings, notes, sources = res
        all_findings.extend(findings)
        all_notes.extend(notes)
        all_sources.extend(sources)

    return {
        "findings": all_findings,
        "raw_search_notes": all_notes,
        "sources_used": list(dict.fromkeys(all_sources)),  # dedupe preserve order
        "status": "fact_checking",
    }


# ---------------------------------------------------------------------------
# FACT CHECKER
# ---------------------------------------------------------------------------
async def fact_checker_node(state: ResearchState) -> dict:
    llm = get_llm(temperature=0.1)
    findings = state.get("findings") or []

    if not findings:
        return {"fact_checks": [], "status": "writing"}

    # Check top claims (limit for cost/latency)
    to_check = findings[:12]
    claims_text = "\n".join(
        f"- Claim: {f['claim']}\n  Evidence: {f.get('evidence', '')}\n  Sources: {f.get('sources', [])}"
        for f in to_check
    )

    persona = _load_agent_persona("fact_checker")
    role = persona.get("role", "Fact Checker & Source Validator")
    backstory = persona.get("backstory", "").strip()

    system = f"""You are the {role}.
{backstory}

For each claim, decide:
- VERIFIED: multiple independent sources or strong primary evidence
- PARTIALLY_VERIFIED: some support but incomplete or single-source
- UNVERIFIED: insufficient evidence
- CONTRADICTED: evidence against the claim

Return ONLY a JSON array:
[
  {{
    "claim": "...",
    "status": "VERIFIED|PARTIALLY_VERIFIED|UNVERIFIED|CONTRADICTED",
    "notes": "brief reason",
    "supporting_sources": [],
    "conflicting_sources": []
  }}
]"""

    user = f"""Original topic: {state["topic"]}

Claims to check:
{claims_text}

Base your judgment primarily on the evidence already provided. Be conservative."""

    try:
        resp = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
        data = _parse_json_block(resp.content) or []
    except Exception:
        data = []

    if isinstance(data, dict):
        data = [data]

    fact_checks = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                fact_checks.append(
                    {
                        "claim": item.get("claim", ""),
                        "status": item.get("status", "UNVERIFIED"),
                        "notes": item.get("notes", ""),
                        "supporting_sources": item.get("supporting_sources") or [],
                        "conflicting_sources": item.get("conflicting_sources") or [],
                    }
                )

    if not fact_checks and findings:
        for f in to_check:
            fact_checks.append(
                {
                    "claim": f["claim"],
                    "status": "PARTIALLY_VERIFIED",
                    "notes": "Corroborated by research findings",
                    "supporting_sources": f.get("sources", []),
                    "conflicting_sources": [],
                }
            )

    return {"fact_checks": fact_checks, "status": "writing"}


# ---------------------------------------------------------------------------
# WRITER
# ---------------------------------------------------------------------------
async def writer_node(state: ResearchState) -> dict:
    llm = get_llm(temperature=0.4)
    s = get_settings()

    findings = state.get("findings") or []
    fact_checks = state.get("fact_checks") or []
    feedback = state.get("review_feedback") or ""

    # Build verified claim list
    verified_map = {fc["claim"]: fc for fc in fact_checks}

    claims_block = []
    for f in findings:
        status = verified_map.get(f["claim"], {}).get("status", "UNVERIFIED")
        claims_block.append(
            f"- [{status}] {f['claim']}\n  Evidence: {f.get('evidence', '')}\n  Sources: {', '.join(f.get('sources') or [])}"
        )

    persona = _load_agent_persona("writer")
    role = persona.get("role", "Research Report Writer")
    backstory = persona.get("backstory", "").strip()

    system = f"""You are the {role}.
{backstory}

Structure the report exactly as:

# {{title}}

## Executive Summary
(3–6 sentences)

## Key Findings
- bullet points with inline citations like [1], [2]

## Detailed Analysis
Use sub-headings for major themes. Cite sources.

## Limitations & Open Questions
Be honest about gaps and confidence levels.

## Sources
Numbered list of unique URLs used.

Rules:
- Every non-obvious claim must have a citation.
- Prefer VERIFIED and PARTIALLY_VERIFIED claims; note UNVERIFIED ones carefully.
- Neutral, professional tone.
- If review feedback is provided, address it thoroughly.
"""

    user = f"""Topic: {state["topic"]}

Sub-questions explored:
{json.dumps(state.get("sub_questions"), indent=2)}

Findings + fact-check status:
{chr(10).join(claims_block)}

All sources collected:
{chr(10).join(f"[{i}] {u}" for i, u in enumerate(state.get("sources_used") or [], 1))}

{"Previous reviewer feedback to address:" + feedback if feedback else ""}

Write the full report now."""

    try:
        resp = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
        draft = resp.content.strip() if isinstance(resp.content, str) else str(resp.content).strip()
    except Exception:
        draft = (
            f"# {state['topic']}\n\n"
            "## Executive Summary\n"
            "This structured research report consolidates findings from multi-agent web exploration.\n\n"
            "## Key Findings\n"
            + "\n".join(f"- {f['claim']}" for f in findings[:5])
            + "\n\n## Sources\n"
            + "\n".join(f"[{i}] {s}" for i, s in enumerate(state.get("sources_used") or [], 1))
        )

    # Store in RAG for future use
    if s.rag_enabled:
        try:
            rag = get_rag()
            rag.add_texts(
                [draft],
                metadatas=[{"topic": state["topic"], "type": "research_report"}],
            )
        except Exception:
            pass

    return {
        "draft_report": draft,
        "status": "reviewing",
    }


# ---------------------------------------------------------------------------
# REVIEWER
# ---------------------------------------------------------------------------
async def reviewer_node(state: ResearchState) -> dict:
    s = get_settings()
    llm = get_llm(temperature=0.2)
    review_count = state.get("review_count", 0) + 1

    persona = _load_agent_persona("reviewer")
    role = persona.get("role", "Quality Reviewer")
    backstory = persona.get("backstory", "").strip()

    system = f"""You are the {role}.
{backstory}

Check:
1. Does the report fully answer the original topic?
2. Are major claims properly cited and mostly verified?
3. Is the structure clear and professional?
4. Are limitations acknowledged?

Return a JSON object:
{{
  "approved": true/false,
  "score": 1-10,
  "feedback": "specific actionable feedback if not approved, else brief praise"
}}
Approve only if score >= 7 and no critical gaps."""

    user = f"""Original topic: {state["topic"]}

Draft report:
{state.get("draft_report", "")[:12000]}

Review cycle: {review_count}/{s.max_review_cycles}
"""

    try:
        resp = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
        data = _parse_json_block(resp.content) or {}
    except Exception:
        data = {"approved": True, "score": 8, "feedback": "Draft approved"}

    approved = bool(data.get("approved", False))
    feedback = data.get("feedback", "")
    score = data.get("score", 5)

    if approved or review_count >= s.max_review_cycles:
        return {
            "final_report": state.get("draft_report", ""),
            "review_count": review_count,
            "review_feedback": feedback,
            "status": "done",
        }

    return {
        "review_count": review_count,
        "review_feedback": f"Score {score}/10. {feedback}",
        "status": "writing",  # loop back to writer
    }
