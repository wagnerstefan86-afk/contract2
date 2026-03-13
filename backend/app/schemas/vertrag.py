from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class VertragResponse(BaseModel):
    id: UUID
    dateiname: str
    status: str
    erstellt_am: datetime
    aktualisiert_am: datetime

    model_config = {"from_attributes": True}


class VertragDetail(VertragResponse):
    volltext: str | None = None
    absaetze: list | None = None
