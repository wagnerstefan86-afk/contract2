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


class FundstelleUpdate(BaseModel):
    pruef_status: str | None = None
    pruef_kommentar: str | None = None
