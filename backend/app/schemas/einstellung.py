from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class EinstellungResponse(BaseModel):
    id: UUID
    schluessel: str
    wert: str
    beschreibung: str | None = None
    aktualisiert_am: datetime

    model_config = {"from_attributes": True}


class EinstellungUpdate(BaseModel):
    wert: str
