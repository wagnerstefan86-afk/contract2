"""Pydantic schemas for Policy Profile and related objects."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class PolicyRuleResponse(BaseModel):
    id: UUID
    name: str
    description: str | None = None
    rule_type: str
    match_scope: str
    pattern_type: str
    action: str
    priority: int
    is_active: bool
    conditions_json: dict | None = None

    model_config = {"from_attributes": True}


class PolicyProfileResponse(BaseModel):
    id: UUID
    name: str
    version: str
    description: str | None = None
    is_active: bool
    created_at: datetime
    rules: list[PolicyRuleResponse] = []

    model_config = {"from_attributes": True}


class PositiveControlResponse(BaseModel):
    id: UUID
    analysis_case_id: UUID
    case_document_id: UUID
    document_section_id: UUID | None = None
    control_type: str
    control_value: str
    source_text: str
    status: str
    notes: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentSectionResponse(BaseModel):
    id: UUID
    case_document_id: UUID
    section_index: int
    page_from: int | None = None
    page_to: int | None = None
    heading_path: str | None = None
    section_type: str
    char_count: int
    token_estimate: int
    routing: str | None = None
    routing_reason: str | None = None

    model_config = {"from_attributes": True}
