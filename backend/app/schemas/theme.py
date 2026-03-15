"""Pydantic schemas for Theme API responses."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ThemeEvidenceResponse(BaseModel):
    id: UUID
    finding_id: UUID
    evidence_role: str
    rank: int
    # Denormalized finding fields
    kurzbeschreibung: str | None = None
    kategorie: str | None = None
    risikostufe: str | None = None
    textstelle: str | None = None
    # Paragraph-level evidence (nullable for legacy)
    scope_type: str | None = None
    scope_text: str | None = None
    trigger_spans: list | None = None
    evidence_heading_path: str | None = None

    model_config = {"from_attributes": True}


class ThemeResponse(BaseModel):
    id: UUID
    analysis_case_id: UUID
    category: str
    canonical_title: str
    canonical_summary: str | None = None
    severity: str
    source_finding_count: int
    source_document_count: int
    conflict_detected: bool
    conflict_summary: str | None = None
    final_selected: bool
    final_rank: int | None = None
    final_editorial_json: dict | None = None
    final_rejection_reason: str | None = None
    final_selection_basis: str | None = None
    created_at: datetime
    evidence: list[ThemeEvidenceResponse] = []

    model_config = {"from_attributes": True}


class CaseThemesResponse(BaseModel):
    themes: list[ThemeResponse]
    total_themes: int
    total_final: int
    total_findings: int
