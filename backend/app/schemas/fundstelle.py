from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class FundstelleResponse(BaseModel):
    id: UUID
    analyse_id: UUID
    vertrag_id: UUID
    textstelle: str
    kategorie: str
    risikostufe: str
    kurzbeschreibung: str
    erklaerung: str | None = None
    empfehlung: str | None = None
    quelle_pass: str | None = None
    pruef_status: str
    pruef_kommentar: str | None = None
    erstellt_am: datetime

    model_config = {"from_attributes": True}


class FundstelleUpdate(BaseModel):
    pruef_status: str | None = None
    pruef_kommentar: str | None = None
