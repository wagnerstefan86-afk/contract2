import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime, Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

import enum


class VertragStatus(str, enum.Enum):
    HOCHGELADEN = "Hochgeladen"
    EXTRAHIERT = "Extrahiert"
    IN_ANALYSE = "In Analyse"
    ANALYSIERT = "Analysiert"
    ARCHIVIERT = "Archiviert"


class Vertrag(Base):
    __tablename__ = "vertraege"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dateiname: Mapped[str] = mapped_column(String(500))
    dateipfad: Mapped[str] = mapped_column(String(1000))
    volltext: Mapped[str | None] = mapped_column(Text, nullable=True)
    absaetze: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    seiten_map: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default=VertragStatus.HOCHGELADEN.value)
    erstellt_am: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    aktualisiert_am: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    analysen = relationship("Analyse", back_populates="vertrag", cascade="all, delete-orphan")
    fundstellen = relationship("Fundstelle", back_populates="vertrag", cascade="all, delete-orphan")
