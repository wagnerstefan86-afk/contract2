from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class AnalyseResponse(BaseModel):
    id: UUID
    vertrag_id: UUID
    status: str
    aktueller_pass: str | None = None
    fortschritt: int
    gestartet_am: datetime
    beendet_am: datetime | None = None
    fehler: str | None = None

    model_config = {"from_attributes": True}
