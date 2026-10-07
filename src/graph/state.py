"""Shared state for the research multi-agent graph."""

from __future__ import annotations

import operator
from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel, Field


class SubQuestion(BaseModel):
    id: str
    question: str
    rationale: str = ""


class Finding(BaseModel):
    sub_question_id: str
    claim: str
    evidence: str
    sources: list[str] = Field(default_factory=list)
    confidence: float = 0.5  # 0–1


class FactCheckResult(BaseModel):
    claim: str
    status: Literal["VERIFIED", "PARTIALLY_VERIFIED", "UNVERIFIED", "CONTRADICTED"]
    notes: str = ""
    supporting_sources: list[str] = Field(default_factory=list)
    conflicting_sources: list[str] = Field(default_factory=list)


class ResearchState(TypedDict):
    # Input
    topic: str
    focus_mode: str  # broad | deep | verify

    # Planning
    sub_questions: list[dict]  # serialized SubQuestion

    # Research
    findings: Annotated[list[dict], operator.add]  # list of Finding dicts
    raw_search_notes: Annotated[list[str], operator.add]

    # Fact-checking
    fact_checks: list[dict]

    # Writing
    draft_report: str
    final_report: str

    # Control
    review_count: int
    review_feedback: str
    status: str  # planning | researching | fact_checking | writing | reviewing | done | error
    error: str
    sources_used: Annotated[list[str], operator.add]
