from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class FundstelleResponse(BaseModel):
    id: UUID
    analyse_id: UUID
    vertrag_id: UUID
    textstelle: str
    absatz_ids: list | None = None
    kategorie: str
    risikostufe: str
    kurzbeschreibung: str
    erklaerung: str | None = None
    empfehlung: str | None = None
    quelle_pass: str | None = None
    pruef_status: str
    pruef_kommentar: str | None = None
    erstellt_am: datetime
    detail: dict | None = None
    zusammenfuehrung: dict | None = None
    # Paragraph-level evidence fields (nullable for legacy findings)
    scope_type: str | None = None
    scope_text: str | None = None
    trigger_spans: list | None = None
    evidence_heading_path: str | None = None
    evidence_page_from: int | None = None
    evidence_page_to: int | None = None

    model_config = {"from_attributes": True}


class ThemaEditorialContext(BaseModel):
    """Parent theme editorial data for the detail view."""
    thema_id: UUID | None = None
    titel: str = ""
    problem_summary: str = ""
    impact: list[str] = []
    recommendation: list[str] = []
    negotiation: list[str] = []
    warum_verhandlungsrelevant: str = ""
    alternativformulierung: str = ""
    bieterfrage: str = ""
    verhandlungsargumente: list[str] = []


class FundstelleDetailResponse(FundstelleResponse):
    """Extended response for single-fundstelle detail view with parent theme context."""
    thema_editorial: ThemaEditorialContext | None = None


class FundstelleUpdate(BaseModel):
    pruef_status: str | None = None
    pruef_kommentar: str | None = None
