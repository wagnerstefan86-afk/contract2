"""Pydantic schemas for RisikoThema API responses."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, computed_field

# Valid decision states
DECISION_STATES = {"OPEN", "IN_NEGOTIATION", "ACCEPTED", "REJECTED", "CLOSED"}


class EvidenceItem(BaseModel):
    """A single piece of contract evidence supporting a risk theme."""
    scope_text: str
    segment_id: str | None = None
    trigger_spans: list[str] | None = None
    heading_path: str | None = None


class RisikoThemaFundstelleResponse(BaseModel):
    """Lightweight Fundstelle representation nested inside a RisikoThema."""
    id: UUID
    kurzbeschreibung: str
    kategorie: str
    risikostufe: str
    textstelle: str
    pruef_status: str
    # Paragraph-level evidence (nullable for legacy findings)
    scope_type: str | None = None
    scope_text: str | None = None
    trigger_spans: list | None = None
    evidence_heading_path: str | None = None

    model_config = {"from_attributes": True}


class RisikoThemaResponse(BaseModel):
    """Full RisikoThema with nested Fundstellen."""
    id: UUID
    analyse_id: UUID
    vertrag_id: UUID
    titel: str
    kategorie: str
    risikostufe: str
    beschreibung: str
    sortierung: int
    erstellt_am: datetime
    fundstellen: list[RisikoThemaFundstelleResponse]
    evidences: list[EvidenceItem] = []
    final_selected: bool = False
    final_verwerfungsgrund: str | None = None
    final_editorial: dict | None = None

    @computed_field
    @property
    def anzahl(self) -> int:
        return len(self.fundstellen)

    model_config = {"from_attributes": True}


# --- Final Editorial Pass response schemas ---

class FinalesThemaFundstelleResponse(BaseModel):
    """Fundstelle within a final editorial theme — primary or secondary."""
    id: UUID
    kurzbeschreibung: str
    kategorie: str
    risikostufe: str
    textstelle: str
    pruef_status: str
    ist_primaer: bool = False
    # Paragraph-level evidence (nullable for legacy findings)
    scope_type: str | None = None
    scope_text: str | None = None
    trigger_spans: list | None = None
    evidence_heading_path: str | None = None

    model_config = {"from_attributes": True}


class FinalesThemaResponse(BaseModel):
    """A final editorial theme — the main output for reviewers."""
    id: UUID
    titel: str
    kategorie: str
    risikostufe: str
    kurzbeschreibung: str
    warum_verhandlungsrelevant: str
    alternativformulierung: str
    bieterfrage: str
    verhandlungsargumente: list[str]
    problem_summary: str = ""
    impact: list[str] = []
    recommendation: list[str] = []
    negotiation: list[str] = []
    fundstellen: list[FinalesThemaFundstelleResponse]
    evidences: list[EvidenceItem] = []
    sortierung: int
    # Decision layer
    decision_status: str = "OPEN"
    decision_comment: str | None = None
    recommendation_override: str | None = None
    negotiation_override: str | None = None
    decided_by_user_id: UUID | None = None
    decided_by_name: str | None = None
    decided_at: datetime | None = None
    decision_updated_at: datetime | None = None


class VerworfenesThemaResponse(BaseModel):
    """A rejected theme — shown only in debug view."""
    id: UUID
    titel: str
    kategorie: str
    grund: str


class FinalEditorialResponse(BaseModel):
    """Complete final editorial pass result."""
    finale_themen: list[FinalesThemaResponse]
    verworfene_themen: list[VerworfenesThemaResponse]
    metriken: dict


class DecisionUpdate(BaseModel):
    """Request body for updating a theme's decision state."""
    decision_status: str | None = None
    decision_comment: str | None = None
    recommendation_override: str | None = None
    negotiation_override: str | None = None
