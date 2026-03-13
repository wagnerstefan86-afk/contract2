import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

import enum


class ProtokollEbene(str, enum.Enum):
    INFO = "Info"
    WARNUNG = "Warnung"
    FEHLER = "Fehler"


class Protokoll(Base):
    __tablename__ = "protokolle"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analyse_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("analysen.id", ondelete="SET NULL"), nullable=True)
    vertrag_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("vertraege.id", ondelete="SET NULL"), nullable=True)
    ebene: Mapped[str] = mapped_column(String(50), default=ProtokollEbene.INFO.value)
    nachricht: Mapped[str] = mapped_column(Text)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    erstellt_am: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
