"""Pydantic schemas for AnalysisCase and CaseDocument API responses."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class CaseDocumentResponse(BaseModel):
    id: UUID
    analysis_case_id: UUID
    filename: str
    original_mime_type: str | None = None
    sha256: str | None = None
    page_count: int | None = None
    char_count: int | None = None
    language: str | None = None
    document_type: str
    document_role_rank: int
    status: str
    parse_status: str
    classification_status: str
    created_at: datetime
    error_message: str | None = None

    model_config = {"from_attributes": True}


class AnalysisCaseResponse(BaseModel):
    id: UUID
    external_case_ref: str | None = None
    title: str
    customer_name: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    total_documents: int
    total_pages: int
    total_characters: int
    total_chunks: int
    total_findings: int
    total_themes: int
    total_final_themes: int
    pipeline_warnings: list[str] | None = None
    failure_reason: str | None = None

    model_config = {"from_attributes": True}


class AnalysisCaseDetail(AnalysisCaseResponse):
    documents: list[CaseDocumentResponse] = []
    processing_summary: dict | None = None


class AnalysisCaseCreate(BaseModel):
    title: str
    external_case_ref: str | None = None
    customer_name: str | None = None
    policy_profile_id: UUID | None = None
