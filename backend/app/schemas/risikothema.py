"""Pydantic schemas for RisikoThema API responses."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, computed_field


class RisikoThemaFundstelleResponse(BaseModel):
    """Lightweight Fundstelle representation nested inside a RisikoThema."""
    id: UUID
    kurzbeschreibung: str
    kategorie: str
    risikostufe: str
    textstelle: str
    pruef_status: str

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
    fundstellen: list[FinalesThemaFundstelleResponse]
    sortierung: int


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
