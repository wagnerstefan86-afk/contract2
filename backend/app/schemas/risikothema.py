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

    @computed_field
    @property
    def anzahl(self) -> int:
        return len(self.fundstellen)

    model_config = {"from_attributes": True}
